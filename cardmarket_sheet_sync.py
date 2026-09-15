#!/usr/bin/env python3
"""Daily Cardmarket price-guide -> Google Sheets portfolio sync."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

POKEMON_GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"
LORCANA_GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_19.json"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
INVENTORY_RANGE = "Inventory!A1:AY2000"
HISTORY_RANGE = "'Price History'!A:J"
GREEN_THRESHOLD = 0.10
RED_THRESHOLD = -0.10
MIN_ABS_CHANGE_DKK = 5.0
TARGET_LOOKBACK_DAYS = 30


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def cell(row: list[Any], idx: int, default: Any = "") -> Any:
    if idx >= len(row) or row[idx] is None:
        return default
    return row[idx]


def header_map(row: list[Any]) -> dict[str, int]:
    return {str(value): idx for idx, value in enumerate(row) if value not in (None, "")}


def sheet_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
    text = str(value).strip().split()[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def date_formula(value: date) -> str:
    return f"=DATE({value.year};{value.month};{value.day})"


def fetch_guide(url: str) -> tuple[date, dict[int, dict[str, Any]]]:
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    payload = response.json()
    guide_date = datetime.strptime(payload["createdAt"], "%Y-%m-%dT%H:%M:%S%z").date()
    guide = {int(item["idProduct"]): item for item in payload.get("priceGuides", [])}
    if not guide:
        raise RuntimeError(f"Empty Cardmarket guide: {url}")
    return guide_date, guide


def choose_prices(item: dict[str, Any], game: str, variant: str) -> tuple[float | None, float | None, float | None, float | None]:
    game = (game or "").strip().lower()
    variant = (variant or "").strip().lower()

    if game in ("pokemon", "pokémon"):
        explicit_holo = "reverse holo" in variant or (
            "holo" in variant
            and not any(token in variant for token in ("full art", "illustration", "sir", "special illustration"))
        )
        if explicit_holo and item.get("trend-holo") not in (None, 0, 0.0):
            return (
                as_float(item.get("trend-holo")),
                as_float(item.get("low-holo")),
                as_float(item.get("avg7-holo")),
                as_float(item.get("avg30-holo")),
            )

    if game == "lorcana" and "foil" in variant and item.get("trend-foil") not in (None, 0, 0.0):
        return (
            as_float(item.get("trend-foil")),
            as_float(item.get("low-foil")),
            as_float(item.get("avg7-foil")),
            as_float(item.get("avg30-foil")),
        )

    return (
        as_float(item.get("trend")),
        as_float(item.get("low")),
        as_float(item.get("avg7")),
        as_float(item.get("avg30")),
    )


def get_values(service: Any, spreadsheet_id: str, range_name: str) -> list[list[Any]]:
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueRenderOption="UNFORMATTED_VALUE",
            dateTimeRenderOption="SERIAL_NUMBER",
        )
        .execute()
    )
    return result.get("values", [])


def batch_write(service: Any, spreadsheet_id: str, data: list[dict[str, Any]]) -> None:
    for start in range(0, len(data), 400):
        chunk = data[start : start + 400]
        if not chunk:
            continue
        (
            service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": chunk},
            )
            .execute()
        )


def append_history(service: Any, spreadsheet_id: str, rows: list[list[Any]]) -> None:
    if not rows:
        return
    (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=HISTORY_RANGE,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        )
        .execute()
    )


def parse_history(values: list[list[Any]]) -> tuple[set[tuple[date, str]], dict[str, list[tuple[date, float]]]]:
    keys: set[tuple[date, str]] = set()
    series: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in values[1:]:
        if len(row) < 10:
            continue
        d = sheet_date(row[0])
        position = str(row[1]).strip() if row[1] not in (None, "") else ""
        value = as_float(row[9])
        if not d or not position:
            continue
        keys.add((d, position))
        if value is not None and value > 0:
            series[position].append((d, value))
    for position in series:
        series[position].sort(key=lambda item: item[0])
    return keys, series


def baseline_for(series: list[tuple[date, float]], current_date: date) -> tuple[date, float] | None:
    target = current_date - timedelta(days=TARGET_LOOKBACK_DAYS)
    eligible = [item for item in series if item[0] <= target]
    return eligible[-1] if eligible else None


def signal_for(current_value: float, baseline: tuple[date, float] | None, manual_override: bool) -> tuple[float | None, str, str]:
    if baseline is None or baseline[1] <= 0:
        return None, "Ny", "Afventer mindst ca. 30 dages prishistorik."

    baseline_date, old_value = baseline
    pct = (current_value - old_value) / old_value
    abs_change = current_value - old_value

    if abs(abs_change) < MIN_ABS_CHANGE_DKK:
        signal = "Gul"
    elif pct >= GREEN_THRESHOLD:
        signal = "Grøn"
    elif pct <= RED_THRESHOLD:
        signal = "Rød"
    else:
        signal = "Gul"

    # Prefix with text so a leading + cannot be interpreted as a formula by Sheets.
    note = f"Ændring {pct:+.1%} / {abs_change:+.2f} DKK vs. reference {baseline_date.isoformat()}."
    if manual_override:
        note += " Markedssignal kun; manuel konservativ værdi er bevaret."
    return pct, signal, note


def main() -> int:
    credentials_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "").strip()
    spreadsheet_id = os.getenv("POKEMON_SHEET_ID", "").strip()
    if not credentials_json or not spreadsheet_id:
        print("[cardmarket-sheet-sync] Google Sheets secrets are not configured; nothing changed.")
        return 0

    credentials = service_account.Credentials.from_service_account_info(
        json.loads(credentials_json), scopes=[SCOPE]
    )
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    inventory = get_values(service, spreadsheet_id, INVENTORY_RANGE)
    if not inventory:
        raise RuntimeError("Inventory sheet is empty")
    headers = header_map(inventory[0])

    required = [
        "Type", "Cardmarket ID", "Navn", "Antal", "Variant", "EUR/DKK",
        "Manuel konservativ værdi DKK", "Position ID", "Game", "CM Trend EUR",
        "CM Low EUR", "CM Avg7 EUR", "CM Avg30 EUR", "CM senest opdateret",
        "CM snapshot", "CM ændring 30d %", "Signal", "Signalnote",
    ]
    missing = [name for name in required if name not in headers]
    if missing:
        raise RuntimeError("Missing Inventory columns: " + ", ".join(missing))

    history = get_values(service, spreadsheet_id, HISTORY_RANGE)
    history_keys, history_series = parse_history(history)

    # On the very first run preserve the pre-existing snapshot before overwriting it.
    if len(history) <= 1:
        seed_rows: list[list[Any]] = []
        for row in inventory[1:]:
            product_id = as_int(cell(row, headers["Cardmarket ID"]))
            position = str(cell(row, headers["Position ID"])).strip()
            item_type = str(cell(row, headers["Type"])).strip()
            snapshot_date = sheet_date(cell(row, headers["CM senest opdateret"]))
            trend = as_float(cell(row, headers["CM Trend EUR"]))
            low = as_float(cell(row, headers["CM Low EUR"]))
            avg7 = as_float(cell(row, headers["CM Avg7 EUR"]))
            avg30 = as_float(cell(row, headers["CM Avg30 EUR"]))
            fx = as_float(cell(row, headers["EUR/DKK"]))
            qty = as_float(cell(row, headers["Antal"])) or 1.0
            name = str(cell(row, headers["Navn"])).strip()
            if not product_id or not position or not snapshot_date or trend is None or fx is None or item_type == "Slab":
                continue
            market_value = qty * trend * fx
            seed_rows.append([
                date_formula(snapshot_date), position, product_id, name, trend,
                low if low is not None else "", avg7 if avg7 is not None else "",
                avg30 if avg30 is not None else "", fx, market_value,
            ])
            history_keys.add((snapshot_date, position))
            history_series[position].append((snapshot_date, market_value))
        append_history(service, spreadsheet_id, seed_rows)
        print(f"Seeded {len(seed_rows)} historical price snapshots from Inventory.")

    pokemon_date, pokemon_guide = fetch_guide(POKEMON_GUIDE_URL)
    lorcana_date, lorcana_guide = fetch_guide(LORCANA_GUIDE_URL)
    print(f"Downloaded Cardmarket guides: Pokemon {pokemon_date} ({len(pokemon_guide):,}), Lorcana {lorcana_date} ({len(lorcana_guide):,}).")

    market_updates: list[dict[str, Any]] = []
    new_history: list[list[Any]] = []
    current_refs: dict[str, tuple[date, float, bool, int]] = {}
    matched = 0
    absent = 0

    for sheet_row, row in enumerate(inventory[1:], start=2):
        product_id = as_int(cell(row, headers["Cardmarket ID"]))
        if not product_id:
            continue

        game = str(cell(row, headers["Game"])).strip()
        variant = str(cell(row, headers["Variant"])).strip()
        item_type = str(cell(row, headers["Type"])).strip()
        guide = lorcana_guide if game.lower() == "lorcana" else pokemon_guide
        guide_date = lorcana_date if game.lower() == "lorcana" else pokemon_date
        guide_item = guide.get(product_id)
        if not guide_item:
            absent += 1
            continue

        trend, low, avg7, avg30 = choose_prices(guide_item, game, variant)
        if trend is None:
            absent += 1
            continue

        matched += 1
        market_updates.extend([
            {"range": f"Inventory!N{sheet_row}:Q{sheet_row}", "values": [[trend, low if low is not None else "", avg7 if avg7 is not None else "", avg30 if avg30 is not None else ""]]},
            {"range": f"Inventory!W{sheet_row}", "values": [[date_formula(guide_date)]]},
            {"range": f"Inventory!AV{sheet_row}", "values": [[date_formula(guide_date)]]},
        ])

        position = str(cell(row, headers["Position ID"])).strip()
        fx = as_float(cell(row, headers["EUR/DKK"]))
        qty = as_float(cell(row, headers["Antal"])) or 1.0
        manual_override = as_float(cell(row, headers["Manuel konservativ værdi DKK"])) is not None
        if not position or fx is None or item_type == "Slab":
            continue

        market_value = qty * trend * fx
        current_refs[position] = (guide_date, market_value, manual_override, sheet_row)
        if (guide_date, position) not in history_keys:
            name = str(cell(row, headers["Navn"])).strip()
            new_history.append([
                date_formula(guide_date), position, product_id, name, trend,
                low if low is not None else "", avg7 if avg7 is not None else "",
                avg30 if avg30 is not None else "", fx, market_value,
            ])
            history_keys.add((guide_date, position))
            history_series[position].append((guide_date, market_value))
            history_series[position].sort(key=lambda item: item[0])

    batch_write(service, spreadsheet_id, market_updates)
    append_history(service, spreadsheet_id, new_history)

    signal_updates: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)
    for position, (current_date, current_value, manual_override, sheet_row) in current_refs.items():
        older = [item for item in history_series.get(position, []) if item[0] < current_date]
        baseline = baseline_for(older, current_date)
        pct, signal, note = signal_for(current_value, baseline, manual_override)
        counts[signal] += 1
        signal_updates.append({
            "range": f"Inventory!AW{sheet_row}:AY{sheet_row}",
            "values": [[pct if pct is not None else "", signal, note]],
        })

    batch_write(service, spreadsheet_id, signal_updates)
    print(f"Updated {matched} matched products; {absent} Cardmarket IDs absent. Appended {len(new_history)} price-history rows.")
    print("Signals:", dict(counts))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[cardmarket-sheet-sync] ERROR: {exc}", file=sys.stderr)
        raise
