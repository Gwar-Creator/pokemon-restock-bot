"""Discord V2 alert presentation. Pure, conservative, and not enabled in production.

Do not map generic 'in_stock' or a hidden catalog hit to 'online_buyable'.
An adapter must provide explicit, recently verified channel-specific evidence.
"""
from math import isfinite
from urllib.parse import urlsplit

STATUS = {
    "BUY_NOW": ("KØB NU", 0x57F287, "Onlinekøb bekræftet ved seneste kontrol. Lager kan ændre sig."),
    "RESERVE_NOW": ("RESERVÉR NU", 0x3498DB, "Click & Collect bekræftet ved seneste kontrol. Reservation kan ændre sig."),
    "STORE_STOCK": ("BUTIKSLAGER", 0xE67E22, "Positivt registreret butikslager. Køb og reservation er ikke bekræftet."),
    "PREPUBLISH": ("KLARGØRES", 0xF1C40F, "Skjult eller endnu ikke offentliggjort vare. Ikke bekræftet købbar."),
    "PREORDER": ("FORUDBESTIL", 0x9B59B6, "Aktiv forudbestilling, ikke en vare på lager."),
    "UNKNOWN": ("UKENDT", 0x95A5A6, "Datakilderne er utilstrækkelige eller modstridende. Kontrollér manuelt."),
}

MAX_STORE_LINES = 12


def safe_url(value):
    """Return a public HTTP(S) URL or empty string; never guess links."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > 2048 or any(char.isspace() for char in value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return ""
        if parsed.username or parsed.password:
            return ""
    except ValueError:
        return ""
    return value


def positive_stores(event):
    """Only explicit positive stock counts are evidence of system stock."""
    found = []
    for store in event.get("stores") or []:
        if not isinstance(store, dict):
            continue
        name = str(store.get("name") or "").strip()
        raw_count = store.get("stock")
        if not name or isinstance(raw_count, bool):
            continue
        try:
            count = int(raw_count)
        except (ValueError, TypeError, OverflowError):
            continue
        if count > 0:
            found.append((name, count))
    return found


def classify(event):
    """Choose the strongest *verified* action, never infer purchasing from stock."""
    stores = positive_stores(event)
    link = safe_url(event.get("url"))
    online = event.get("online_buyable") is True
    reservable = event.get("click_collect_reservable") is True
    preorder = event.get("preorder_open") is True
    hidden = event.get("is_pre_publish") is True

    # Conflicting source signals are unsafe to promote as purchase opportunities.
    if (hidden and (online or reservable)) or (preorder and (online or reservable)):
        return "UNKNOWN"
    if online and link:
        return "BUY_NOW"
    if reservable and stores and link:
        return "RESERVE_NOW"
    if preorder and link:
        return "PREORDER"
    if hidden:
        return "PREPUBLISH"
    if stores:
        return "STORE_STOCK"
    return "UNKNOWN"


def format_price(value):
    if value is None or isinstance(value, bool):
        return ""
    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError):
        return ""
    if not isfinite(price) or price <= 0:
        return ""
    return f"{price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " kr."


def render_embed(event):
    """Build one Discord embed without posting anything or touching scanner state."""
    key = classify(event)
    label, color, explanation = STATUS[key]
    source = str(event.get("source") or "Ukendt kilde").strip()[:80]
    name = str(event.get("name") or "Ukendt produkt").strip()[:220]
    link = safe_url(event.get("url"))
    stores = positive_stores(event)

    fields = [{"name": "STATUS", "value": explanation, "inline": False}]
    price = format_price(event.get("price"))
    if price:
        fields.append({"name": "PRIS", "value": price, "inline": True})

    if stores:
        lines = [f"{store}: {count} stk." for store, count in stores[:MAX_STORE_LINES]]
        remaining = len(stores) - len(lines)
        if remaining:
            lines.append(f"… samt {remaining} yderligere butikker")
        fields.append({"name": "REGISTRERET BUTIKSLAGER", "value": "\n".join(lines)[:1024], "inline": False})

    if event.get("is_pre_publish") is True and stores:
        fields.append({
            "name": "VIGTIGT",
            "value": "Systemlager på skjult vare er ikke dokumentation for, at varen sælges i butikken.",
            "inline": False,
        })

    checked = str(event.get("checked_at") or "").strip()
    if checked:
        fields.append({"name": "SENEST KONTROLLERET", "value": checked[:100], "inline": True})

    embed = {
        "title": f"{label} · {source}"[:256],
        "description": f"**{name}**",
        "color": color,
        "fields": fields,
        "footer": {"text": f"MasterBot · {key} · Kildedata, ikke købsgaranti"},
    }
    if link and key in ("BUY_NOW", "RESERVE_NOW", "PREORDER"):
        embed["url"] = link
    image = safe_url(event.get("image_url"))
    if image:
        embed["thumbnail"] = {"url": image}
    return embed


def webhook_payload(event):
    return {"username": "MasterBot", "allowed_mentions": {"parse": []}, "embeds": [render_embed(event)]}
