from pathlib import Path

BOT = Path("restock_bot_github.py")
PATCH = Path("patch_v141.py")

text = BOT.read_text(encoding="utf-8")

# Built-in CSV support for the Excel-friendly export.
if "import csv\n" not in text:
    text = text.replace("import json\n", "import json\nimport csv\nimport io\n", 1)
elif "import io\n" not in text:
    text = text.replace("import csv\n", "import csv\nimport io\n", 1)

start = text.index("def _price_history_daily_summary(")
end = text.index("\n\ndef process_price_history(", start)

replacement = r'''def _price_history_row_line(entry):
    diff = _history_pct(
        entry.get("current_best"),
        entry.get("historical_low")
    )
    low_shops = entry.get("historical_low_shops") or []
    low_shop = " + ".join(low_shops) if low_shops else "-"
    current_shops = entry.get("current_shops") or []
    current_shop = " + ".join(current_shops) if current_shops else entry.get("current_shop") or "-"

    return (
        f"**{entry.get('label') or 'Ukendt produkt'}**\n"
        f"Lavest **{format_price(entry.get('historical_low'))}** · {low_shop}  |  "
        f"Nu **{format_price(entry.get('current_best'))}** · {current_shop}  |  "
        f"**{_history_pct_text(diff)}**"
    )


def _price_history_category_embeds(game, entries):
    order = {value: index for index, value in enumerate(PRICE_WATCH_TYPE_ORDER)}
    grouped = {}

    for entry in entries:
        info = parse_price_watch_key(entry["product_key"])
        grouped.setdefault(info["type"], []).append(entry)

    embeds = []

    for product_type in sorted(grouped, key=lambda value: order.get(value, 99)):
        category_entries = sorted(
            grouped[product_type],
            key=lambda entry: entry["label"].lower()
        )

        chunks = []
        current = []
        current_len = 0

        for entry in category_entries:
            block = _price_history_row_line(entry)
            block_len = len(block) + 2

            if current and current_len + block_len > 3700:
                chunks.append(current)
                current = []
                current_len = 0

            current.append(block)
            current_len += block_len

        if current:
            chunks.append(current)

        for index, chunk in enumerate(chunks, start=1):
            suffix = (
                f" · {index}/{len(chunks)}"
                if len(chunks) > 1
                else ""
            )
            embeds.append({
                "title": (
                    f"{price_watch_game_label(game)} · "
                    f"{price_watch_type_label(product_type)}"
                    f" ({len(category_entries)}){suffix}"
                )[:256],
                "description": "\n\n".join(chunk)[:4096],
                "color": 0x5865F2 if game == "POKÉMON" else 0x9B59B6,
                "footer": {
                    "text": "Lavest = dansk rekord siden tracking start · Diff = nu vs. rekord"
                },
            })

    return embeds


def _send_price_history_embed_batches(embeds):
    if not PRICE_HISTORY_WEBHOOK_URL or not embeds:
        return False

    sent = False

    for index in range(0, len(embeds), 10):
        batch = embeds[index:index + 10]
        response = requests.post(
            PRICE_HISTORY_WEBHOOK_URL,
            json={
                "username": "MasterBot",
                "allowed_mentions": {"parse": []},
                "embeds": batch,
            },
            headers={
                "User-Agent": "Pokemon-Lorcana-MasterBot/1.4.1"
            },
            timeout=20,
        )
        response.raise_for_status()
        sent = True

    return sent


def _send_price_history_csv(products, active_keys, now_local):
    if not PRICE_HISTORY_WEBHOOK_URL:
        return False

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Game",
        "Kategori",
        "Produkt",
        "Historisk laveste DKK",
        "Laveste butik",
        "Laveste dato",
        "Nuværende pris DKK",
        "Nuværende butik",
        "Difference %",
        "Produkt URL",
    ])

    rows = []

    for product_key in active_keys:
        entry = products.get(product_key)
        if not isinstance(entry, dict):
            continue

        info = parse_price_watch_key(product_key)
        diff = _history_pct(
            entry.get("current_best"),
            entry.get("historical_low")
        )
        low_shops = " + ".join(entry.get("historical_low_shops") or [])
        current_shops = " + ".join(entry.get("current_shops") or [])

        rows.append((
            info["game"],
            price_watch_type_label(info["type"]),
            price_watch_display_name(product_key),
            entry.get("historical_low"),
            low_shops,
            entry.get("historical_low_date") or "",
            entry.get("current_best"),
            current_shops or entry.get("current_shop") or "",
            None if diff is None else round(diff, 1),
            entry.get("current_url") or "",
        ))

    rows.sort(key=lambda row: (row[0], row[1], row[2].lower()))

    for row in rows:
        writer.writerow(row)

    filename = f"price_history_{now_local.strftime('%Y-%m-%d')}.csv"
    payload = {
        "username": "MasterBot",
        "content": (
            "📎 **Fuld Price History** · Excel/CSV · "
            f"{len(rows)} aktive produkter"
        ),
        "allowed_mentions": {"parse": []},
    }

    response = requests.post(
        PRICE_HISTORY_WEBHOOK_URL,
        data={"payload_json": json.dumps(payload, ensure_ascii=False)},
        files={
            "files[0]": (
                filename,
                output.getvalue().encode("utf-8-sig"),
                "text/csv",
            )
        },
        headers={
            "User-Agent": "Pokemon-Lorcana-MasterBot/1.4.1"
        },
        timeout=30,
    )
    response.raise_for_status()
    return True


def _price_history_daily_summary(products, active_keys, now_local, started_at):
    if not PRICE_HISTORY_WEBHOOK_URL:
        return False

    active_entries = []

    for product_key in active_keys:
        entry = products.get(product_key)
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        row["product_key"] = product_key
        row["label"] = price_watch_display_name(product_key)
        active_entries.append(row)

    if not active_entries:
        return False

    sent_any = False

    # One categorized dashboard per game. Discord supports up to 10 embeds
    # per webhook message; categories are automatically chunked if needed.
    for game in ("POKÉMON", "LORCANA"):
        game_entries = [
            entry for entry in active_entries
            if parse_price_watch_key(entry["product_key"])["game"] == game
        ]

        if not game_entries:
            continue

        embeds = _price_history_category_embeds(game, game_entries)
        if _send_price_history_embed_batches(embeds):
            sent_any = True

    # Full untruncated Excel-friendly export once per daily dashboard.
    if _send_price_history_csv(products, active_keys, now_local):
        sent_any = True

    return sent_any
'''

text = text[:start] + replacement + text[end:]

# First-ever baseline should not flood the channel with a massive dashboard.
# Store the baseline and send one concise status card + CSV instead.
old_daily = '''    if daily_due:
        if _price_history_daily_summary(
            next_products,
            active_keys,
            now_local,
            started_at,
        ):
            last_daily_date = today
'''
new_daily = '''    if daily_due:
        if first_run:
            pokemon_count = sum(
                1 for key in active_keys
                if parse_price_watch_key(key)["game"] == "POKÉMON"
            )
            lorcana_count = sum(
                1 for key in active_keys
                if parse_price_watch_key(key)["game"] == "LORCANA"
            )

            send_price_history_embed(
                "📊 PRICE HISTORY AKTIVERET",
                (
                    f"Baseline gemt for **{len(active_keys)} aktive produkter**.\n\n"
                    f"⚡ Pokémon: **{pokemon_count}**\n"
                    f"✨ Lorcana: **{lorcana_count}**\n\n"
                    "Fra nu registreres nye historiske lavpunkter. "
                    "Den kategoriserede oversigt sendes én gang dagligt."
                ),
                color=0x5865F2,
                footer=f"Historik startet {started_at[:10]}",
            )
            _send_price_history_csv(
                next_products,
                active_keys,
                now_local,
            )
            last_daily_date = today
        elif _price_history_daily_summary(
            next_products,
            active_keys,
            now_local,
            started_at,
        ):
            last_daily_date = today
'''

if old_daily not in text:
    raise RuntimeError("Could not find Price History daily summary hook")
text = text.replace(old_daily, new_daily, 1)

BOT.write_text(text, encoding="utf-8")
PATCH.unlink(missing_ok=True)
print("V1.4.1 applied: categorized Price History + full CSV export.")
