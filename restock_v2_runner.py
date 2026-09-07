#!/usr/bin/env python3
"""Thin production runner for Restock V2 Discord routing.

The legacy scanner remains the data/fetch engine while channel policy is moved
out of its large module. The legacy file has executable startup code after its
START marker, so this runner loads definitions first, patches the channel gate,
and only then executes the startup section.
"""

from concurrent.futures import ThreadPoolExecutor
import re
from pathlib import Path

from alert_policy import TIER_A_SOURCES, tier_a_signal_allowed, tier_b_signal_allowed
from faraos_parser_v2 import faraos_name_v2

SCANNER_FILE = Path(__file__).resolve().parent / "restock_bot_github.py"
START_MARKER = (
    "# =========================================================\n"
    "# START\n"
    "# ========================================================="
)

TIER_A_LABELS = {
    "coolshop": "COOLSHOP",
    "proshop": "PROSHOP",
    "br": "BR",
    "bilka": "BILKA",
    "foetex": "FØTEX",
}

PRICE_WATCH_FOCUS_MAX_PRICE = {
    "UPC": 2000.0,
    "SPC": 1500.0,
    "COLLECTION": 1000.0,
    "TIN": 500.0,
}

PRICE_WATCH_EXTRA_FOCUS_SETS = (
    ("Surging Sparks", ("surging sparks", "surging spark")),
    ("Twilight Masquerade", ("twilight masquerade",)),
    ("Mega Evolution", ("mega evolution",)),
    ("Journey Together", ("journey together",)),
    (
        "30th Anniversary",
        (
            "pokemon 30th",
            "pokémon 30th",
            "30th anniversary",
            "30th celebration",
            "30th celebrations",
        ),
    ),
)

# Faraos' top-level Pokemon category currently reports many products but only
# renders part of the catalogue in the repeated card structure used by the
# legacy parser. Scan the stable public sealed subcategories instead. Keep the
# parent pages first so existing IDs remain stable for products still visible
# there, while the granular feeds recover the missing catalogue rows.
FARAOS_V3_FEEDS = (
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/booster"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/boosterdisplay"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/pokemondisplays"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/collectionbokse"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/elitetrainerbox"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/premiumcollection"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/tins"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/3-pak"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/2-pack"),
    ("POKÉMON", "https://www.faraos.dk/games/kortspil/pokemon/checklane"),
    ("LORCANA", "https://www.faraos.dk/games/kortspil/lorcana"),
    ("LORCANA", "https://www.faraos.dk/games/kortspil/lorcana/boosters"),
)

if tuple(TIER_A_LABELS) != tuple(TIER_A_SOURCES):
    raise RuntimeError("Restock runner er ikke synkron med TIER_A_SOURCES")


def _clean_lines(message):
    return [
        line.replace("**", "").strip()
        for line in str(message or "").splitlines()
        if line.strip()
    ]


def _event_from_headline(headline):
    upper = str(headline or "").upper()
    if "FORUDBESTILLING" in upper or "PREORDER" in upper:
        return "PREORDER"
    if "RESTOCK" in upper:
        return "RESTOCK"
    if "NYT" in upper or "NY " in upper:
        return "NEW"
    return None


def _is_tier_a_headline(headline):
    upper = str(headline or "").upper()
    return any(
        re.search(rf"\b{re.escape(label)}\b", upper)
        for label in TIER_A_LABELS.values()
    )


def restock_v2_channel_alert_allowed(message, legacy_policy=None):
    """Keep Tier A fast but filtered; make Tier B Discord deliberately strict."""
    lines = _clean_lines(message)
    if not lines:
        return False

    headline = lines[0]
    event = _event_from_headline(headline)

    # Non-product operational output keeps the legacy decision until those
    # concerns are moved to their dedicated channels in a later cleanup.
    if event is None:
        return legacy_policy(message) if legacy_policy is not None else True

    if len(lines) < 2:
        return False

    product_name = lines[1]

    # Tier A remains the fast retail lane, but even Tier A should not fill the
    # Restock channel with ordinary Pitch Black/Chaos Rising packs and ETBs.
    if _is_tier_a_headline(headline):
        return tier_a_signal_allowed(product_name, event=event)

    return tier_b_signal_allowed(product_name, event=event)


def load_scanner_parts():
    source = SCANNER_FILE.read_text(encoding="utf-8")
    if START_MARKER not in source:
        raise RuntimeError("Kunne ikke finde START-markøren i restock_bot_github.py")
    definitions, startup = source.split(START_MARKER, 1)
    return definitions, startup


def _install_price_watch_focus_sets(namespace):
    current = tuple(namespace.get("PRICE_WATCH_FOCUS_SETS") or ())
    if not current:
        raise RuntimeError("Price Watch focus hook mangler PRICE_WATCH_FOCUS_SETS")

    existing = {canonical for canonical, _aliases in current}
    additions = tuple(
        entry
        for entry in PRICE_WATCH_EXTRA_FOCUS_SETS
        if entry[0] not in existing
    )
    namespace["PRICE_WATCH_FOCUS_SETS"] = current + additions


def _install_price_watch_focus_caps(namespace):
    collector = namespace.get("collect_price_watch_focus_listings")
    if collector is None:
        raise RuntimeError("Price Watch focus hook mangler collect_price_watch_focus_listings")

    def capped_collector(current_state, fresh_sources=None):
        listings = collector(current_state, fresh_sources=fresh_sources)
        return {
            key: listing
            for key, listing in listings.items()
            if (
                PRICE_WATCH_FOCUS_MAX_PRICE.get(listing.get("type")) is None
                or float(listing.get("price") or 0) <= PRICE_WATCH_FOCUS_MAX_PRICE[listing.get("type")]
            )
        }

    namespace["collect_price_watch_focus_listings"] = capped_collector


def _install_faraos_parser(namespace):
    legacy_name = namespace.get("_faraos_name")
    clean_text = namespace.get("woocommerce_clean_text")
    if legacy_name is None or clean_text is None:
        raise RuntimeError("Faraos parser-hook mangler forventede legacy-funktioner")

    def patched_faraos_name(card):
        return faraos_name_v2(card, legacy_name, clean_text)

    namespace["_faraos_name"] = patched_faraos_name
    namespace["FARAOS_FEEDS"] = FARAOS_V3_FEEDS


def _install_kelz0r_fast_fetch(namespace):
    """Scan Kelz0r's two independent categories concurrently.

    The legacy implementation walks each category page-by-page in sequence.
    We keep that conservative per-category request pattern, but run the booster
    and tin categories in parallel. This caps Kelz0r at two simultaneous HTTP
    requests while preserving product IDs, filtering and state semantics.
    """
    required = (
        "KELZ0R_FEEDS",
        "requests",
        "BeautifulSoup",
        "BROWSER_HEADERS",
        "urljoin",
        "hashlib",
        "woocommerce_clean_text",
        "woocommerce_is_relevant_sealed",
        "_wave5_synthetic",
        "_wave5_nearest_card",
        "_wave5_anchor_name",
        "_wave5_price",
        "_wave5_product",
    )
    missing = [name for name in required if namespace.get(name) is None]
    if missing:
        raise RuntimeError("Kelz0r fast hook mangler: " + ", ".join(missing))

    feeds = tuple(namespace["KELZ0R_FEEDS"])
    requests_mod = namespace["requests"]
    soup_cls = namespace["BeautifulSoup"]
    headers = namespace["BROWSER_HEADERS"]
    urljoin = namespace["urljoin"]
    hashlib_mod = namespace["hashlib"]
    clean_text = namespace["woocommerce_clean_text"]
    relevant_sealed = namespace["woocommerce_is_relevant_sealed"]
    wave5_synthetic = namespace["_wave5_synthetic"]
    nearest_card = namespace["_wave5_nearest_card"]
    anchor_name = namespace["_wave5_anchor_name"]
    wave5_price = namespace["_wave5_price"]
    wave5_product = namespace["_wave5_product"]

    def is_product_url(value):
        return bool(re.search(r"-p-\d+\.html(?:$|[?#])", value or "", flags=re.I))

    def canonical_url(value):
        return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/")

    def stable_product_id(product_url):
        match = re.search(r"-p-(\d+)\.html$", product_url, flags=re.I)
        if match:
            return f"kelz0r:{match.group(1)}"
        return "kelz0r:" + hashlib_mod.sha256(product_url.encode("utf-8")).hexdigest()[:20]

    def fetch_feed(base_url):
        products = {}
        seen_urls = set()
        session = requests_mod.Session()
        session.headers.update(
            {
                **headers,
                "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
            }
        )

        for page in range(1, 31):
            separator = "&" if "?" in base_url else "?"
            page_url = base_url if page == 1 else f"{base_url}{separator}page={page}"
            response = session.get(page_url, timeout=30)
            response.raise_for_status()
            soup = soup_cls(response.text, "html.parser")

            page_product_urls = set()
            for anchor in soup.find_all("a", href=True):
                href = urljoin(page_url, anchor.get("href"))
                if is_product_url(href):
                    page_product_urls.add(canonical_url(href))

            if not page_product_urls:
                break

            # Some shops repeat the final catalogue page for out-of-range page
            # numbers. Stop as soon as pagination yields no unseen product URLs.
            if not (page_product_urls - seen_urls):
                break

            for anchor in soup.find_all("a", href=True):
                href = urljoin(page_url, anchor.get("href"))
                if not is_product_url(href):
                    continue

                product_url = canonical_url(href)
                if product_url in seen_urls:
                    continue

                card = nearest_card(anchor, is_product_url)
                name = anchor_name(anchor, card)
                if not name or not relevant_sealed(wave5_synthetic(name, "POKÉMON")):
                    seen_urls.add(product_url)
                    continue

                card_text = clean_text(card.get_text(" ", strip=True))
                low = card_text.lower()
                preorder = any(
                    marker in low
                    for marker in (
                        "[preorder]", "preorder", "pre-order", "forudbestil",
                        "forudbestilling", "forhåndsbestilling", "forhandsbestilling",
                    )
                )
                explicit_out = any(
                    marker in low
                    for marker in (
                        "meddela", "notify", "giv mig besked", "udsolgt",
                        "ikke på lager", "ikke pa lager",
                    )
                )
                explicit_in = any(
                    marker in low
                    for marker in (
                        "køb nu", "koeb nu", "köp nu", "kop nu", "buy now",
                        "læg i indkøbskurv", "laeg i indkoebskurv",
                        "læg i kurv", "laeg i kurv", "add to cart",
                    )
                )

                product_id = stable_product_id(product_url)
                products[product_id] = wave5_product(
                    name,
                    "POKÉMON",
                    wave5_price(card_text),
                    explicit_in and not explicit_out,
                    preorder,
                    product_url,
                )
                seen_urls.add(product_url)

        return products

    def fast_kelz0r_products():
        if len(feeds) < 2:
            return fetch_feed(feeds[0]) if feeds else {}

        products = {}
        with ThreadPoolExecutor(max_workers=min(2, len(feeds))) as executor:
            for partial in executor.map(fetch_feed, feeds):
                products.update(partial)
        return products

    namespace["get_kelz0r_products"] = fast_kelz0r_products


def main():
    definitions, startup = load_scanner_parts()
    namespace = {
        "__name__": "restock_v2_scanner",
        "__file__": str(SCANNER_FILE),
    }

    exec(compile(definitions, str(SCANNER_FILE), "exec"), namespace)
    legacy_policy = namespace["restock_channel_alert_allowed"]
    _install_price_watch_focus_sets(namespace)
    _install_price_watch_focus_caps(namespace)
    _install_faraos_parser(namespace)
    _install_kelz0r_fast_fetch(namespace)

    def channel_policy(message):
        return restock_v2_channel_alert_allowed(
            message,
            legacy_policy=legacy_policy,
        )

    namespace["restock_channel_alert_allowed"] = channel_policy
    exec(compile(startup, str(SCANNER_FILE), "exec"), namespace)


if __name__ == "__main__":
    main()
