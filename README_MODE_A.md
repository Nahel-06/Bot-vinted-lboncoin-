
# Mode A Bot — Multi-termes (abstrait) → Telegram

## Contenu
- `mode_a_bot.py` — script
- `mode_a_config.json` — configuration
- `requirements.txt`

## Utilisation (local ou Render)
1. Crée un bot Telegram (BotFather) → récupère TOKEN.
2. Récupère ton CHAT_ID (@userinfobot).
3. Variables d'environnement:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Installe:
   ```bash
   pip install -r requirements.txt
   ```
5. Lance:
   ```bash
   python mode_a_bot.py
   ```

## Configuration (mode_a_config.json)
- `models`: liste des modèles/variantes cibles.
- `price_min`/`price_max`: plage de prix.
- `require_shipping`: True pour retenir uniquement les annonces indiquant l'envoi.
- `shipping_positive` / `shipping_negative`: indices textuels pour l'expédition.
- `terms_any`: liste de groupes; au moins un terme d'un des groupes doit apparaître.
- `terms_optional`: variantes facultatives (pas obligatoires).
- `terms_exclude`: termes à exclure.
- `search_interval_seconds`: intervalle de scan (secondes).
- `tag_prefix`: préfixe emoji dans la notif.

> Ce pack est abstrait et neutre: il n'encode aucun ciblage illégal. Configure uniquement des critères légitimes.
