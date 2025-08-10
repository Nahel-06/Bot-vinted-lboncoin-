"""
mode_a_bot_web.py
- For Render *Web Service* free plan (binds to $PORT)
- Starts a tiny HTTP server (healthcheck) AND runs the Mode A bot loop
- Uses synchronous Telegram HTTP API
"""

import os, time, json, re, unicodedata, hashlib, logging, threading
import requests
from bs4 import BeautifulSoup
from http.server import BaseHTTPRequestHandler, HTTPServer

# -------------------- Config --------------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
if not TOKEN or not CHAT_ID:
    raise RuntimeError("Missing env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")

API_BASE = f"https://api.telegram.org/bot{TOKEN}"
HEADERS = {"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CONFIG_PATH = "mode_a_config.json"

# -------------------- Tiny HTTP server --------------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        return  # silence default logging

def start_http_server():
    port = int(os.environ.get("PORT", "10000"))
    httpd = HTTPServer(("0.0.0.0", port), HealthHandler)
    logging.info(f"HTTP health server listening on :{port}")
    httpd.serve_forever()

# -------------------- Bot helpers --------------------
def load_cfg():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
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
    if not models: return True
    t = normalize(title)
    return any(normalize(m) in t for m in models)

def price_ok(price, cfg) -> bool:
    if price is None: return True
    try:
        p = float(price)
        return cfg.get("price_min", 0) <= p <= cfg.get("price_max", 10**9)
    except:
        return True

def shipping_passes(text: str, cfg) -> bool:
    if not cfg.get("require_shipping", False):
        return True
    t = normalize(text)
    pos_terms = [normalize(w) for w in cfg.get("shipping_positive", [])]
    neg_terms = [normalize(w) for w in cfg.get("shipping_negative", [])]
    has_pos = any(w in t for w in pos_terms) if pos_terms else True
    has_neg = any(w in t for w in neg_terms) if neg_terms else False
    return has_pos and not has_neg

def terms_pass(title: str, desc: str, cfg) -> bool:
    t = normalize(f"{title or ''} {desc or ''}")
    inc_groups = cfg.get("terms_any", [])
    exc_terms  = [normalize(x) for x in cfg.get("terms_exclude", [])]
    ok_any = True
    if inc_groups:
        ok_any = any(any(normalize(term) in t for term in group) for group in inc_groups)
    ok_exc = not any(x in t for x in exc_terms) if exc_terms else True
    return ok_any and ok_exc

# Telegram sync
def tg_send_message(text: str):
    try:
        r = requests.post(f"{API_BASE}/sendMessage", data={"chat_id": CHAT_ID, "text": text})
        r.raise_for_status()
    except Exception as e:
        logging.warning(f"Telegram sendMessage failed: {e}")

def tg_send_photo(photo_url: str, caption: str):
    try:
        r = requests.post(f"{API_BASE}/sendPhoto", data={"chat_id": CHAT_ID, "photo": photo_url, "caption": caption})
        r.raise_for_status()
    except Exception as e:
        logging.warning(f"Telegram sendPhoto failed: {e}")

def send_telegram(item, tag=None):
    prefix = f"{tag} " if tag else ""
    lines = [
        f"{prefix}{'📱' if 'iphone' in normalize(item.get('title','')) else '📟'} {item.get('title','(Sans titre)')}",
        f"💶 {item.get('price','?')}",
        f"🔗 {item.get('url')}"
    ]
    msg = "\n".join(lines)
    if item.get("photo"):
        tg_send_photo(item["photo"], msg)
    else:
        tg_send_message(msg)

# Parsers
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

# Core bot
def bot_loop():
    tg_send_message("✅ Mode A Bot (web) démarré.")
    seen = set()
    while True:
        try:
            cfg = load_cfg()
            results = []

            if "leboncoin" in cfg and "base_urls" in cfg.get("leboncoin", {}):
                for u in cfg["leboncoin"]["base_urls"]:
                    try:
                        results += fetch_leboncoin(u)
                    except Exception as e:
                        logging.warning(f"LBC fetch fail: {e}")
                        time.sleep(2)

            if "vinted" in cfg and "base_urls" in cfg.get("vinted", {}):
                for u in cfg["vinted"]["base_urls"]:
                    try:
                        results += fetch_vinted(u)
                    except Exception as e:
                        logging.warning(f"Vinted fetch fail: {e}")
                        time.sleep(2)

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
                if not terms_pass(title, desc, cfg):
                    continue
                if not shipping_passes(f"{title} {desc}", cfg):
                    continue

                send_telegram(it, tag=cfg.get("tag_prefix"))
                seen.add(fid)

            time.sleep(int(cfg.get("search_interval_seconds", 180)))
        except Exception as e:
            logging.error(f"Loop error: {e}")
            try:
                tg_send_message(f"⚠️ Bot: {e}")
            except:
                pass
            time.sleep(120)

if __name__ == "__main__":
    # Start HTTP health server in a thread
    t = threading.Thread(target=start_http_server, daemon=True)
    t.start()
    # Run bot loop in main thread
    bot_loop()
