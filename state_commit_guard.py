import argparse
import copy
import json
import subprocess
from pathlib import Path


MAIN_FILES = (
    "restock_state_v2.json",
    "local_stock_state_v1.json",
)

HOT_FILES = (
    "hot_restock_state.json",
    "salling_early_radar_state.json",
    "salling_victini_state.json",
)


def _read_json_text(text):
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("state root must be a JSON object")
    return value


def _serialize(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def _head_text(path):
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _same_except_keys(old_entry, new_entry, ignored_keys):
    old_cmp = copy.deepcopy(old_entry)
    new_cmp = copy.deepcopy(new_entry)
    for key in ignored_keys:
        old_cmp.pop(key, None)
        new_cmp.pop(key, None)
    return old_cmp == new_cmp


def compact_local_stock(old, new):
    compact = copy.deepcopy(new)
    old_products = old.get("products") or {}
    new_products = compact.get("products") or {}

    if isinstance(old_products, dict) and isinstance(new_products, dict):
        for product_key, new_product in new_products.items():
            old_product = old_products.get(product_key)
            if not isinstance(old_product, dict) or not isinstance(new_product, dict):
                continue
            if _same_except_keys(old_product, new_product, {"observed_at"}):
                if "observed_at" in old_product:
                    new_product["observed_at"] = old_product["observed_at"]
                else:
                    new_product.pop("observed_at", None)

    return compact


def compact_restock_state(old, new):
    compact = copy.deepcopy(new)
    old_health = old.get("_source_health") or {}
    new_health = compact.get("_source_health") or {}

    if isinstance(old_health, dict) and isinstance(new_health, dict):
        for source_key, new_entry in new_health.items():
            old_entry = old_health.get(source_key)
            if not isinstance(old_entry, dict) or not isinstance(new_entry, dict):
                continue
            ignored = {"last_attempt", "last_success"}
            if _same_except_keys(old_entry, new_entry, ignored):
                for key in ignored:
                    if key in old_entry:
                        new_entry[key] = old_entry[key]
                    else:
                        new_entry.pop(key, None)

    # _last_full_scan_epoch is deliberately kept from the current run. It is
    # the V44 recovery heartbeat and must remain fresh even when nothing else
    # changed, otherwise a healthy scanner would enter recovery mode after 30m.
    return compact


def compact_hot_state(old, new):
    compact = copy.deepcopy(new)
    old_controls = old.get("source_controls") or {}
    new_controls = compact.get("source_controls") or {}

    if isinstance(old_controls, dict) and isinstance(new_controls, dict):
        for source_key, new_entry in new_controls.items():
            old_entry = old_controls.get(source_key)
            if not isinstance(old_entry, dict) or not isinstance(new_entry, dict):
                continue
            if _same_except_keys(old_entry, new_entry, {"last_success_at"}):
                if "last_success_at" in old_entry:
                    new_entry["last_success_at"] = old_entry["last_success_at"]
                else:
                    new_entry.pop("last_success_at", None)

    old_cmp = copy.deepcopy(old)
    new_cmp = copy.deepcopy(compact)
    old_cmp.pop("updated_at", None)
    new_cmp.pop("updated_at", None)
    if old_cmp == new_cmp:
        if "updated_at" in old:
            compact["updated_at"] = old["updated_at"]
        else:
            compact.pop("updated_at", None)

    return compact


def compact_updated_at_only(old, new):
    compact = copy.deepcopy(new)
    old_cmp = copy.deepcopy(old)
    new_cmp = copy.deepcopy(compact)
    old_cmp.pop("updated_at", None)
    new_cmp.pop("updated_at", None)
    if old_cmp == new_cmp:
        if "updated_at" in old:
            compact["updated_at"] = old["updated_at"]
        else:
            compact.pop("updated_at", None)
    return compact


def compact_state(path, old, new):
    if path == "local_stock_state_v1.json":
        return compact_local_stock(old, new)
    if path == "restock_state_v2.json":
        return compact_restock_state(old, new)
    if path == "hot_restock_state.json":
        return compact_hot_state(old, new)
    if path in {"salling_early_radar_state.json", "salling_victini_state.json"}:
        return compact_updated_at_only(old, new)
    return new


def process_file(path):
    current_path = Path(path)
    if not current_path.exists():
        print(f"STATE GUARD: {path} mangler; springer over")
        return

    head_text = _head_text(path)
    if head_text is None:
        print(f"STATE GUARD: {path} findes ikke i HEAD; beholder ny fil")
        return

    current_text = current_path.read_text(encoding="utf-8")
    try:
        old = _read_json_text(head_text)
        new = _read_json_text(current_text)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"STATE GUARD: {path} kunne ikke normaliseres ({exc}); beholder current")
        return

    compact = compact_state(path, old, new)
    compact_text = _serialize(compact)
    if compact_text != current_text:
        current_path.write_text(compact_text, encoding="utf-8")
        print(f"STATE GUARD: {path} kompakteret")
    else:
        print(f"STATE GUARD: {path} ingen volatil støj at fjerne")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("main", "hot"), required=True)
    args = parser.parse_args()

    files = MAIN_FILES if args.profile == "main" else HOT_FILES
    for path in files:
        process_file(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
