from pathlib import Path

PATH = Path("restock_bot_github.py")
text = PATH.read_text(encoding="utf-8")

MARKER = "MATCHING_OPPORTUNITY_V40 = True"

if MARKER in text:
    print("V40 matching audit + opportunity score already applied")
    raise SystemExit(0)


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f"V40 patch failed: marker not found for {label}")
    text = text.replace(old, new, 1)


replace_once(
    '''WAVE5_RETAILERS_V38 = True
WAVE5_SOURCE_FIXES_V39 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    '''WAVE5_RETAILERS_V38 = True
WAVE5_SOURCE_FIXES_V39 = True
MATCHING_OPPORTUNITY_V40 = True
RESTOCK_DUPLICATE_COOLDOWN_SECONDS = 6 * 60 * 60
''',
    "V40 marker",
)

replace_once(
    '''PRICE_HISTORY_NEW_LOW_MIN_DKK = 25.0
PRICE_HISTORY_NEW_LOW_MIN_PCT = 5.0

# User-defined retail relevance ceilings.''',
    '''PRICE_HISTORY_NEW_LOW_MIN_DKK = 25.0
PRICE_HISTORY_NEW_LOW_MIN_PCT = 5.0
PRICE_MATCHING_AUDIT_FILE = "price_matching_audit_v1.json"
PRICE_MATCHING_AUDIT_MAX_SUSPECTS = 20

# User-defined retail relevance ceilings.''',
    "V40 constants",
)

v40_helpers = r'''

# =========================================================
# PRICE MATCHING AUDIT V1 + OPPORTUNITY SCORE V1
# =========================================================

def _matching_bigrams(value):
    compact = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index:index + 2] for index in range(len(compact) - 1)}


def _matching_similarity(left, right):
    left = str(left or "").strip().lower()
    right = str(right or "").strip().lower()
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if left_tokens and right_tokens:
        token_score = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))
    else:
        token_score = 0.0

    left_bigrams = _matching_bigrams(left)
    right_bigrams = _matching_bigrams(right)
    if left_bigrams and right_bigrams:
        bigram_score = (
            2.0 * len(left_bigrams & right_bigrams)
            / (len(left_bigrams) + len(right_bigrams))
        )
    else:
        bigram_score = 0.0

    containment = 0.0
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= 5 and shorter in longer:
        containment = 0.94

    return max(token_score, bigram_score, containment)


def build_price_matching_audit(candidates, comparable_groups):
    raw_groups = {}
    for product in candidates:
        product_key = get_price_watch_product_key(product)
        if product_key:
            raw_groups.setdefault(product_key, []).append(product)

    matched_lines = sum(len(products) for products in comparable_groups.values())
    candidate_lines = len(candidates)
    coverage_pct = (
        round(matched_lines / candidate_lines * 100.0, 1)
        if candidate_lines else 0.0
    )

    rows = []
    for product_key, products in raw_groups.items():
        info = parse_price_watch_key(product_key)
        shops = sorted({product.get("shop") for product in products if product.get("shop")})
        names = sorted({str(product.get("name") or "") for product in products if product.get("name")})
        rows.append({
            "product_key": product_key,
            "game": info["game"],
            "type": info["type"],
            "language": info["language"],
            "set_name": info["set_name"],
            "shops": shops,
            "names": names[:4],
            "shop_count": len(shops),
        })

    suspects = []
    for index, left in enumerate(rows):
        for right in rows[index + 1:]:
            if (
                left["game"] != right["game"]
                or left["type"] != right["type"]
                or left["language"] != right["language"]
            ):
                continue
            if left["set_name"] == right["set_name"]:
                continue
            if set(left["shops"]) == set(right["shops"]) and len(left["shops"]) == 1:
                continue
            if left["shop_count"] >= 2 and right["shop_count"] >= 2:
                continue

            similarity = _matching_similarity(left["set_name"], right["set_name"])
            if similarity < 0.82:
                continue

            suspects.append({
                "similarity": round(similarity, 3),
                "game": left["game"],
                "type": left["type"],
                "language": left["language"],
                "left_set": left["set_name"],
                "right_set": right["set_name"],
                "left_shops": left["shops"],
                "right_shops": right["shops"],
                "left_names": left["names"][:2],
                "right_names": right["names"][:2],
            })

    suspects.sort(
        key=lambda row: (
            row["similarity"],
            len(row["left_shops"]) + len(row["right_shops"]),
        ),
        reverse=True,
    )
    suspects = suspects[:PRICE_MATCHING_AUDIT_MAX_SUSPECTS]

    audit = {
        "version": 1,
        "candidate_lines": candidate_lines,
        "exact_comparable_groups": len(comparable_groups),
        "matched_lines": matched_lines,
        "coverage_pct": coverage_pct,
        "normalized_keys": len(raw_groups),
        "single_shop_keys": sum(1 for row in rows if row["shop_count"] < 2),
        "likely_alias_pairs": len(suspects),
        "suspects": suspects,
    }

    print(
        "MATCHING AUDIT V1: "
        f"{candidate_lines} prislinjer | "
        f"{len(comparable_groups)} eksakte grupper | "
        f"{coverage_pct:.1f}% linjedækning | "
        f"{audit['single_shop_keys']} singletons | "
        f"{len(suspects)} mulige alias-par"
    )
    for suspect in suspects[:5]:
        print(
            "MATCHING SUSPECT: "
            f"{suspect['left_set']} <-> {suspect['right_set']} "
            f"({suspect['similarity']:.2f}) | "
            f"{', '.join(suspect['left_shops'])} / {', '.join(suspect['right_shops'])}"
        )

    return audit


def save_price_matching_audit(audit):
    payload = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path = Path(PRICE_MATCHING_AUDIT_FILE)
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old != payload:
        path.write_text(payload, encoding="utf-8")


def _opportunity_history_entry(history_state, product_key):
    history_state = history_state if isinstance(history_state, dict) else {}
    products = history_state.get("products")
    if not isinstance(products, dict):
        return {}
    entry = products.get(product_key)
    return entry if isinstance(entry, dict) else {}


def calculate_opportunity_score(product_key, products, history_state=None):
    ordered = sorted(products, key=lambda product: (product["price"], product["shop"]))
    if not ordered:
        return {
            "score": 0,
            "label": "NORMAL",
            "saving_dkk": 0.0,
            "saving_pct": 0.0,
            "next_price": None,
            "shop_count": 0,
            "historical_low": None,
            "historical_diff_pct": None,
            "components": {},
        }

    cheapest_by_shop = {}
    for product in ordered:
        shop = product["shop"]
        current = cheapest_by_shop.get(shop)
        if current is None or product["price"] < current["price"]:
            cheapest_by_shop[shop] = product
    ordered = sorted(cheapest_by_shop.values(), key=lambda product: (product["price"], product["shop"]))

    best_price = float(ordered[0]["price"])
    distinct_higher = [
        float(product["price"])
        for product in ordered
        if float(product["price"]) > best_price + 0.005
    ]
    next_price = min(distinct_higher) if distinct_higher else None
    saving_dkk = max(0.0, (next_price - best_price) if next_price is not None else 0.0)
    saving_pct = (
        saving_dkk / next_price * 100.0
        if next_price and next_price > 0
        else 0.0
    )

    relative_points = min(35.0, saving_pct * 1.75)
    if saving_dkk >= 200:
        absolute_points = 15.0
    elif saving_dkk >= 100:
        absolute_points = 12.0
    elif saving_dkk >= 50:
        absolute_points = 8.0
    elif saving_dkk >= 25:
        absolute_points = 5.0
    else:
        absolute_points = 0.0

    history_entry = _opportunity_history_entry(history_state, product_key)
    historical_low = history_entry.get("historical_low")
    try:
        historical_low = float(historical_low)
    except (TypeError, ValueError):
        historical_low = None

    historical_diff_pct = None
    history_points = 0.0
    if historical_low and historical_low > 0:
        historical_diff_pct = max(0.0, (best_price / historical_low - 1.0) * 100.0)
        if historical_diff_pct <= 1.0:
            history_points = 25.0
        elif historical_diff_pct <= 5.0:
            history_points = 20.0
        elif historical_diff_pct <= 10.0:
            history_points = 14.0
        elif historical_diff_pct <= 20.0:
            history_points = 7.0

    shop_count = len(ordered)
    if shop_count <= 2:
        scarcity_points = 15.0
    elif shop_count == 3:
        scarcity_points = 12.0
    elif shop_count == 4:
        scarcity_points = 9.0
    elif shop_count == 5:
        scarcity_points = 6.0
    else:
        scarcity_points = 3.0

    observation_days = safe_int(history_entry.get("observation_days"), 0)
    confidence_points = min(10.0, 2.0 + min(shop_count, 4) * 1.5 + min(observation_days, 4) * 0.5)

    score = int(round(min(
        100.0,
        relative_points
        + absolute_points
        + history_points
        + scarcity_points
        + confidence_points
    )))

    if score >= 80:
        label = "STÆRKT KØB"
    elif score >= 65:
        label = "GOD PRIS"
    elif score >= 50:
        label = "INTERESSANT"
    else:
        label = "NORMAL"

    return {
        "score": score,
        "label": label,
        "saving_dkk": round(saving_dkk, 2),
        "saving_pct": round(saving_pct, 1),
        "next_price": next_price,
        "shop_count": shop_count,
        "historical_low": historical_low,
        "historical_diff_pct": None if historical_diff_pct is None else round(historical_diff_pct, 1),
        "components": {
            "relative_price_edge": round(relative_points, 1),
            "absolute_saving": round(absolute_points, 1),
            "historical_position": round(history_points, 1),
            "scarcity": round(scarcity_points, 1),
            "confidence": round(confidence_points, 1),
        },
    }


def opportunity_score_icon(score):
    if score >= 80:
        return "🔥"
    if score >= 65:
        return "✅"
    if score >= 50:
        return "👀"
    return "•"
'''

replace_once(
    '''def build_price_watch_groups(candidates):
''',
    v40_helpers + '''\n\ndef build_price_watch_groups(candidates):\n''',
    "V40 helper insertion",
)

replace_once(
    '''def send_price_watch_change(
    product_key,
    old_entry,
    products
):
''',
    '''def send_price_watch_change(
    product_key,
    old_entry,
    products,
    history_state=None
):
''',
    "price change signature",
)

replace_once(
    '''    link_line = (
        f"\\n🔗 {best['url']}"
        if best.get("url")
        else ""
    )

    send_price_watch(
''',
    '''    opportunity = calculate_opportunity_score(
        product_key,
        products,
        history_state=history_state,
    )
    score_line = (
        f"\\n🎯 {opportunity_score_icon(opportunity['score'])} "
        f"**{opportunity['score']}/100 · {opportunity['label']}**"
    )

    link_line = (
        f"\\n🔗 {best['url']}"
        if best.get("url")
        else ""
    )

    send_price_watch(
''',
    "price change opportunity calculation",
)

replace_once(
    '''        + "\\n".join(ranking_lines)
        + link_line
    )
''',
    '''        + "\\n".join(ranking_lines)
        + score_line
        + link_line
    )
''',
    "price change opportunity display",
)

replace_once(
    '''def send_price_watch_daily_summary(
    comparable_groups,
    now_local
):
''',
    '''def send_price_watch_daily_summary(
    comparable_groups,
    now_local,
    history_state=None
):
''',
    "daily summary signature",
)

replace_once(
    '''        signals_by_game[game].append({
            "product_key": product_key,
            "best": best,
            "shops": price_watch_lowest_shops(products),
            "next_price": next_price,
            "saving_dkk": saving_dkk,
            "saving_pct": saving_pct,
        })
''',
    '''        opportunity = calculate_opportunity_score(
            product_key,
            products,
            history_state=history_state,
        )
        signals_by_game[game].append({
            "product_key": product_key,
            "best": best,
            "shops": price_watch_lowest_shops(products),
            "next_price": next_price,
            "saving_dkk": saving_dkk,
            "saving_pct": saving_pct,
            "opportunity": opportunity,
        })
''',
    "daily opportunity row",
)

replace_once(
    '''        signals = sorted(
            signals_by_game[game],
            key=lambda row: (row["saving_pct"], row["saving_dkk"]),
            reverse=True,
        )[:PRICE_WATCH_DAILY_MAX_SIGNALS_PER_GAME]
''',
    '''        signals = sorted(
            signals_by_game[game],
            key=lambda row: (
                row["opportunity"]["score"],
                row["saving_pct"],
                row["saving_dkk"],
            ),
            reverse=True,
        )[:PRICE_WATCH_DAILY_MAX_SIGNALS_PER_GAME]
''',
    "daily sort by opportunity",
)

replace_once(
    '''            lines.append(
                f"{index}. **{price_watch_display_name(signal['product_key'])} · "
                f"{price_watch_type_label(info['type'])}** — "
                f"{format_price(signal['best']['price'])} hos {shops} · "
                f"næste {format_price(signal['next_price'])} · "
                f"spar **{signal['saving_pct']:.0f}%**"
            )
''',
    '''            opportunity = signal["opportunity"]
            lines.append(
                f"{index}. {opportunity_score_icon(opportunity['score'])} "
                f"**{opportunity['score']}/100 · "
                f"{price_watch_display_name(signal['product_key'])} · "
                f"{price_watch_type_label(info['type'])}** — "
                f"{format_price(signal['best']['price'])} hos {shops} · "
                f"næste {format_price(signal['next_price'])} · "
                f"spar **{signal['saving_pct']:.0f}%**"
            )
''',
    "daily opportunity display",
)

replace_once(
    '''def process_price_watch(
    old_price_watch_state,
    current_state,
    fresh_sources
):
''',
    '''def process_price_watch(
    old_price_watch_state,
    current_state,
    fresh_sources,
    history_state=None
):
''',
    "process price watch signature",
)

replace_once(
    '''    comparable_groups = build_price_watch_groups(
        candidates
    )

    source_observations = build_price_watch_source_observations(
''',
    '''    comparable_groups = build_price_watch_groups(
        candidates
    )

    matching_audit = build_price_matching_audit(
        candidates,
        comparable_groups,
    )
    save_price_matching_audit(matching_audit)

    opportunity_by_key = {
        product_key: calculate_opportunity_score(
            product_key,
            products,
            history_state=history_state,
        )
        for product_key, products in comparable_groups.items()
    }
    top_opportunities = sorted(
        opportunity_by_key.items(),
        key=lambda row: row[1]["score"],
        reverse=True,
    )[:5]
    if top_opportunities:
        print(
            "OPPORTUNITY SCORE V1: "
            + " | ".join(
                f"{price_watch_display_name(product_key)} {score['score']}/100"
                for product_key, score in top_opportunities
            )
        )

    source_observations = build_price_watch_source_observations(
''',
    "audit and score generation",
)

replace_once(
    '''        f"PRICE WATCH V4: "
''',
    '''        f"PRICE WATCH V5: "
''',
    "V5 log label",
)

replace_once(
    '''        daily_sent = send_price_watch_daily_summary(
            comparable_groups,
            now_local
        )
''',
    '''        daily_sent = send_price_watch_daily_summary(
            comparable_groups,
            now_local,
            history_state=history_state,
        )
''',
    "daily history pass-through",
)

replace_once(
    '''    def confirmed_entry(product_key, best, current_best, current_shops, current_sources):
        return {
            "current_best": current_best,
            "current_shop": best["shop"],
            "current_shops": current_shops,
            "current_sources": current_sources,
            "name": price_watch_display_name(product_key),
            "last_seen": now_local.isoformat()
        }
''',
    '''    def confirmed_entry(product_key, best, current_best, current_shops, current_sources):
        opportunity = opportunity_by_key.get(product_key) or {}
        return {
            "current_best": current_best,
            "current_shop": best["shop"],
            "current_shops": current_shops,
            "current_sources": current_sources,
            "name": price_watch_display_name(product_key),
            "opportunity_score": safe_int(opportunity.get("score"), 0),
            "opportunity_label": opportunity.get("label") or "NORMAL",
            "opportunity": opportunity,
            "last_seen": now_local.isoformat()
        }
''',
    "persist opportunity score",
)

text = text.replace(
    '''send_price_watch_change(product_key, old_entry, products)''',
    '''send_price_watch_change(
                    product_key,
                    old_entry,
                    products,
                    history_state=history_state,
                )'''
)

replace_once(
    '''    return {
        "version": 4,
        "products": next_products,
        "last_daily_date": last_daily_date
    }
''',
    '''    return {
        "version": 5,
        "products": next_products,
        "last_daily_date": last_daily_date,
        "matching_audit": matching_audit,
    }
''',
    "V5 state return",
)

replace_once(
    '''        new_state["price_watch"] = process_price_watch(
            state.get("price_watch"),
            price_watch_current_state,
            price_watch_fresh_sources
        )
''',
    '''        new_state["price_watch"] = process_price_watch(
            state.get("price_watch"),
            price_watch_current_state,
            price_watch_fresh_sources,
            history_state=state.get("price_history"),
        )
''',
    "main history pass-through",
)

PATH.write_text(text, encoding="utf-8")
print("Applied V40: matching audit + opportunity score V1")
