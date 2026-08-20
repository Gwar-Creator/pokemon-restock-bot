import os
import re
import requests


WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
BASE_URL = "https://api.etilbudsavis.dk/v2"

# Fast geografisk sanity check omkring Kolding.
KOLDING_LAT = 55.4904
KOLDING_LNG = 9.4722
LOCAL_RADIUS_METERS = 55000

COOP_CHAIN_MARKERS = (
    "kvickly",
    "superbrugsen",
    "brugsen",
    "365discount",
    "365 discount",
)

POKEMON_QUERIES = (
    "pokemon",
    "pokémon",
    "booster",
    "elite trainer box",
    "etb",
    "tin",
)

HEADERS = {
    "User-Agent": "Pokemon-Lorcana-MasterBot/coop-probe-v1"
}


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
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def is_coop_name(value):
    text = normalize(value)
    return any(marker in text for marker in COOP_CHAIN_MARKERS)


def is_pokemon_offer(offer):
    text = normalize(
        " ".join(
            [
                str(offer.get("heading") or ""),
                str(offer.get("description") or ""),
                str((offer.get("branding") or {}).get("name") or ""),
            ]
        )
    )

    positive = (
        "pokemon",
        "pokémon",
        "booster",
        "elite trainer",
        " etb",
        "tin",
    )
    blocked = (
        "panini",
        "match attax",
        "one piece",
        "magic the gathering",
        "yu-gi-oh",
        "yugioh",
    )
    return any(marker in text for marker in positive) and not any(
        marker in text for marker in blocked
    )


def dealer_name(offer, dealers_by_id):
    dealer_id = str(offer.get("dealer_id") or "")
    branding = (offer.get("branding") or {}).get("name")
    nested = (offer.get("dealer") or {}).get("name")
    return str(branding or nested or dealers_by_id.get(dealer_id) or "Ukendt")


def format_price(offer):
    pricing = offer.get("pricing") or {}
    value = pricing.get("price")
    try:
        return f"{float(value):.2f} kr.".replace(".", ",")
    except (TypeError, ValueError):
        return "pris ukendt"


def fetch_dealers():
    raw = get_json(
        "/dealers",
        {"country_id": "DK", "limit": 250},
    )
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


def fetch_local_stores(coop_dealers):
    # /stores er et ekstra probe-lag. Hvis endpointet ikke længere accepterer
    # de klassiske radius-parametre, må det ikke få hele testen til at fejle.
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
                    "limit": 100,
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

            found.append(
                {
                    "chain": chain_name,
                    "name": name,
                    "city": city,
                    "postal": postal,
                    "id": store_id,
                }
            )

    # Dedupe på ID/navn, da nogle kæder kan overlappe i søgningen.
    unique = {}
    for store in found:
        key = store["id"] or f"{store['chain']}|{store['name']}|{store['city']}"
        unique[key] = store

    return list(unique.values()), errors


def fetch_pokemon_offers(dealers_by_id, coop_dealers):
    offers = {}
    query_errors = []

    for query in POKEMON_QUERIES:
        try:
            raw = get_json(
                "/offers/search",
                {
                    "query": query,
                    "limit": 100,
                    "country_id": "DK",
                },
            )
        except Exception as error:
            query_errors.append(f"{query}: {type(error).__name__}")
            continue

        if not isinstance(raw, list):
            continue

        for offer in raw:
            dealer_id = str(offer.get("dealer_id") or "")
            name = dealer_name(offer, dealers_by_id)

            # Først exact dealer-id, fallback til brand/dealer-navn.
            if dealer_id not in coop_dealers and not is_coop_name(name):
                continue
            if not is_pokemon_offer(offer):
                continue

            offer_id = str(offer.get("id") or "")
            key = offer_id or (
                f"{dealer_id}|{offer.get('heading')}|"
                f"{(offer.get('pricing') or {}).get('price')}"
            )
            row = dict(offer)
            row["_chain_name"] = name
            offers[key] = row

    return list(offers.values()), query_errors


def send_report(dealers, coop_dealers, stores, store_errors, offers, query_errors):
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL mangler")

    lines = [
        "**Isoleret probe - ingen ændring af normal restock-logik.**",
        "",
        f"✅ Tjek API/dealers: **{len(dealers)} danske kæder**",
        f"🏪 Coop-kæder fundet: **{len(coop_dealers)}**",
        f"📍 Lokale Coop-butikker via /stores: **{len(stores)}**",
        f"🎴 Aktuelle Pokémon-signaler hos Coop: **{len(offers)}**",
    ]

    if store_errors:
        lines.append(
            f"⚠️ Store-endpoint fejl på {len(store_errors)} kæde(r) - "
            "offer-signalet kan stadig bruges."
        )

    if query_errors:
        lines.append(f"⚠️ Offer-query fejl: {len(query_errors)}")

    if coop_dealers:
        lines.append("")
        lines.append("**Coop-kæder i API'et:**")
        for name in sorted(set(coop_dealers.values())):
            lines.append(f"• {name}")

    if stores:
        lines.append("")
        lines.append("**Lokale butikker fundet:**")
        for store in sorted(stores, key=lambda row: (row["chain"], row["city"], row["name"]))[:12]:
            location = " ".join(x for x in (store["postal"], store["city"]) if x).strip()
            suffix = f" - {location}" if location else ""
            lines.append(f"• {store['chain']}: {store['name']}{suffix}")

    if offers:
        lines.append("")
        lines.append("**Pokémon/TCG-signaler lige nu:**")
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
                "Ingen aktuelle Pokémon-tilbud fundet hos Coop i dette scan.",
            ]
        )

    lines.extend(
        [
            "",
            "**Konklusion på proben:**",
            "Tjek-signalet kan bruges til Coop-kampagner/tilbud og butiksliste. "
            "Det dokumenterer ikke fysisk lagerantal. Live stock kræver et separat "
            "Coop/app-lagerendpoint, hvis vi kan finde et offentligt anvendeligt et.",
        ]
    )

    payload = {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "🧪 COOP PROBE V1",
                "description": "\n".join(lines)[:4090],
                "color": 0xF1C40F,
                "footer": {"text": "MasterBot · Coop probe · one-time test"},
            }
        ],
    }

    response = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    response.raise_for_status()


if __name__ == "__main__":
    dealers = {}
    coop_dealers = {}
    stores = []
    offers = []
    store_errors = []
    query_errors = []

    try:
        dealers, coop_dealers = fetch_dealers()
        print(
            f"COOP PROBE: {len(dealers)} dealers | "
            f"{len(coop_dealers)} Coop dealers"
        )
    except Exception as error:
        print(f"COOP PROBE dealers FEJL: {error}")

    if coop_dealers:
        stores, store_errors = fetch_local_stores(coop_dealers)
        print(
            f"COOP PROBE stores: {len(stores)} lokale fund | "
            f"{len(store_errors)} fejl"
        )

    try:
        offers, query_errors = fetch_pokemon_offers(dealers, coop_dealers)
        print(
            f"COOP PROBE offers: {len(offers)} Coop/Pokémon signaler | "
            f"{len(query_errors)} query-fejl"
        )
    except Exception as error:
        query_errors.append(str(error))
        print(f"COOP PROBE offers FEJL: {error}")

    send_report(
        dealers,
        coop_dealers,
        stores,
        store_errors,
        offers,
        query_errors,
    )
