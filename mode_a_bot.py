"""
Mode A Bot — Abstract multi-term search + notifier
- Polls multiple marketplaces at intervals
- Applies model range, price band, shipping requirement
- Uses include/exclude multi-terms & variants (abstract, user-provided)
- Sends rich notifications to Telegram
"""

import os, time, json, re, unicodedata, hashlib, logging
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Bot

# ---------------- Setup ----------------
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
if not TOKEN or not CHAT_ID:
    raise RuntimeError("Missing env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")

bot = Bot(token=TOKEN)
HEADERS = {"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------- Utils ----------------
def load_cfg():
    with open("mode_a_config.json", "r", encoding="utf-8") as f:
        return json.load(f)

def normalize(txt: str) -> str:
    if not txt: return ""
    txt = unicodedata.normalize("NFKD", txt).encode("ascii","ignore").decode("ascii")
    return re.sub(r"\s+", " ", txt.strip().lower())

def parse_price(text: str):
    if not text: return None
    text = text.replace("\xa0"," ")
    m = re.search(r"(\d[\d\s]{0,6})\s*€", text)
    if m:
        try: return int(m.group(1).replace(" ", ""))
        except: return None
    return None

def fingerprint(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()

def in_model_range(title: str, models: list) -> bool:
    t = normalize(title)
    return any(normalize(m) in t for m in models) if models else True

def price_ok(price, cfg) -> bool:
    if price is None: return True
    try:
        p = float(price)
        return cfg["price_min"] <= p <= cfg["price_max"]
    except:
        return True

def shipping_passes(text: str, cfg) -> bool:
    if not cfg.get("require_shipping", False):
        return True
    t = normalize(text)
    pos = any(normalize(w) in t for w in cfg.get("shipping_positive", [])) if cfg.get("shipping_positive") else True
    neg = any(normalize(w) in t for w in cfg.get("shipping_negative", [])) if cfg.get("shipping_negative") else False
    return pos and not neg

def terms_pass(title: str, desc: str, cfg) -> bool:
    t = normalize(f"{title or ''} {desc or ''}")
    inc_groups = cfg.get("terms_any", [])
    opt_terms  = cfg.get("terms_optional", [])
    exc_terms  = cfg.get("terms_exclude", [])
    # terms_any means: at least one term from ANY of the groups must appear overall
    ok_any = True
    if inc_groups:
        ok_any = any(any(normalize(term) in t for term in group) for group in inc_groups)
    ok_opt = True  # optional group: no constraint, but used for future scoring
    # exclude: none of these should appear
    ok_exc = not any(normalize(term) in t for term in exc_terms) if exc_terms else True
    return ok_any and ok_exc

def send_telegram(item, tag=None):
    prefix = f"{tag} " if tag else ""
    lines = [
        f"{prefix}{'📱' if 'iphone' in normalize(item.get('title','')) else '📟'} {item.get('title','(Sans titre)')}",
        f"💶 {item.get('price','?')}",
        f"🔗 {item.get('url')}"
    ]
    msg = "\n".join(lines)
    try:
        if item.get("photo"):
            bot.send_photo(CHAT_ID, photo=item["photo"], caption=msg)
        else:
            bot.send_message(CHAT_ID, text=msg)
    except Exception as e:
        logging.warning(f"Telegram send failed: {e}")

# ---------------- Parsers ----------------
def fetch_leboncoin(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for a in soup.select("a[href*='/vi/']"):
        href = a.get("href") or ""
        if not href: 
            continue
        link = "https://www.leboncoin.fr" + href if href.startswith("/") else href
        title = a.get_text(" ", strip=True)
        price_el = a.find_next(lambda tag: tag.name in ["span","div"] and "€" in (tag.get_text() or ""))
        price = parse_price(price_el.get_text() if price_el else None)
        img = None
        imgtag = a.find("img")
        if imgtag:
            img = imgtag.get("src") or imgtag.get("data-src")
        desc = ""
        sib = a.find_next("p")
        if sib:
            desc = sib.get_text(" ", strip=True)
        items.append({"title": title, "price": price, "url": link, "photo": img, "desc": desc, "platform": "leboncoin"})
    return items

def fetch_vinted(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for a in soup.select("a[href*='/items/']"):
        href = a.get("href") or ""
        if not href: 
            continue
        link = "https://www.vinted.fr" + href if href.startswith("/") else href
        title = a.get_text(" ", strip=True)
        price_el = a.find(lambda tag: tag.name in ["span","div"] and "€" in (tag.get_text() or ""))
        price = parse_price(price_el.get_text() if price_el else None)
        img = None
        imgtag = a.find("img")
        if imgtag:
            img = imgtag.get("src") or imgtag.get("data-src")
        desc = ""
        items.append({"title": title, "price": price, "url": link, "photo": img, "desc": desc, "platform": "vinted"})
    return items

# ---------------- Core loop ----------------
def run_once(cfg, seen):
    results = []
    # Aggregate from sources
    if "leboncoin" in cfg.get("platforms", []):
        for u in cfg["leboncoin"]["base_urls"]:
            try: results += fetch_leboncoin(u)
            except Exception as e:
                logging.warning(f"LBC fetch fail: {e}"); time.sleep(2)
    if "vinted" in cfg.get("platforms", []):
        for u in cfg["vinted"]["base_urls"]:
            try: results += fetch_vinted(u)
            except Exception as e:
                logging.warning(f"Vinted fetch fail: {e}"); time.sleep(2)

    # Filter & notify
    for it in results:
        fid = fingerprint(it["url"])
        if fid in seen:
            continue
        title = it.get("title","")
        desc  = it.get("desc","")
        price = it.get("price")

        if not in_model_range(title, cfg.get("models", [])):
            continue
        if not price_ok(price, cfg):
            continue
        if not shipping_passes(f"{title} {desc}", cfg):
            continue
        if not terms_pass(title, desc, cfg):
            continue

        send_telegram(it, tag=cfg.get("tag_prefix"))
        seen.add(fid)

def main():
    cfg = load_cfg()
    seen = set()
    bot.send_message(CHAT_ID, text="✅ Mode A Bot démarré.")
    while True:
        try:
            cfg = load_cfg()
            run_once(cfg, seen)
            time.sleep(int(cfg.get("search_interval_seconds", 180)))
        except Exception as e:
            logging.error(f"Loop error: {e}")
            try: bot.send_message(CHAT_ID, text=f"⚠️ Bot: {e}")
            except: pass
            time.sleep(120)

if __name__ == "__main__":
    main()
