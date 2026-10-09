"""Read-only Cardmarket portfolio sync preflight. Does not change the sheet."""
import json
import os
from collections import Counter

SHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "15ihyr9IxxBGgQsetbMCE0DCCVzYGZXwp-X9tdwlkpwM")


def main():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not raw:
        raise RuntimeError("No service account JSON configured in this workflow")
    credentials = Credentials.from_service_account_info(
        json.loads(raw), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False).spreadsheets()
    response = service.values().get(
        spreadsheetId=SHEET_ID, range="'Inventory v2'!A1:V2500",
        valueRenderOption="FORMULA").execute()
    rows = response.get("values", [])
    if not rows:
        raise RuntimeError("Inventory v2 returned no rows")
    counts = Counter()
    for row in rows[1:]:
        if len(row) < 4 or row[0] not in ("Active", "Incoming") or not row[3]:
            continue
        counts["active_or_incoming"] += 1
        if len(row) > 2 and str(row[2]).strip():
            counts["has_cm_id"] += 1
        else:
            counts["missing_cm_id"] += 1
    print(json.dumps({"sheet_access": "OK", "read_only": True, "counts": counts}))
    print("No cells were changed.")


if __name__ == "__main__":
    main()
