"""Sync Cardmarket Pokémon price guide to Inventory v2.

Dry run by default. Only Q:T (market data) and V (snapshot) are written.
L/M conservative valuation formulas/manual prices are never changed here.
"""
import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime

import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "15ihyr9IxxBGgQsetbMCE0DCCVzYGZXwp-X9tdwlkpwM")
DEFAULT_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def load_guide():
    path = os.getenv("CARDMARKET_PRICE_GUIDE_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            guide = json.load(f)
    else:
        url = os.getenv("CARDMARKET_PRICE_GUIDE_URL", DEFAULT_URL)
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        guide = response.json()
    if not isinstance(guide.get("priceGuides"), list) or not guide.get("createdAt"):
        raise ValueError("Unexpected Cardmarket price guide structure")
    created = guide["createdAt"][:10]
    snapshot = datetime.strptime(created, "%Y-%m-%d").strftime("%d/%m/%Y")
    return snapshot, {str(p["idProduct"]): p for p in guide["priceGuides"]}


def sheet_api():
    secret = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "")
    if not secret:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS secret is missing")
    creds = Credentials.from_service_account_info(json.loads(secret), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Write matched prices; default is dry run")
    args = parser.parse_args()
    snapshot, guide = load_guide()
    api = sheet_api()
    result = api.values().get(
        spreadsheetId=SHEET_ID, range="'Inventory v2'!A1:AC2500",
        valueRenderOption="FORMULA").execute()
    rows = result.get("values", [])
    if not rows:
        raise RuntimeError("Inventory v2 empty")
    expected = {2: "Cardmarket ID", 16: "CM Trend EUR", 17: "CM Low EUR",
                18: "CM Avg7 EUR", 19: "CM Avg30 EUR", 21: "CM snapshot"}
    for index, title in expected.items():
        if len(rows[0]) <= index or rows[0][index] != title:
            raise RuntimeError(f"Unexpected column {index + 1}: expected {title!r}")
    id_numbers = defaultdict(set)
    for row in rows[1:]:
        if len(row) > 6 and row[0] in ("Active", "Incoming"):
            pid = str(row[2]).strip()
            if pid:
                id_numbers[pid].add(str(row[5]).split("/")[0].strip())
    conflicting_ids = {pid for pid, numbers in id_numbers.items() if len(numbers) > 1}

    changes = []
    counts = Counter()
    for number, row in enumerate(rows[1:], 2):
        if len(row) < 4 or not row[3] or row[0] not in ("Active", "Incoming"):
            continue
        counts["active"] += 1
        pid = str(row[2]).strip() if len(row) > 2 else ""
        if not pid:
            counts["missing_id"] += 1
            continue
        if pid in conflicting_ids:
            counts["conflicting_id"] += 1
            print("CONFLICTING_ID", number, pid, row[3])
            continue
        price = guide.get(pid)
        if not price:
            counts["not_in_guide"] += 1
            print("NOT_IN_GUIDE", number, pid, row[3])
            continue
        variant = str(row[6]).lower() if len(row) > 6 else ""
        if "ikke verificeret" in variant or "unknown" in variant:
            counts["unverified_variant"] += 1
            continue
        protected = ("stamp", "snowflake", "cracked ice", "cosmos",
                     "1st edition", "4th print", "calendar", "exclusive")
        if any(marker in variant for marker in protected):
            counts["special_variant_skipped"] += 1
            continue
        keys = ("trend", "low", "avg7", "avg30")
        if "reverse holo" in variant:
            keys = ("trend-holo", "low-holo", "avg7-holo", "avg30-holo")
            counts["reverse_foil"] += 1
        values = [price.get(k) for k in keys]
        if any(not isinstance(x, (int, float)) or x <= 0 for x in values):
            counts["incomplete_price"] += 1
            continue
        trend, low, avg7, avg30 = values
        if (max(avg7, avg30) / min(avg7, avg30) > 8 or
                trend / max(avg7, avg30) > 8 or
                min(avg7, avg30) / trend > 8):
            counts["price_anomaly_skipped"] += 1
            print("PRICE_ANOMALY", number, pid, row[3], values)
            continue
        counts["matched"] += 1
        existing = row[16:20] if len(row) >= 20 else []
        previous_date = row[21] if len(row) > 21 else ""
        if [str(x) for x in existing] == [str(x) for x in values] and previous_date == snapshot:
            counts["unchanged"] += 1
            continue
        changes.append({"range": f"'Inventory v2'!Q{number}:T{number}", "values": [values]})
        changes.append({"range": f"'Inventory v2'!V{number}", "values": [[snapshot]]})
        counts["changed"] += 1
    print(json.dumps({"snapshot": snapshot, "write": args.write, "counts": dict(counts)},
                     ensure_ascii=False))
    if not args.write:
        print("DRY RUN - no cells changed")
        return
    if counts["matched"] < 1000:
        raise RuntimeError("Safety stop: fewer than 1000 matches; refusing to write")
    for start in range(0, len(changes), 200):
        api.values().batchUpdate(spreadsheetId=SHEET_ID, body={
            "valueInputOption": "RAW", "data": changes[start:start + 200]
        }).execute()
    print(f"SUCCESS: updated {counts['changed']} rows. Valuation columns untouched.")


if __name__ == "__main__":
    main()
