import os
import re
from collections import Counter

import requests


WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
BASE_URL = "https://api.etilbudsavis.dk/v2"

# Hent bredt nok til også at få Esbjerg med, men filtrer bagefter hårdt til
# de fire byer vi vil teste først.
KOLDING_LAT = 55.4904
KOLDING_LNG = 9.4722
LOCAL_RADIUS_METERS = 100000
TARGET_CITY_MARKERS = (
    "brørup",
    "brorup",
    "vejen",
    "kolding",
    "esbjerg",
)
TARGET_CITY_LABEL = "Brørup · Vejen · Kolding · Esbjerg"

COOP_CHAIN_MARKERS = (
    "kvickly",
    "superbrugsen",
    "brugsen",
    "365discount",
    "365 discount",
)

KNOWN_COOP_DEALERS = {
    "c1edq": "Kvickly",
    "0b1e8": "SuperBrugsen",
    "d311fg": "Brugsen",
    "DWZE1w": "365discount",
}

POKEMON_QUERIES = (
    "pokemon",
    "pokémon",
    "pokemon kort",
    "pokemon tcg",
    "pokemon booster",
    "pokemon elite trainer",
    "pokemon etb",
    "pokemon tin",
)

SEALED_PRODUCT_MARKERS = (
    "booster",
    "elite trainer",
    " etb",
    "etb ",
    " tin",
    "tin ",
    "mini tin",
    "poké ball tin",
    "poke ball tin",
)

HEADERS = {"User-Agent": "Pokemon-Lorcana-MasterBot/coop-probe-v1.3"}


def get_json(path, params=None):
    response = requests.get(
        BASE_URL + path,
        params=params or {},
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def normalize(value):
    text = str(value or "").strip().lower()
    text = text.replace("pokémon", "pokemon")
    return re.sub(r"\s+", " ", text)


def is_coop_name(value):
    text = normalize(value)
    return any(marker in text for marker in COOP_CHAIN_MARKERS)


def is_target_city(name, city, postal=""):
    text = normalize(f"{name} {city} {postal}")
    return any(marker in text for marker in TARGET_CITY_MARKERS)


def offer_text(offer):
    return normalize(
        " ".join(
            [
                str(offer.get("heading") or ""),
                str(offer.get("description") or ""),
            ]
        )
    )


def is_pokemon_tcg_offer(offer):
    text = offer_text(offer)
    if "pokemon" not in text:
        return False

    blocked = (
        "panini",
        "match attax",
        "one piece",
        "magic the gathering",
        "yu-gi-oh",
        "yugioh",
        "legetøj",
        "legetoj",
        "figur",
        "bamse",
        "plush",
    )
    if any(marker in text for marker in blocked):
        return False

    return any(marker in text for marker in SEALED_PRODUCT_MARKERS)


def dealer_name(offer, dealers_by_id):
    dealer_id = str(offer.get("dealer_id") or "")
    branding = (offer.get("branding") or {}).get("name")
    nested = (offer.get("dealer") or {}).get("name")
    return str(
        branding
        or nested
        or dealers_by_id.get(dealer_id)
        or KNOWN_COOP_DEALERS.get(dealer_id)
        or "Ukendt"
    )


def format_price(offer):
    pricing = offer.get("pricing") or {}
    value = pricing.get("price")
    try:
        return f"{float(value):.2f} kr.".replace(".", ",")
    except (TypeError, ValueError):
        return "pris ukendt"


def fetch_dealers():
    raw = get_json("/dealers", {"country_id": "DK", "limit": 250})
    if not isinstance(raw, list):
        raise RuntimeError("Tjek /dealers returnerede ikke en liste")

    dealers = {}
    coop_dealers = {}
    for dealer in raw:
        dealer_id = str(dealer.get("id") or "")
        name = str(dealer.get("name") or "")
        if not dealer_id:
            continue
        dealers[dealer_id] = name
        if is_coop_name(name):
            coop_dealers[dealer_id] = name

    return dealers, coop_dealers


def fetch_coop_offer_signals(dealers_by_id):
    offers = {}
    discovered_coop_dealers = {}
    query_errors = []
    rejected_rows = 0

    for query in POKEMON_QUERIES:
        try:
            raw = get_json(
                "/offers/search",
                {"query": query, "limit": 100, "country_id": "DK"},
            )
        except Exception as error:
            query_errors.append(f"{query}: {type(error).__name__}")
            continue

        if not isinstance(raw, list):
            continue

        for offer in raw:
            dealer_id = str(offer.get("dealer_id") or "")
            name = dealer_name(offer, dealers_by_id)

            if not is_coop_name(name) and dealer_id not in KNOWN_COOP_DEALERS:
                continue

            if dealer_id:
                discovered_coop_dealers[dealer_id] = (
                    KNOWN_COOP_DEALERS.get(dealer_id) or name
                )

            if not is_pokemon_tcg_offer(offer):
                rejected_rows += 1
                continue

            offer_id = str(offer.get("id") or "")
            key = offer_id or (
                f"{dealer_id}|{offer.get('heading')}|"
                f"{(offer.get('pricing') or {}).get('price')}"
            )
            row = dict(offer)
            row["_chain_name"] = KNOWN_COOP_DEALERS.get(dealer_id) or name
            offers[key] = row

    return list(offers.values()), discovered_coop_dealers, query_errors, rejected_rows


def fetch_local_stores(coop_dealers):
    found = []
    errors = []

    for dealer_id, chain_name in coop_dealers.items():
        try:
            raw = get_json(
                "/stores",
                {
                    "dealer_id": dealer_id,
                    "r_lat": KOLDING_LAT,
                    "r_lng": KOLDING_LNG,
                    "r_radius": LOCAL_RADIUS_METERS,
                    "limit": 200,
                },
            )
        except Exception as error:
            errors.append(f"{chain_name}: {type(error).__name__}")
            continue

        if not isinstance(raw, list):
            continue

        for store in raw:
            name = str(store.get("name") or store.get("title") or chain_name)
            address = store.get("address") or {}
            city = str(address.get("city") or store.get("city") or "")
            postal = str(address.get("zip_code") or address.get("zip") or "")
            store_id = str(store.get("id") or "")

            if not is_target_city(name, city, postal):
                continue

            found.append(
                {
                    "chain": chain_name,
                    "name": name,
                    "city": city,
                    "postal": postal,
                    "id": store_id,
                }
            )

    unique = {}
    for store in found:
        key = store["id"] or f"{store['chain']}|{store['name']}|{store['city']}"
        unique[key] = store

    return list(unique.values()), errors


def send_report(
    dealers,
    api_coop_dealers,
    discovered_coop_dealers,
    stores,
    store_errors,
    offers,
    query_errors,
    rejected_rows,
):
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    store_counts = Counter(store["chain"] for store in stores)

    lines = [
        "**Isoleret probe - ingen ændring af normal restock-logik.**",
        f"🎯 Område: **{TARGET_CITY_LABEL}**",
        "",
        f"🏪 Coop-kæder vi tester: **{len(KNOWN_COOP_DEALERS)}**",
        f"📍 Matchende Coop-butikker: **{len(stores)}**",
        f"🎴 Reelle booster/ETB/tin-signaler: **{len(offers)}**",
        f"🧹 Frasorterede brede/irrelevante Coop-hits: **{rejected_rows}**",
    ]

    if store_errors:
        lines.append(
            f"⚠️ /stores fejl på {len(store_errors)} kæde(r): "
            + ", ".join(store_errors)
        )
    if query_errors:
        lines.append(f"⚠️ Offer-query fejl: {len(query_errors)}")

    lines.append("")
    lines.append("**Kædedækning i de fire byer:**")
    for dealer_id, chain_name in KNOWN_COOP_DEALERS.items():
        lines.append(
            f"• {chain_name}: **{store_counts.get(chain_name, 0)} butikker** · `{dealer_id}`"
        )

    if stores:
        lines.append("")
        lines.append("**Butikker i scope:**")

        city_order = {"brørup": 0, "brorup": 0, "vejen": 1, "kolding": 2, "esbjerg": 3}

        def store_priority(row):
            text = normalize(f"{row['name']} {row['city']}")
            rank = 99
            for marker, value in city_order.items():
                if marker in text:
                    rank = min(rank, value)
            return (rank, row["chain"], row["name"])

        for store in sorted(stores, key=store_priority):
            location = " ".join(
                x for x in (store["postal"], store["city"]) if x
            ).strip()
            suffix = f" - {location}" if location else ""
            lines.append(f"• {store['chain']}: {store['name']}{suffix}")

    if offers:
        lines.append("")
        lines.append("**Pokémon sealed-signaler lige nu:**")
        for offer in sorted(
            offers,
            key=lambda row: (
                str(row.get("_chain_name") or ""),
                str(row.get("heading") or ""),
            ),
        )[:10]:
            heading = str(offer.get("heading") or "Ukendt vare")
            run_from = str(offer.get("run_from") or "")[:10]
            run_till = str(offer.get("run_till") or "")[:10]
            period = ""
            if run_from or run_till:
                period = f" · {run_from or '?'} -> {run_till or '?'}"
            lines.append(
                f"• **{offer.get('_chain_name', 'Coop')}** - {heading} - "
                f"{format_price(offer)}{period}"
            )
    else:
        lines.extend(
            [
                "",
                "Ingen aktuelle booster/ETB/tin-tilbud fundet hos Coop i dette scan.",
            ]
        )

    lines.extend(
        [
            "",
            "**Næste stock-spor:**",
            "De fundne store-ID'er i Brørup, Vejen, Kolding og Esbjerg bliver vores "
            "testgrundlag til Coop-appens produkt/EAN-opslag. Målet er at se, om "
            "svaret indeholder availability/quantity/stock - ikke kun lokal pris.",
        ]
    )

    payload = {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "🧪 COOP PROBE V1.3 - 4 BYER",
                "description": "\n".join(lines)[:4090],
                "color": 0xF1C40F,
                "footer": {"text": "MasterBot · Coop probe · Brørup/Vejen/Kolding/Esbjerg"},
            }
        ],
    }

    response = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    response.raise_for_status()


if __name__ == "__main__":
    dealers = {}
    api_coop_dealers = {}
    discovered_coop_dealers = {}
    stores = []
    offers = []
    store_errors = []
    query_errors = []
    rejected_rows = 0

    try:
        dealers, api_coop_dealers = fetch_dealers()
    except Exception as error:
        print(f"COOP PROBE dealers FEJL: {error}")

    try:
        (
            offers,
            discovered_coop_dealers,
            query_errors,
            rejected_rows,
        ) = fetch_coop_offer_signals(dealers)
    except Exception as error:
        query_errors.append(str(error))
        print(f"COOP PROBE offers FEJL: {error}")

    combined_coop_dealers = dict(KNOWN_COOP_DEALERS)
    combined_coop_dealers.update(api_coop_dealers)
    combined_coop_dealers.update(discovered_coop_dealers)

    stores, store_errors = fetch_local_stores(combined_coop_dealers)
    print(
        f"COOP PROBE V1.3: {len(stores)} butikker i {TARGET_CITY_LABEL} | "
        f"{len(store_errors)} fejl"
    )

    send_report(
        dealers,
        api_coop_dealers,
        discovered_coop_dealers,
        stores,
        store_errors,
        offers,
        query_errors,
        rejected_rows,
    )
