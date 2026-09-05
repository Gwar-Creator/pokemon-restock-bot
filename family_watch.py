from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

API_URL = "https://madpris.gratis.dk/api/products"
CONFIG_PATH = Path(os.getenv("FAMILY_WATCH_CONFIG", "family_watchlist.json"))
STATE_PATH = Path(os.getenv("FAMILY_WATCH_STATE", "family_watch_state.json"))
WEBHOOK_URL = os.getenv("FAMILY_WATCH_WEBHOOK_URL", "").strip()
DRY_RUN = os.getenv("FAMILY_WATCH_DRY_RUN", "1").strip().lower() in {"1", "true", "yes", "on"}
TIMEOUT_SECONDS = 20
USER_AGENT = "family-watch/0.1 (+github.com/Gwar-Creator/pokemon-restock-bot)"
STATE_RETENTION_DAYS = 45

DANISH_TRANSLATION = str.maketrans({"æ": "ae", "ø": "o", "å": "a", "Æ": "ae", "Ø": "o", "Å": "a"})

STORE_ALIASES = {
    "rema": "rema1000",
    "rema1000": "rema1000",
    "daglibrugsen": "daglibrugsen",
    "daglibrugsen": "daglibrugsen",
    "365": "365discount",
    "coop365": "365discount",
    "365discount": "365discount",
    "discount365": "365discount",
    "superbrugsen": "superbrugsen",
    "lovbjerg": "lovbjerg",
}


@dataclass(frozen=True)
class Offer:
    group_id: str
    group_label: str
    store: str
    name: str
    brand: str
    price: float | None
    unit_price: float | None
    unit: str
    unit_size: Any
    product_id: str
    ean: str
    url: str

    @property
    def key(self) -> str:
        price_token = "" if self.price is None else f"{self.price:.2f}"
        identity = self.product_id or self.ean or normalize_text(self.name)
        return "|".join([self.group_id, self.store, identity, price_token])


def normalize_text(value: Any) -> str:
    text = str(value or "").translate(DANISH_TRANSLATION).lower()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return " ".join(text.split())


def canonical_store(value: Any) -> str:
    compact = re.sub(r"[^a-z0-9]", "", normalize_text(value))
    return STORE_ALIASES.get(compact, compact)


def combined_product_text(product: dict[str, Any]) -> str:
    return normalize_text(" ".join(str(product.get(k) or "") for k in ("name", "brand", "category", "subcategory")))


def store_is_allowed(product: dict[str, Any], config: dict[str, Any]) -> bool:
    allowed = {canonical_store(store) for store in config.get("allowed_stores", []) if store}
    if not allowed:
        return True
    return canonical_store(product.get("store")) in allowed


def matches_group(product: dict[str, Any], group: dict[str, Any]) -> bool:
    text = combined_product_text(product)
    include_all = [normalize_text(x) for x in group.get("include_all", []) if x]
    include_any = [normalize_text(x) for x in group.get("include_any", []) if x]
    exclude_any = [normalize_text(x) for x in group.get("exclude_any", []) if x]

    if include_all and not all(token in text for token in include_all):
        return False
    if include_any and not any(token in text for token in include_any):
        return False
    if exclude_any and any(token in text for token in exclude_any):
        return False
    return True


def parse_offer(product: dict[str, Any], group: dict[str, Any]) -> Offer:
    def maybe_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return Offer(
        group_id=str(group["id"]),
        group_label=str(group["label"]),
        store=str(product.get("store") or "Ukendt butik"),
        name=str(product.get("name") or "Ukendt vare"),
        brand=str(product.get("brand") or ""),
        price=maybe_float(product.get("price")),
        unit_price=maybe_float(product.get("unit_price")),
        unit=str(product.get("unit") or ""),
        unit_size=product.get("unit_size"),
        product_id=str(product.get("id") or ""),
        ean=str(product.get("ean") or ""),
        url=str(product.get("url") or ""),
    )


def fetch_products(query: str, session: requests.Session) -> list[dict[str, Any]]:
    params = {
        "q": query,
        "on_sale": "1",
        "sort": "price",
        "order": "asc",
        "page": 1,
    }
    response = session.get(API_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    products = payload.get("products", [])
    if not isinstance(products, list):
        raise ValueError("Madpris response did not contain a products list")
    return [p for p in products if isinstance(p, dict)]


def collect_offers(config: dict[str, Any], session: requests.Session) -> tuple[list[Offer], list[str]]:
    offers: dict[str, Offer] = {}
    errors: list[str] = []

    for group in config.get("watch_groups", []):
        group_products: dict[str, dict[str, Any]] = {}
        for query in group.get("queries", []):
            try:
                products = fetch_products(str(query), session)
            except Exception as exc:
                errors.append(f"{group.get('id', '?')} / {query}: {type(exc).__name__}: {exc}")
                continue

            for product in products:
                if product.get("on_sale") is False or not store_is_allowed(product, config):
                    continue
                pid = str(product.get("id") or "")
                fallback = "|".join([
                    str(product.get("store") or ""),
                    normalize_text(product.get("name")),
                    str(product.get("price") or ""),
                ])
                group_products[pid or fallback] = product

        for product in group_products.values():
            if not matches_group(product, group):
                continue
            offer = parse_offer(product, group)
            offers[offer.key] = offer

    return sorted(offers.values(), key=lambda o: (o.group_label, o.price if o.price is not None else 10**9, o.store, o.name)), errors


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not config.get("watch_groups"):
        raise ValueError("family_watchlist.json has no watch_groups")
    return config


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"seen": {}, "last_run_at": None}
    try:
        with STATE_PATH.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            raise ValueError("state must be an object")
        state.setdefault("seen", {})
        return state
    except Exception:
        return {"seen": {}, "last_run_at": None}


def prune_seen(seen: dict[str, str]) -> dict[str, str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=STATE_RETENTION_DAYS)
    kept: dict[str, str] = {}
    for key, value in seen.items():
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed >= cutoff:
            kept[key] = value
    return kept


def format_price(value: float | None) -> str:
    if value is None:
        return "pris ukendt"
    if value.is_integer():
        return f"{int(value)} kr."
    return f"{value:.2f}".replace(".", ",") + " kr."


def offer_line(offer: Offer) -> str:
    brand = f"{offer.brand} " if offer.brand and normalize_text(offer.brand) not in normalize_text(offer.name) else ""
    return f"• {offer.store}: {brand}{offer.name} — **{format_price(offer.price)}**"


def build_messages(offers: list[Offer]) -> list[str]:
    grouped: dict[str, list[Offer]] = {}
    for offer in offers:
        grouped.setdefault(offer.group_label, []).append(offer)

    messages: list[str] = []
    for label, group_offers in grouped.items():
        lines = [f"👶 **FAMILY WATCH — {label}**"]
        for offer in group_offers[:10]:
            lines.append(offer_line(offer))
        if len(group_offers) > 10:
            lines.append(f"… og {len(group_offers) - 10} flere match")
        messages.append("\n".join(lines))
    return messages


def send_discord(message: str, session: requests.Session) -> None:
    response = session.post(WEBHOOK_URL, json={"content": message}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()


def main() -> int:
    config = load_config()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    offers, errors = collect_offers(config, session)
    print(f"Family Watch: {len(offers)} matching offers across {len(config['watch_groups'])} watch groups")
    for message in build_messages(offers):
        print("\n" + message)

    if errors:
        print("\nSource warnings:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)

    if DRY_RUN:
        print("\nDRY RUN: no Discord messages sent and no state written.")
        return 0 if offers or not errors else 2

    if not WEBHOOK_URL:
        print("FAMILY_WATCH_WEBHOOK_URL is required when FAMILY_WATCH_DRY_RUN=0", file=sys.stderr)
        return 2

    state = load_state()
    seen = prune_seen(state.get("seen", {}))
    new_offers = [offer for offer in offers if offer.key not in seen]

    for message in build_messages(new_offers):
        send_discord(message, session)
        time.sleep(0.25)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for offer in offers:
        seen[offer.key] = now
    state = {
        "seen": seen,
        "last_run_at": now,
        "last_match_count": len(offers),
        "last_new_count": len(new_offers),
    }
    with STATE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    print(f"Production mode: sent {len(new_offers)} new offer alerts; state saved to {STATE_PATH}")
    return 0 if offers or not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
