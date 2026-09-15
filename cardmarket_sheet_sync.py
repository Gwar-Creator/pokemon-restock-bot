#!/usr/bin/env python3
"""Daily Cardmarket price-guide -> Google Sheets portfolio sync.

- Downloads Cardmarket's public daily price guides for Pokemon and Lorcana.
- Matches Inventory rows by Cardmarket ID.
- Updates raw market reference columns only (N:Q, W, AV).
- Never overwrites manual conservative value (S) or portfolio value (T).
- Appends one daily snapshot per position to Price History.
- Writes a 30-day red/yellow/green signal to AW:AY.

Required environment variables:
  GOOGLE_SHEETS_CREDENTIALS  Full service-account JSON
  POKEMON_SHEET_ID           Google Sheets spreadsheet ID
"""

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

POKEMON_GUIDE_URL = (
    "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"
)
LORCANA_GUIDE_URL = (
    "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_19.json"
)
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
INVENTORY_RANGE = "Inventory!A1:AY2000"
HISTORY_RANGE = "'Price History'!A:J"

GREEN_THRESHOLD = 0.10
RED_THRESHOLD = -0.10
MIN_ABS_CHANGE_DKK = 5.0
MIN_BASELINE_AGE_DAYS = 20
TARGET_LOOKBACK_DAYS = 30


def die_or_skip(message: str) -> int:
    print(f"[cardmarket-sheet-sync] {message}")
    return 0


def fetch_guide(url: str) -> tuple[date, dict[int, dict[str, Any]]]:
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    payload = response.json()
    created = datetime.strptime(payload["createdAt"], "%Y-%m-%dT%H:%M:%S%z").date()
    guide = {int(item["idProduct"]): item for item in payload.get("priceGuides", [])}
    if not guide:
        raise RuntimeError(f"No priceGuides returned from {url}")
    return created, guide


def header_map(header: list[Any]) -> dict[str, int]:
    return {str(value): idx for idx, value in enumerate(header) if value not in (None, "")}


def cell(row: list[Any], idx: int | None, default: Any = "") -> Any:
    if idx is None or idx >= len(row):
        return default
    value = row[idx]
    return default if value is None else value


def as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sheet_serial_to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text.split()[0], fmt).date()
        except ValueError:
            continue
    return None


def choose_prices(
    guide_row: dict[str, Any], game: str, variant: str
) -> tuple[float | None, float | None, float | None, float | None]:
    """Return trend, low, avg7 and avg30 for the inventory variant."""
    variant_norm = (variant or "").strip().lower()
    game_norm = (game or "").strip().lower()

    if game_norm in ("pokémon", "pokemon"):
        explicit_holo = ("reverse holo" in variant_norm) or (
            "holo" in variant_norm
            and not any(
                token in variant_norm
                for token in ("full art", "illustration", "sir", "special illustration")
            )
        )
        if explicit_holo and guide_row.get("trend-holo") not in (None, 0, 0.0):
            return (
                as_float(guide_row.get("trend-holo")),
                as_float(guide_row.get("low-holo")),
                as_float(guide_row.get("avg7-holo")),
                as_float(guide_row.get("avg30-holo")),
            )
    elif game_norm == "lorcana":
        if "foil" in variant_norm and guide_row.get("trend-foil") not in (None, 0, 0.0):
            return (
                as_float(guide_row.get("trend-foil")),
                as_float(guide_row.get("low-foil")),
                as_float(guide_row.get("avg7-foil")),
                as_float(guide_row.get("avg30-foil")),
            )

    return (
        as_float(guide_row.get("trend")),
        as_float(guide_row.get("low")),
        as_float(guide_row.get("avg7")),
        as_float(guide_row.get("avg30")),
    )


def date_formula(d: date) -> str:
    return f"=DATE({d.year};{d.month};{d.day})"


def parse_history(
    values: list[list[Any]],
) -> tuple[set[tuple[date, str]], dict[str, list[tuple[date, float]]]]:
    keys: set[tuple[date, str]] = set()
    by_position: dict[str, list[tuple[date, float]]] = defaultdict(list)
    if not values:
        return keys, by_position
    for row in values[1:]:
        if len(row) < 10:
            continue
        d = sheet_serial_to_date(row[0])
        position = str(row[1]).strip() if row[1] not in (None, "") else ""
        market_value = as_float(row[9])
        if not d or not position:
            continue
        keys.add((d, position))
        if market_value is not None and market_value > 0:
            by_position[position].append((d, market_value))
    for position in by_position:
        by_position[position].sort(key=lambda item: item[0])
    return keys, by_position


def pick_baseline(
    series: list[tuple[date, float]], current_date: date
) -> tuple[date, float] | None:
    target = current_date - timedelta(days=TARGET_LOOKBACK_DAYS)
    eligible = [item for item in series if item[0] <= target]
    if not eligible:
        return None
    baseline = eligible[-1]
    if (current_date - baseline[0]).days < MIN_BASELINE_AGE_DAYS:
        return None
    return baseline


def signal_for(
    current_value: float | None,
    baseline: tuple[date, float] | None,
    manual_override: bool,
) -> tuple[float | None, str, str]:
    if current_value is None or current_value <= 0 or baseline is None or baseline[1] <= 0:
        return None, "Ny", "Afventer mindst ca. 30 dages prishistorik."

    baseline_date, baseline_value = baseline
    pct = (current_value - baseline_value) / baseline_value
    abs_change = current_value - baseline_value

    if abs(abs_change) < MIN_ABS_CHANGE_DKK:
        signal = "Gul"
    elif pct >= GREEN_THRESHOLD:
        signal = "Grøn"
    elif pct <= RED_THRESHOLD:
        signal = "Rød"
    else:
        signal = "Gul"

    note = f"{pct:+.1%} / {abs_change:+.2f} DKK vs. reference {baseline_date.isoformat()}."
    if manual_override:
        note += " Markedssignal kun; manuel konservativ værdi er bevaret."
    return pct, signal, note


def values_get(service: Any, spreadsheet_id: str, range_name: str) -> list[list[Any]]:
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


def values_batch_update(
    service: Any, spreadsheet_id: str, data: list[dict[str, Any]]
) -> None:
    if not data:
        return
    for start in range(0, len(data), 400):
        chunk = data[start : start + 400]
        (
            service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": chunk},
            )
            .execute()
        )


def values_append(service: Any, spreadsheet_id: str, rows: list[list[Any]]) -> None:
    if not rows:
        return
    (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range="'Price History'!A:J",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        )
        .execute()
    )


def main() -> int:
    credentials_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "").strip()
    spreadsheet_id = os.getenv("POKEMON_SHEET_ID", "").strip()
    if not credentials_json or not spreadsheet_id:
        return die_or_skip(
            "Google Sheets secrets are not configured yet; nothing changed. "
            "Set GOOGLE_SHEETS_CREDENTIALS and POKEMON_SHEET_ID to activate the daily sync."
        )

    try:
        info = json.loads(credentials_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS is not valid JSON") from exc

    creds = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    inventory = values_get(service, spreadsheet_id, INVENTORY_RANGE)
    if not inventory:
        raise RuntimeError("Inventory sheet is empty")
    headers = header_map(inventory[0])

    required = [
        "Type",
        "Cardmarket ID",
        "Navn",
        "Antal",
        "Variant",
        "EUR/DKK",
        "Manuel konservativ værdi DKK",
        "Position ID",
        "Game",
        "CM Trend EUR",
        "CM Low EUR",
        "CM Avg7 EUR",
        "CM Avg30 EUR",
        "CM senest opdateret",
        "CM snapshot",
        "CM ændring 30d %",
        "Signal",
        "Signalnote",
    ]
    missing_headers = [name for name in required if name not in headers]
    if missing_headers:
        raise RuntimeError(f"Inventory is missing expected columns: {', '.join(missing_headers)}")

    history = values_get(service, spreadsheet_id, HISTORY_RANGE)
    history_keys, history_by_position = parse_history(history)

    # Seed the old stored snapshot before today's values overwrite Inventory.
    seed_rows: list[list[Any]] = []
    if len(history) <= 1:
        for sheet_row, row in enumerate(inventory[1:], start=2):
            product_id = as_int(cell(row, headers["Cardmarket ID"]))
            position = str(cell(row, headers["Position ID"])).strip()
            item_type = str(cell(row, headers["Type"])).strip()
            snapshot_date = sheet_serial_to_date(cell(row, headers["CM senest opdateret"]))
            trend = as_float(cell(row, headers["CM Trend EUR"]))
            low = as_float(cell(row, headers["CM Low EUR"]))
            avg7 = as_float(cell(row, headers["CM Avg7 EUR"]))
            avg30 = as_float(cell(row, headers["CM Avg30 EUR"]))
            fx = as_float(cell(row, headers["EUR/DKK"]))
            qty = as_float(cell(row, headers["Antal"])) or 1.0
            name = str(cell(row, headers["Navn"])).strip()
            if not product_id or not position or not snapshot_date or trend is None or fx is None:
                continue
            if item_type == "Slab":
                continue
            market_value = qty * trend * fx
            seed_rows.append(
                [
                    date_formula(snapshot_date),
                    position,
                    product_id,
                    name,
                    trend,
                    low if low is not None else "",
                    avg7 if avg7 is not None else "",
                    avg30 if avg30 is not None else "",
                    fx,
                    market_value,
                ]
            )
            history_keys.add((snapshot_date, position))
            history_by_position[position].append((snapshot_date, market_value))
        for position in history_by_position:
            history_by_position[position].sort(key=lambda item: item[0])
        if seed_rows:
            values_append(service, spreadsheet_id, seed_rows)
            print(f"Seeded {len(seed_rows)} historical price snapshots from Inventory.")

    pokemon_date, pokemon_guide = fetch_guide(POKEMON_GUIDE_URL)
    lorcana_date, lorcana_guide = fetch_guide(LORCANA_GUIDE_URL)
    print(
        f"Downloaded Cardmarket guides: Pokemon {pokemon_date.isoformat()} "
        f"({len(pokemon_guide):,}), Lorcana {lorcana_date.isoformat()} ({len(lorcana_guide):,})."
    )

    updates: list[dict[str, Any]] = []
    append_rows: list[list[Any]] = []
    current_refs: dict[str, tuple[date, float, bool, int]] = {}
    matched = 0
    missing = 0

    for sheet_row, row in enumerate(inventory[1:], start=2):
        product_id = as_int(cell(row, headers["Cardmarket ID"]))
        if not product_id:
            continue
        game = str(cell(row, headers["Game"])).strip()
        variant = str(cell(row, headers["Variant"])).strip()
        item_type = str(cell(row, headers["Type"])).strip()
        guide = lorcana_guide if game.lower() == "lorcana" else pokemon_guide
        guide_date = lorcana_date if game.lower() == "lorcana" else pokemon_date
        guide_row = guide.get(product_id)
        if not guide_row:
            missing += 1
            continue

        trend, low, avg7, avg30 = choose_prices(guide_row, game, variant)
        if trend is None:
            missing += 1
            continue

        matched += 1
        updates.append(
            {
                "range": f"Inventory!N{sheet_row}:Q{sheet_row}",
                "values": [
                    [
                        trend,
                        low if low is not None else "",
                        avg7 if avg7 is not None else "",
                        avg30 if avg30 is not None else "",
                    ]
                ],
            }
        )
        updates.append({"range": f"Inventory!W{sheet_row}", "values": [[date_formula(guide_date)]]})
        updates.append({"range": f"Inventory!AV{sheet_row}", "values": [[date_formula(guide_date)]]})

        position = str(cell(row, headers["Position ID"])).strip()
        name = str(cell(row, headers["Navn"])).strip()
        fx = as_float(cell(row, headers["EUR/DKK"]))
        qty = as_float(cell(row, headers["Antal"])) or 1.0
        manual_override = as_float(cell(row, headers["Manuel konservativ værdi DKK"])) is not None
        if not position or fx is None or item_type == "Slab":
            continue

        market_value = qty * trend * fx
        current_refs[position] = (guide_date, market_value, manual_override, sheet_row)
        key = (guide_date, position)
        if key not in history_keys:
            append_rows.append(
                [
                    date_formula(guide_date),
                    position,
                    product_id,
                    name,
                    trend,
                    low if low is not None else "",
                    avg7 if avg7 is not None else "",
                    avg30 if avg30 is not None else "",
                    fx,
                    market_value,
                ]
            )
            history_keys.add(key)
            history_by_position[position].append((guide_date, market_value))
            history_by_position[position].sort(key=lambda item: item[0])

    values_batch_update(service, spreadsheet_id, updates)
    values_append(service, spreadsheet_id, append_rows)

    signal_updates: list[dict[str, Any]] = []
    signal_counts = defaultdict(int)
    for position, (current_date, current_value, manual_override, sheet_row) in current_refs.items():
        series = history_by_position.get(position, [])
        older_series = [item for item in series if item[0] < current_date]
        baseline = pick_baseline(older_series, current_date)
        pct, signal, note = signal_for(current_value, baseline, manual_override)
        signal_counts[signal] += 1
        signal_updates.append(
            {
                "range": f"Inventory!AW{sheet_row}:AY{sheet_row}",
                "values": [[pct if pct is not None else "", signal, note]],
            }
        )

    values_batch_update(service, spreadsheet_id, signal_updates)

    print(
        f"Updated {matched} matched products; {missing} Cardmarket IDs were absent from today's guide. "
        f"Appended {len(append_rows)} new price-history rows."
    )
    print("Signals:", dict(signal_counts))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[cardmarket-sheet-sync] ERROR: {exc}", file=sys.stderr)
        raise
