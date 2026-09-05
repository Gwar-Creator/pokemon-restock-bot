from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

CONFIG_PATH = Path(os.getenv("FAMILY_WATCH_CONFIG", "family_watchlist.json"))
STATE_PATH = Path(os.getenv("FAMILY_WATCH_STATE", "family_watch_state.json"))
WEBHOOK_URL = os.getenv("FAMILY_WATCH_WEBHOOK_URL", "").strip()
DRY_RUN = os.getenv("FAMILY_WATCH_DRY_RUN", "1").strip().lower() in {"1", "true", "yes", "on"}
TIMEOUT_SECONDS = 25
USER_AGENT = "Mozilla/5.0 (compatible; FamilyWatch/0.2; +https://github.com/Gwar-Creator/pokemon-restock-bot)"
STATE_RETENTION_DAYS = 45
COPENHAGEN = ZoneInfo("Europe/Copenhagen")
ETILBUDSAVIS_SEARCH_URL = "https://etilbudsavis.dk/soeg/{query}"
LOVBJERG_VEJEN_URL = "https://www.lovbjerg.dk/avis/denne-uges-avis/vejen"
TJEK_CATALOGS_URL = "https://squid-api.tjek.com/v2/catalogs"
TJEK_INCITO_URL = "https://squid-api.tjek.com/v4/rpc/generate_incito_from_publication"
TJEK_SECTION_URL = "https://squid-api.tjek.com/v4/rpc/generate_incito_from_publication_section"

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
    source: str
    group_id: str
    group_label: str
    store: str
    name: str
    description: str
    price: float | None
    valid_from: datetime
    valid_until: datetime
    offer_id: str
    publication_id: str
    publication_label: str
    url: str
    image: str = ""

    @property
    def key(self) -> str:
        if self.offer_id:
            return "|".join([self.source, self.publication_id or "-", self.offer_id])
        return "|".join(
            [
                self.source,
                canonical_store(self.store),
                normalize_text(self.name),
                self.valid_from.isoformat(),
                self.valid_until.isoformat(),
            ]
        )

    @property
    def fingerprint(self) -> str:
        price = "" if self.price is None else f"{self.price:.2f}"
        return "|".join(
            [
                canonical_store(self.store),
                normalize_text(self.name),
                price,
                self.valid_from.isoformat(),
                self.valid_until.isoformat(),
                self.group_id,
            ]
        )


def normalize_text(value: Any) -> str:
    text = str(value or "").translate(DANISH_TRANSLATION).lower()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return " ".join(text.split())


def canonical_store(value: Any) -> str:
    compact = re.sub(r"[^a-z0-9]", "", normalize_text(value))
    return STORE_ALIASES.get(compact, compact)


def combined_product_text(product: dict[str, Any]) -> str:
    return normalize_text(
        " ".join(
            str(product.get(k) or "")
            for k in ("name", "description", "brand", "category", "subcategory")
        )
    )


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


def parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    match = re.search(r"([+-]\d{2})(\d{2})$", text)
    if match and ":" not in text[-6:]:
        text = text[: match.start()] + f"{match.group(1)}:{match.group(2)}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def offer_phase(offer: Offer, now: datetime | None = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if now < offer.valid_from:
        return "upcoming"
    if now <= offer.valid_until:
        return "current"
    return "expired"


def format_date(value: datetime) -> str:
    local = value.astimezone(COPENHAGEN)
    return f"{local.day}/{local.month}"


def format_period(offer: Offer) -> str:
    return f"{format_date(offer.valid_from)}–{format_date(offer.valid_until)}"


def format_price(value: float | None) -> str:
    if value is None:
        return "pris ukendt"
    if float(value).is_integer():
        return f"{int(value)} kr."
    return f"{value:.2f}".replace(".", ",") + " kr."


def _iter_jsonld_offers(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(t).lower() == "offer" for t in types if t):
            yield node
        for value in node.values():
            yield from _iter_jsonld_offers(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_jsonld_offers(value)


def extract_etilbudsavis_offer_dicts(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for offer in _iter_jsonld_offers(payload):
            marker = json.dumps(offer, ensure_ascii=False, sort_keys=True)
            if marker not in seen:
                seen.add(marker)
                found.append(offer)
    return found


def _image_url(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return _image_url(value[0])
    if isinstance(value, dict):
        return str(value.get("url") or value.get("contentUrl") or "")
    return ""


def parse_etilbudsavis_offer(raw: dict[str, Any], group: dict[str, Any]) -> Offer | None:
    seller = raw.get("seller") or {}
    store = seller.get("name") if isinstance(seller, dict) else seller
    store = str(store or "")
    name = str(raw.get("name") or "").strip()
    description = str(raw.get("description") or "").strip()
    valid_from = parse_timestamp(raw.get("validFrom") or raw.get("availabilityStarts"))
    valid_until = parse_timestamp(
        raw.get("validThrough") or raw.get("priceValidUntil") or raw.get("availabilityEnds")
    )
    if not store or not name or not valid_from or not valid_until:
        return None

    price = maybe_float(raw.get("price"))
    if price is None and isinstance(raw.get("priceSpecification"), dict):
        price = maybe_float(raw["priceSpecification"].get("price"))

    url = str(raw.get("url") or "")
    params = parse_qs(urlparse(url).query)
    publication_id = str((params.get("publication") or [""])[0])
    offer_id = str((params.get("offer") or [""])[0])
    if not offer_id:
        offer_id = str(raw.get("sku") or raw.get("@id") or "")

    return Offer(
        source="etilbudsavis",
        group_id=str(group["id"]),
        group_label=str(group["label"]),
        store=store,
        name=name,
        description=description,
        price=price,
        valid_from=valid_from,
        valid_until=valid_until,
        offer_id=offer_id,
        publication_id=publication_id,
        publication_label="",
        url=url,
        image=_image_url(raw.get("image")),
    )


def collect_etilbudsavis_offers(
    config: dict[str, Any], session: requests.Session
) -> tuple[list[Offer], list[str]]:
    query_cache: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    offers: dict[str, Offer] = {}

    for group in config.get("watch_groups", []):
        for query in group.get("queries", []):
            query = str(query).strip()
            if not query:
                continue
            if query not in query_cache:
                url = ETILBUDSAVIS_SEARCH_URL.format(query=quote(query, safe=""))
                try:
                    response = session.get(url, timeout=TIMEOUT_SECONDS)
                    response.raise_for_status()
                    query_cache[query] = extract_etilbudsavis_offer_dicts(response.text)
                except Exception as exc:
                    errors.append(f"eTilbudsavis / {query}: {type(exc).__name__}: {exc}")
                    query_cache[query] = []

            for raw in query_cache[query]:
                seller = raw.get("seller") or {}
                store = seller.get("name") if isinstance(seller, dict) else seller
                product = {
                    "store": store,
                    "name": raw.get("name"),
                    "description": raw.get("description"),
                }
                if not store_is_allowed(product, config) or not matches_group(product, group):
                    continue
                offer = parse_etilbudsavis_offer(raw, group)
                if offer and offer_phase(offer) != "expired":
                    offers[offer.key] = offer

    return list(offers.values()), errors


def _descendant_texts(node: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(node, dict):
        if node.get("view_name") == "TextView" and node.get("text"):
            texts.append(str(node["text"]).strip())
        for value in node.values():
            texts.extend(_descendant_texts(value))
    elif isinstance(node, list):
        for value in node:
            texts.extend(_descendant_texts(value))
    return texts


def parse_lovbjerg_offer_node(
    node: dict[str, Any], publication: dict[str, Any], group: dict[str, Any]
) -> Offer | None:
    label = str(node.get("accessibility_label") or "").strip()
    match = re.match(r"^(.*?),\s*DKK\s*([0-9]+(?:[.,][0-9]+)?)\s*$", label, re.I)
    if not match:
        return None
    name = match.group(1).strip()
    price = maybe_float(match.group(2))
    texts = [text for text in _descendant_texts(node) if text and text != name]
    description = " | ".join(dict.fromkeys(texts))
    valid_from = parse_timestamp(publication.get("run_from"))
    valid_until = parse_timestamp(publication.get("run_till"))
    if not valid_from or not valid_until:
        return None

    image = ""
    stack: list[Any] = [node]
    while stack and not image:
        current = stack.pop()
        if isinstance(current, dict):
            if current.get("background_image"):
                image = str(current["background_image"])
                break
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)

    return Offer(
        source="lovbjerg_direct",
        group_id=str(group["id"]),
        group_label=str(group["label"]),
        store="Løvbjerg",
        name=name,
        description=description,
        price=price,
        valid_from=valid_from,
        valid_until=valid_until,
        offer_id=str(node.get("id") or ""),
        publication_id=str(publication.get("id") or ""),
        publication_label=str(publication.get("label") or "Løvbjerg Vejen"),
        url=LOVBJERG_VEJEN_URL,
        image=image,
    )


def _find_offer_nodes(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("role") == "offer" and node.get("accessibility_label"):
            found.append(node)
        for value in node.values():
            found.extend(_find_offer_nodes(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_find_offer_nodes(value))
    return found


def _find_section_bodies(node: Any) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if (
            node.get("view_name") == "IncitoEmbedView"
            and str(node.get("src") or "").endswith("generate_incito_from_publication_section")
            and node.get("body")
        ):
            try:
                body = json.loads(str(node["body"]))
                if isinstance(body, dict):
                    bodies.append(body)
            except json.JSONDecodeError:
                pass
        for value in node.values():
            bodies.extend(_find_section_bodies(value))
    elif isinstance(node, list):
        for value in node:
            bodies.extend(_find_section_bodies(value))
    return bodies


def collect_lovbjerg_offers(
    config: dict[str, Any], session: requests.Session, now: datetime | None = None
) -> tuple[list[Offer], list[str]]:
    errors: list[str] = []
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        response = session.get(LOVBJERG_VEJEN_URL, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        widget = soup.select_one('.tjek-widget[data-type="publication-viewer"]')
        if not widget:
            return [], ["Løvbjerg: publication widget not found"]
        api_key = str(widget.get("data-api-key") or "")
        current_publication_id = str(widget.get("data-id") or "")
        dealer_id = str(widget.get("data-business-id") or "")
        if not api_key or not dealer_id:
            return [], ["Løvbjerg: widget metadata incomplete"]
    except Exception as exc:
        return [], [f"Løvbjerg page: {type(exc).__name__}: {exc}"]

    headers = {
        "User-Agent": USER_AGENT,
        "X-Api-Key": api_key,
        "X-Widgets-Version": "v1",
        "Content-Type": "application/json",
    }
    try:
        response = session.get(
            TJEK_CATALOGS_URL,
            params={"dealer_id": dealer_id, "types": "paged,incito"},
            headers=headers,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        catalogs = response.json()
        if not isinstance(catalogs, list):
            raise ValueError("catalog response is not a list")
    except Exception as exc:
        return [], [f"Løvbjerg catalogs: {type(exc).__name__}: {exc}"]

    visible_publications: list[dict[str, Any]] = []
    future_limit = now + timedelta(days=14)
    for catalog in catalogs:
        if not isinstance(catalog, dict):
            continue
        pub_id = str(catalog.get("id") or "")
        label = normalize_text(catalog.get("label"))
        run_from = parse_timestamp(catalog.get("run_from"))
        run_till = parse_timestamp(catalog.get("run_till"))
        publish = parse_timestamp(catalog.get("publish"))
        is_vejen = "vejen" in label or pub_id == current_publication_id
        is_visible = publish is None or publish <= now
        if (
            is_vejen
            and is_visible
            and run_from
            and run_till
            and run_till >= now
            and run_from <= future_limit
            and "incito" in [str(x).lower() for x in catalog.get("types", [])]
        ):
            visible_publications.append(catalog)

    all_offers: dict[str, Offer] = {}
    for publication in visible_publications:
        pub_id = str(publication.get("id") or "")
        root_body = {
            "id": pub_id,
            "device_category": "desktop",
            "orientation": "vertical",
            "pointer": "fine",
            "pixel_ratio": 1,
            "max_width": 1000,
            "versions_supported": ["1.0.0"],
        }
        try:
            root_response = session.post(
                TJEK_INCITO_URL, headers=headers, json=root_body, timeout=TIMEOUT_SECONDS
            )
            root_response.raise_for_status()
            root = root_response.json()
            section_bodies = _find_section_bodies(root.get("root_view"))
        except Exception as exc:
            errors.append(f"Løvbjerg {pub_id} root: {type(exc).__name__}: {exc}")
            continue

        unique_bodies: list[dict[str, Any]] = []
        section_ids: set[str] = set()
        for body in section_bodies:
            section_id = str(body.get("section_id") or "")
            if section_id and section_id not in section_ids:
                section_ids.add(section_id)
                unique_bodies.append(body)

        def fetch_section(body: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
            try:
                r = requests.post(
                    TJEK_SECTION_URL, headers=headers, json=body, timeout=TIMEOUT_SECONDS
                )
                r.raise_for_status()
                data = r.json()
                return data, None
            except Exception as exc:
                return {}, f"section {body.get('section_id')}: {type(exc).__name__}: {exc}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for section, error in pool.map(fetch_section, unique_bodies):
                if error:
                    errors.append(f"Løvbjerg {pub_id} {error}")
                    continue
                for node in _find_offer_nodes(section):
                    product = {
                        "store": "Løvbjerg",
                        "name": str(node.get("accessibility_label") or "").split(", DKK", 1)[0],
                        "description": " | ".join(_descendant_texts(node)),
                    }
                    for group in config.get("watch_groups", []):
                        if not matches_group(product, group):
                            continue
                        offer = parse_lovbjerg_offer_node(node, publication, group)
                        if offer and offer_phase(offer, now) != "expired":
                            all_offers[offer.key] = offer

    return list(all_offers.values()), errors


def collect_offers(
    config: dict[str, Any], session: requests.Session, now: datetime | None = None
) -> tuple[list[Offer], list[str]]:
    etilbud, errors = collect_etilbudsavis_offers(config, session)
    lovbjerg, lovbjerg_errors = collect_lovbjerg_offers(config, session, now=now)
    errors.extend(lovbjerg_errors)

    preferred: dict[str, Offer] = {}
    source_priority = {"etilbudsavis": 1, "lovbjerg_direct": 2}
    for offer in etilbud + lovbjerg:
        current = preferred.get(offer.fingerprint)
        if current is None or source_priority.get(offer.source, 0) > source_priority.get(current.source, 0):
            preferred[offer.fingerprint] = offer

    return sorted(
        preferred.values(),
        key=lambda o: (
            0 if offer_phase(o, now) == "current" else 1,
            o.valid_from,
            o.group_label,
            o.price if o.price is not None else 10**9,
            o.store,
        ),
    ), errors


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not config.get("watch_groups"):
        raise ValueError("family_watchlist.json has no watch_groups")
    return config


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"version": 2, "events": {}, "last_run_at": None}
    try:
        with STATE_PATH.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            raise ValueError("state must be an object")
        state.setdefault("version", 2)
        state.setdefault("events", {})
        return state
    except Exception:
        return {"version": 2, "events": {}, "last_run_at": None}


def prune_events(events: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - timedelta(days=STATE_RETENTION_DAYS)
    kept: dict[str, Any] = {}
    for key, event in events.items():
        if not isinstance(event, dict):
            continue
        valid_until = parse_timestamp(event.get("valid_until"))
        if valid_until is None or valid_until >= cutoff:
            kept[key] = event
    return kept


def phase_alert_needed(offer: Offer, event: dict[str, Any], now: datetime | None = None) -> str | None:
    phase = offer_phase(offer, now)
    if phase == "upcoming" and not event.get("upcoming_sent_at"):
        return "upcoming"
    if phase == "current" and not event.get("current_sent_at"):
        return "current"
    return None


def build_message(offer: Offer, phase: str) -> str:
    if phase == "upcoming":
        heading = f"🟡 **KOMMENDE TILBUD — {offer.store}**"
    else:
        heading = f"🟢 **AKTUELT TILBUD — {offer.store}**"

    lines = [
        heading,
        f"**{offer.name}**",
        f"💰 **{format_price(offer.price)}**",
        f"📅 Gælder: **{format_period(offer)}**",
        f"🔎 Matcher: {offer.group_label}",
    ]
    if offer.description:
        short_description = offer.description[:220].strip()
        if short_description and normalize_text(short_description) != normalize_text(offer.name):
            lines.append(f"ℹ️ {short_description}")
    if offer.publication_label:
        lines.append(f"📖 {offer.publication_label}")
    if offer.url:
        lines.append(offer.url)
    return "\n".join(lines)


def send_discord(message: str, session: requests.Session) -> None:
    response = session.post(WEBHOOK_URL, json={"content": message}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()


def main() -> int:
    config = load_config()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/json"})
    now = datetime.now(timezone.utc)

    offers, errors = collect_offers(config, session, now=now)
    state = load_state()
    events = prune_events(state.get("events", {}), now=now)
    pending: list[tuple[Offer, str]] = []
    for offer in offers:
        event = events.get(offer.key, {}) if isinstance(events.get(offer.key, {}), dict) else {}
        phase = phase_alert_needed(offer, event, now=now)
        if phase:
            pending.append((offer, phase))

    print(
        f"Family Watch: {len(offers)} dated matching offers; {len(pending)} pending alerts "
        f"across {len(config['watch_groups'])} watch groups"
    )
    for offer, phase in pending:
        print("\n" + build_message(offer, phase))

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

    sent_count = 0
    now_text = now.isoformat().replace("+00:00", "Z")
    for offer, phase in pending:
        send_discord(build_message(offer, phase), session)
        event = events.setdefault(offer.key, {})
        event[f"{phase}_sent_at"] = now_text
        event["valid_from"] = offer.valid_from.isoformat().replace("+00:00", "Z")
        event["valid_until"] = offer.valid_until.isoformat().replace("+00:00", "Z")
        event["store"] = offer.store
        event["name"] = offer.name
        event["source"] = offer.source
        sent_count += 1
        time.sleep(0.25)

    state["version"] = 2
    state["events"] = events
    state["last_run_at"] = now_text
    state["last_match_count"] = len(offers)
    state["last_alert_count"] = sent_count
    with STATE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    print(f"Production mode: sent {sent_count} alerts; state saved to {STATE_PATH}")
    return 0 if offers or not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
