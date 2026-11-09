"""Read-only Tradera auction scanner for the 144 missing Cardshow entries.

Run only on demand in its separate GitHub workflow. Source snapshot is immutable,
matching and titles remain candidate-level; this never recommends buying.
"""
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from tradera_ruby_match_manual import get, active, title, seller, listing_pricing, safe_url

SOURCE = Path("tradera_cardshow_missing_20261109.json")
OUTPUT = Path("tradera_cardshow_auction_results.json")
TOTALS = {"Base": 102, "Jungle": 64, "Fossil": 62,
          "Ruby": 109, "Sandstorm": 100, "Dragon": 100}
MARKERS = {
    "Base": ("base set", "pokemon base", "pokémon base"),
    "Jungle": ("jungle",),
    "Fossil": ("fossil",),
    "Ruby": ("ruby sapphire", "ruby & sapphire", "ex ruby", "ruby and sapphire"),
    "Sandstorm": ("sandstorm",),
    "Dragon": ("ex dragon", "pokemon dragon 2003", "pokemon dragon 2003"),
}
DISCOVERY = (
    "pokemon base set", "pokemon jungle", "pokemon fossil",
    "pokemon ex ruby sapphire", "pokemon sandstorm", "pokemon ex dragon",
    "pokemon vintage cards", "pokemon gamla kort",
)
MAX_DETAILS = 320
MAX_SELLERS = 25

def normalized(value):
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    return re.sub(r"\s+", " ", "".join(ch for ch in value
                  if not unicodedata.combining(ch))).strip()

def phrase(text, word):
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(normalized(word)) +
                          r"(?![a-z0-9])", text))

def is_excluded(text, card):
    bad = ("proxy", "orica", "fake", "replica", "reprint", "booster", "sealed",
           "celebrations", "classic collection", "25th", "base set 2",
           "psa ", "cgc ", "bgs ", "graded", "japanese", "japanska", "german",
           "tyska", "deutsch", "french", "franska", "italian", "italiano",
           "spanish", "spanska", "korean", "world championship")
    if any(x in text for x in bad):
        return True
    if any(x in text for x in ("reverse", "revers", "1st edition",
                              "first edition", "1st ed", "shadowless")):
        return True
    if "holo" in card["rarity"].lower() and ("non holo" in text or "non-holo" in text):
        return True
    if "holo" not in card["rarity"].lower() and ("holo" in text and
              not any(x in text for x in ("non-holo", "non holo"))):
        return True
    return False

def matches(headline, cards):
    text = normalized(headline)
    hits = []
    for c in cards:
        if not phrase(text, c["name"]) or is_excluded(text, c):
            continue
        set_explicit = any(x in text for x in MARKERS[c["set"]])
        num = c["number"]
        total = TOTALS[c["set"]]
        numbered = bool(re.search(
            r"(?<!\d)0*" + str(num) + r"\s*/\s*" + str(total) + r"(?!\d)", text))
        # If an explicit card number / set total is present but not the expected
        # one, reject, rather than misidentifying a same-name card.
        all_codes = re.findall(r"(?<!\d)(\d{1,3})\s*/\s*(\d{2,3})(?!\d)", text)
        if all_codes and (str(num),str(total)) not in [
               (str(int(a)),str(int(b))) for a,b in all_codes]:
            continue
        if not (set_explicit or numbered):
            continue
        confidence = ("set_and_number" if set_explicit and numbered else
                      "set_only_review_number" if set_explicit else
                      "number_only_review_set")
        hits.append({"set":c["set"],"number":num,"name":c["name"],
                     "confidence":confidence, "priority":c["priority"],
                     "rarity":c["rarity"], "wanted":c["wanted"],
                     "status":c["status"]})
    # /100 without set context can be EX Dragon OR Sandstorm.
    return hits

def main():
    cards=json.loads(SOURCE.read_text(encoding="utf8"))["missing_items"]
    if len(cards)!=144 or not all(x["set"] in TOTALS for x in cards):
        raise ValueError("Cardshow snapshot is not the expected 144-card set")
    app=os.environ.get("TRADERA_APP_ID","").strip()
    key=os.environ.get("TRADERA_APP_KEY","").strip()
    if not app or not key:
        raise ValueError("Tradera API credentials missing from Actions secrets")
    session=requests.Session()
    session.headers.update({"X-App-Id":app,"X-App-Key":key,
                            "Accept":"application/json"})
    issues=Counter()
    discovered={}
    queries=list(DISCOVERY)
    # Query exact number and set size for each *current* missing card.
    queries += [f"{x['name']} {x['number']}/{TOTALS[x['set']]}" for x in cards]
    # Add set-qualified searches without numbers to find loosely titled listings.
    queries += [f"{x['name']} {x['set'] if x['set'] not in ('Ruby','Dragon') else ('ruby sapphire' if x['set']=='Ruby' else 'ex dragon')}"
                for x in cards if x["priority"]=="complete_set" and "holo" in x["rarity"].lower()]
    queries=list(dict.fromkeys(queries))
    checked_queries=0
    for query in queries:
        data,err=get(session,"search",{"query":query,"pageNumber":0})
        checked_queries+=1
        if err:
            issues["search_"+err]+=1
            continue
        rows=data.get("items") if isinstance(data,dict) else None
        if not isinstance(rows,list):
            issues["search_bad_schema"]+=1
            continue
        for row in rows:
            if not isinstance(row,dict):
                continue
            uid=str(row.get("id") or row.get("itemId") or "")
            if uid.isdigit() and matches(title(row),cards):
                discovered[uid]=row
    ads={}
    detail_checks=0
    def inspect(row,source):
        nonlocal detail_checks
        uid=str(row.get("id") or row.get("itemId") or "")
        if not uid.isdigit() or uid in ads or detail_checks>=MAX_DETAILS:
            return
        if not matches(title(row),cards):
            return
        detail_checks+=1
        data,err=get(session,"items/"+uid)
        if err or not isinstance(data,dict):
            issues["detail_"+(err or "schema")]+=1
            return
        if not active(data):
            issues["closed_or_not_verified"]+=1
            return
        pricing=listing_pricing(data)
        if pricing["listing_type"] not in ("Ren auktion","Auktion + Køb nu"):
            issues["not_auction"]+=1
            return
        hits=matches(title(data),cards)
        if not hits:
            issues["detail_no_match"]+=1
            return
        url=safe_url(data.get("itemUrl") or row.get("itemUrl") or row.get("url"))
        if not url:
            issues["missing_url"]+=1
            return
        alias,sid=seller(data,row)
        ads[uid]={"id":uid,"seller":alias,"seller_id":sid,
                  "title":title(data)[:280],"url":url,
                  "type":pricing["listing_type"],
                  "bid_sek":pricing["auction_bid_sek"],
                  "buy_now_sek":pricing["buy_now_sek"],
                  "bid_count":pricing["bid_count"],
                  "end":data.get("endDate"),"cards":hits,
                  "source":source, "language":"not verified",
                  "condition":"not verified",
                  "shipping_to_denmark":"not verified"}
    # Allocate details across all six sets, rather than stopping after the
    # Base Set results. Reserve remaining detail budget for seller expansion.
    pools={set_name:[] for set_name in TOTALS}
    for row in discovered.values():
        row_hits=matches(title(row),cards)
        if not row_hits:
            continue
        set_name=next((h["set"] for h in row_hits
                       if h["priority"]=="complete_set"),row_hits[0]["set"])
        pools[set_name].append(row)
    for set_name,arr in pools.items():
        arr.sort(key=lambda row:(
            not any(h["confidence"]=="set_and_number"
                    for h in matches(title(row),cards)),
            -len(matches(title(row),cards))))
    initial_quotas={"Base":65,"Jungle":32,"Fossil":32,
                    "Ruby":25,"Sandstorm":24,"Dragon":22}
    selected=[]
    added=set()
    for set_name,quota in initial_quotas.items():
        for row in pools[set_name][:quota]:
            uid=str(row.get("id") or row.get("itemId") or "")
            if uid not in added:
                selected.append(row)
                added.add(uid)
    # Fill unused quotas round-robin by all remaining set pools.
    if len(selected)<200:
        remaining={s:[r for r in rows if str(r.get("id") or r.get("itemId") or "") not in added]
                   for s,rows in pools.items()}
        while len(selected)<200 and any(remaining.values()):
            for set_name in TOTALS:
                if remaining[set_name]:
                    row=remaining[set_name].pop(0)
                    uid=str(row.get("id") or row.get("itemId") or "")
                    if uid not in added:
                        selected.append(row)
                        added.add(uid)
                    if len(selected)>=200:
                        break
    for row in selected:
        inspect(row,"balanced_card_search")
    # Expand the sellers of matched auctions, maximizing multi-card opportunities.
    grouped_before=defaultdict(set)
    for a in ads.values():
        if a["seller_id"]:
            grouped_before[a["seller_id"]].update(
                (x["set"],x["number"]) for x in a["cards"])
    expanded=0
    for sid in sorted(grouped_before,key=lambda s:-len(grouped_before[s]))[:MAX_SELLERS]:
        response,err=get(session,"items/seller/"+sid)
        if err:
            issues["seller_"+err]+=1
            continue
        rows=response if isinstance(response,list) else (
             response.get("items") if isinstance(response,dict) else None)
        if not isinstance(rows,list):
            issues["seller_bad_schema"]+=1
            continue
        expanded+=1
        for row in rows[:250]:
            if isinstance(row,dict):
                inspect(row,"seller_inventory")
    sellers=defaultdict(list)
    for ad in ads.values():
        sellers[ad["seller_id"] or ad["seller"]].append(ad)
    rankings=[]
    for sid,arr in sellers.items():
        unique={(c["set"],c["number"],c["name"]) for a in arr for c in a["cards"]}
        strong={(c["set"],c["number"],c["name"]) for a in arr
                for c in a["cards"] if c["confidence"]=="set_and_number"}
        core={(c["set"],c["number"],c["name"]) for a in arr for c in a["cards"]
              if c["priority"]=="complete_set"}
        rankings.append({"seller":arr[0]["seller"],"seller_id":arr[0]["seller_id"],
                         "auction_count":len(arr),
                         "distinct_card_candidates":len(unique),
                         "exact_title_matches":len(strong),
                         "complete_set_candidates":len(core),
                         "cards":[{"set":s,"number":n,"name":name}
                                  for s,n,name in sorted(unique)],
                         "item_ids":[a["id"] for a in arr]})
    rankings.sort(key=lambda x:(-x["complete_set_candidates"],
                -x["exact_title_matches"],-x["distinct_card_candidates"],
                -x["auction_count"],x["seller"]))
    report={"checked_at":datetime.now(timezone.utc).isoformat(),
            "source_sheet":"Pokémon Cardshow – Mobil tjekliste",
            "snapshot_entries":len(cards),"queries_attempted":checked_queries,
            "initial_search_candidates":len(discovered),
            "details_checked":detail_checks,"active_auctions":len(ads),
            "sellers_with_auctions":len(rankings),
            "sellers_expanded":expanded,
            "sellers_with_multiple_distinct_candidates":sum(
                 x["distinct_card_candidates"]>=2 for x in rankings),
            "diagnostics":dict(issues),
            "seller_rankings":rankings,
            "auctions":sorted(ads.values(),key=lambda a:(
                 a["type"]!="Ren auktion",a["bid_sek"] or 999999)),
            "caveats":["Title matches are leads, not verified identities",
                       "English language, condition, authenticity and shipping unverified",
                       "No buy/bid actions, no Discord messages or changes to scanners",
                       "No recommendation without all-in price and comparison"]}
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    for label in ("checked_at","snapshot_entries","queries_attempted",
                  "initial_search_candidates","details_checked","active_auctions",
                  "sellers_with_auctions","sellers_expanded",
                  "sellers_with_multiple_distinct_candidates","diagnostics"):
        print(label+":",json.dumps(report[label],ensure_ascii=False))
    for item in rankings[:20]:
        print("SELLER",json.dumps(item,ensure_ascii=False))
    for ad in report["auctions"][:45]:
        print("AUCTION",json.dumps({
            k:ad[k] for k in ("id","seller","title","url","type","bid_sek","end","cards")
        },ensure_ascii=False))
    summary=os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary,"a",encoding="utf8") as out:
            out.write("## Tradera Cardshow read-only auction scan\n\n")
            out.write(f"{len(cards)} missing entries · {len(ads)} active auction candidates · {len(rankings)} sellers\n\n")
            out.write("| Seller | Distinct cards | Base/Jungle/Fossil | Exact title matches | Auctions |\n")
            out.write("|---|---:|---:|---:|---:|\n")
            for item in rankings[:20]:
                out.write(f"| {item['seller'].replace('|','/')} | {item['distinct_card_candidates']} | "
                          f"{item['complete_set_candidates']} | {item['exact_title_matches']} | "
                          f"{item['auction_count']} |\n")

if __name__=="__main__":
    main()
