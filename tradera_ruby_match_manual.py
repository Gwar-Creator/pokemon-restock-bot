"""Read-only: match active Tradera listings to EX Ruby & Sapphire missing cards."""
import json, os, re, unicodedata
from collections import defaultdict, Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, urlunsplit
import requests

CARDS = [{"num":16,"name":"Breloom","trend_eur":1.27,"rarity":"Rare"},{"num":17,"name":"Donphan","trend_eur":0.52,"rarity":"Rare"},{"num":33,"name":"Hariyama","trend_eur":0.68,"rarity":"Uncommon"},{"num":44,"name":"Skitty","trend_eur":2.56,"rarity":"Uncommon"},{"num":84,"name":"Lum Berry","trend_eur":0.29,"rarity":"Uncommon"},{"num":88,"name":"PokéNav","trend_eur":0.2,"rarity":"Uncommon"},{"num":93,"name":"Darkness Energy","trend_eur":0.93,"rarity":"Special Energy"},{"num":94,"name":"Metal Energy","trend_eur":0.7,"rarity":"Special Energy"},{"num":95,"name":"Rainbow Energy","trend_eur":0.77,"rarity":"Special Energy"},{"num":109,"name":"Lightning Energy","trend_eur":0.2,"rarity":"Energy"},{"num":1,"name":"Aggron","trend_eur":21.43,"rarity":"Rare Holo"},{"num":2,"name":"Beautifly","trend_eur":12.84,"rarity":"Rare Holo"},{"num":3,"name":"Blaziken","trend_eur":26.53,"rarity":"Rare Holo"},{"num":4,"name":"Camerupt","trend_eur":9,"rarity":"Rare Holo"},{"num":5,"name":"Delcatty","trend_eur":7.38,"rarity":"Rare Holo"},{"num":7,"name":"Gardevoir","trend_eur":16.6,"rarity":"Rare Holo"},{"num":8,"name":"Hariyama","trend_eur":11.57,"rarity":"Rare Holo"},{"num":9,"name":"Manectric","trend_eur":13.4,"rarity":"Rare Holo"},{"num":10,"name":"Mightyena","trend_eur":41.02,"rarity":"Rare Holo"},{"num":11,"name":"Sceptile","trend_eur":40.07,"rarity":"Rare Holo"},{"num":12,"name":"Slaking","trend_eur":14.06,"rarity":"Rare Holo"},{"num":14,"name":"Wailord","trend_eur":25.17,"rarity":"Rare Holo"},{"num":96,"name":"Chansey ex","trend_eur":37.39,"rarity":"Rare Holo ex"},{"num":97,"name":"Electabuzz ex","trend_eur":43.57,"rarity":"Rare Holo ex"},{"num":98,"name":"Hitmonchan ex","trend_eur":63.23,"rarity":"Rare Holo ex"},{"num":99,"name":"Lapras ex","trend_eur":120.14,"rarity":"Rare Holo ex"},{"num":100,"name":"Magmar ex","trend_eur":55.47,"rarity":"Rare Holo ex"},{"num":101,"name":"Mewtwo ex","trend_eur":374.34,"rarity":"Rare Holo ex"},{"num":102,"name":"Scyther ex","trend_eur":56.93,"rarity":"Rare Holo ex"},{"num":103,"name":"Sneasel ex","trend_eur":116.17,"rarity":"Rare Holo ex"}]
BASE = "https://api.tradera.com/v4/"
SEARCHES = ["pokemon ruby sapphire", "pokemon ex ruby", "ruby sapphire pokemon"] + [
    f"{c['name']} {c['num']}/109" for c in CARDS]
MAX_DETAILS = 400

def norm(s):
    return "".join(c for c in unicodedata.normalize("NFKD", str(s or "").lower())
                   if not unicodedata.combining(c))

def name_match(t, name):
    return re.search(r"(?<![a-z0-9])"+re.escape(norm(name))+r"(?![a-z0-9])", t) is not None

def matched(title):
    t = norm(title)
    forbidden = ("reverse","revers","non-holo","non holo","deck exclusive",
                 "world championship","world champ","team rocket returns","rocket\'s ",
                 "spanish","spanska","spansk",
                 "japanese","japanska","jp ","/055","german","tyska",
                 "french","franska","italian","korean","proxy","orica","fake",
                 "booster","sealed","psa ","cgc ","bgs ")
    if any(s in t for s in forbidden): return []
    nums = {int(x) for x in re.findall(r"(?<!\d)(\d{1,3})\s*/\s*109(?!\d)",t)}
    nums.update(int(x) for x in re.findall(r"#\s*0?(\d{1,3})(?!\d)",t))
    set_explicit = "ruby" in t and "sapphire" in t
    hits = []
    for card in CARDS:
        if not name_match(t,card["name"]): continue
        if nums and card["num"] not in nums: continue
        if card["num"] in nums:
            confidence = "exact_set_number" if set_explicit else "number_only_check_set"
        elif set_explicit:
            confidence = "set_only_check_number"
        else: continue
        if confidence == "exact_set_number":
            hits.append(dict(card, confidence=confidence))
    return hits

def safe_url(value):
    if not isinstance(value,str): return ""
    try:
        p=urlsplit(value); host=(p.hostname or "").lower()
        if p.scheme not in ("http","https") or not (host=="tradera.com" or host.endswith(".tradera.com")):
            return ""
        if p.username or p.password or p.port or not p.path: return ""
        return urlunsplit(("https",p.netloc,p.path,p.query,""))
    except ValueError: return ""

def get(s,path,params=None):
    try:
        response=s.get(BASE+path,params=params,timeout=20)
        if response.status_code!=200: return None,"HTTP_"+str(response.status_code)
        return response.json(),None
    except (requests.RequestException,ValueError): return None,"BAD_HTTP_OR_JSON"

def active(d):
    if not isinstance(d,dict) or not isinstance(d.get("status"),dict): return False
    if d["status"].get("ended") is not False: return False
    try:
        t=datetime.fromisoformat(d["endDate"].replace("Z","+00:00"))
        if not t.tzinfo: t=t.replace(tzinfo=ZoneInfo("Europe/Stockholm"))
        return t.astimezone(timezone.utc)>datetime.now(timezone.utc)
    except (KeyError,TypeError,ValueError): return False

def title(d):
    return str(d.get("shortDescription") or d.get("title") or d.get("name") or "")

def seller(d,row):
    person=d.get("seller") if isinstance(d.get("seller"),dict) else {}
    alias=d.get("sellerAlias") or person.get("alias") or row.get("sellerAlias") or "Ukendt sælger"
    sid=d.get("sellerId") or person.get("id") or person.get("userId") or row.get("sellerId")
    return str(alias),str(sid) if sid is not None and str(sid).isdigit() else None

def positive_price(raw):
    try:
        value=float(raw)
        return round(value,2) if 0 < value < 1000000 else None
    except (TypeError, ValueError):
        return None

def listing_pricing(d):
    """Separate item format from prices; nextBid is NOT evidence of an auction."""
    kind=d.get("itemType")
    buy=positive_price(d.get("buyItNowPrice"))
    bid=positive_price(d.get("nextBid")) or positive_price(d.get("openingBid"))
    if kind == 1:
        listing_type="Auktion + Køb nu" if buy else "Ren auktion"
        display=bid
        label="Næste bud/startbud" if bid is not None else "Ingen budpris"
    elif kind == 3:
        listing_type="Fast pris"
        display=buy
        label="Fast pris"
    elif kind == 4:
        listing_type="Butik / fast pris"
        display=buy
        label="Butikspris"
    else:
        listing_type="Ukendt format"
        display=None
        label="Ukendt"
    return {
        "item_type_raw":kind,
        "listing_type":listing_type,
        "auction_bid_sek":bid if kind == 1 else None,
        "buy_now_sek":buy if kind in (1,3,4) else None,
        "display_price_sek":display,
        "display_price_label":label,
        "bid_count":d.get("totalBids") if isinstance(d.get("totalBids"),int) else None
    }

def main():
    app=os.environ.get("TRADERA_APP_ID","").strip()
    key=os.environ.get("TRADERA_APP_KEY","").strip()
    if not app or not key: raise SystemExit("Tradera credentials not configured")
    session=requests.Session()
    session.headers.update({"X-App-Id":app,"X-App-Key":key,"Accept":"application/json"})
    issues=Counter(); seen={}; page_calls=0
    for query in dict.fromkeys(SEARCHES):
        for page in range(2):
            v,err=get(session,"search",{"query":query,"pageNumber":page})
            page_calls+=1
            if err or not isinstance(v,dict) or not isinstance(v.get("items"),list):
                issues["search_"+(err or "schema")]+=1; break
            rows=v["items"]
            for row in rows:
                if isinstance(row,dict) and matched(title(row)):
                    key=str(row.get("id") or row.get("itemId") or "")
                    if key.isdigit(): seen[key]=row
            if page+1>=min(2,int(v.get("totalNumberOfPages") or 1)): break

    ads={}; details_count=0
    def check(row,source):
        nonlocal details_count
        uid=str(row.get("id") or row.get("itemId") or "")
        if not uid.isdigit() or uid in ads or details_count>=MAX_DETAILS: return
        if not matched(title(row)): return
        details_count+=1
        d,err=get(session,"items/"+uid)
        if err: issues["detail_"+err]+=1; return
        if not active(d): issues["inactive_or_unverified"]+=1; return
        hits=matched(title(d))
        if not hits: issues["no_detail_match"]+=1; return
        link=safe_url(d.get("itemUrl") or row.get("itemUrl") or row.get("url"))
        if not link: issues["missing_url"]+=1; return
        alias,sid=seller(d,row)
        pricing=listing_pricing(d)
        ads[uid]={
            "id":uid,"title":title(d),"url":link,"seller":alias,"seller_id":sid,
            **pricing,"end_date":d.get("endDate"),
            "language":"English stated" if ("english" in norm(title(d)) or "engelsk" in norm(title(d))) else "Not confirmed",
            "matched_cards":hits,"source":source
        }
    for row in seen.values(): check(row,"card_search")
    sellers={a["seller_id"] for a in ads.values() if a["seller_id"]}
    expanded=0
    for sid in list(sellers)[:12]:
        v,err=get(session,"items/seller/"+sid)
        if err: issues["seller_"+err]+=1; continue
        records=v if isinstance(v,list) else v.get("items") if isinstance(v,dict) else None
        if not isinstance(records,list): issues["seller_schema"]+=1; continue
        expanded+=1
        for row in records[:250]:
            if isinstance(row,dict) and matched(title(row)): check(row,"seller_inventory")
    grouped=defaultdict(list)
    for ad in ads.values(): grouped[ad["seller"]].append(ad)
    ranking=[]
    for alias,items in grouped.items():
        distinct={(x["num"],x["name"]) for it in items for x in it["matched_cards"]}
        strict={(x["num"],x["name"]) for it in items for x in it["matched_cards"] if x["confidence"]=="exact_set_number"}
        pure=[a for a in items if a["listing_type"]=="Ren auktion"]
        mix=[a for a in items if a["listing_type"]=="Auktion + Køb nu"]
        fixed=[a for a in items if a["listing_type"] in ("Fast pris","Butik / fast pris")]
        auction_cards={(c["num"],c["name"]) for a in pure for c in a["matched_cards"]}
        holo_auction_cards={(c["num"],c["name"]) for a in pure for c in a["matched_cards"]
                            if "Holo" in c["rarity"]}
        ranking.append({"seller":alias,"distinct_matches":len(distinct),"exact_matches":len(strict),
                        "open_listings":len(items),"pure_auctions":len(pure),
                        "pure_auction_distinct_cards":len(auction_cards),
                        "pure_auction_holo_ex_cards":len(holo_auction_cards),
                        "auction_buy_now":len(mix),"fixed_price":len(fixed),
                        "pure_auction_cards":[{"number":n,"name":nm} for n,nm in sorted(auction_cards)],
                        "cards":[{"number":n,"name":nm} for n,nm in sorted(distinct)]})
    ranking.sort(key=lambda r:(-r["pure_auction_distinct_cards"],-r["pure_auction_holo_ex_cards"],
                               -r["pure_auctions"],-r["distinct_matches"],r["seller"]))
    out={"checked_at":datetime.now(timezone.utc).isoformat(),"set":"EX Ruby & Sapphire",
         "missing":len(CARDS),"queries":len(set(SEARCHES)),"search_calls":page_calls,
         "found_candidate_ads":len(seen),"detail_calls":details_count,
         "active_ads":len(ads),"sellers_checked":expanded,"seller_rankings":ranking,
         "listing_type_counts":dict(Counter(x["listing_type"] for x in ads.values())),
         "pure_auction_holo_ex_ads":sum(x["listing_type"]=="Ren auktion" and
             any("Holo" in c["rarity"] for c in x["matched_cards"]) for x in ads.values()),
         "listings":sorted(ads.values(),key=lambda x:(
              x["listing_type"]!="Ren auktion",
              not any("Holo" in c["rarity"] for c in x["matched_cards"]),
              x["display_price_sek"] if x["display_price_sek"] is not None else 10**9)),
         "diagnostics":dict(issues),
         "caveats":["Only listings with status.ended=false and future endDate",
                    "Reverse holo excluded","Language, condition, shipping to Denmark require manual check",
                    "No bids/purchases or Discord posts; read only"]}
    with open("tradera_ruby_match_results.json","w",encoding="utf8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2)
    print("RESULT",json.dumps({k:out[k] for k in ("checked_at","missing","queries","search_calls","found_candidate_ads","detail_calls","active_ads","sellers_checked","diagnostics")},ensure_ascii=False))
    for s in ranking[:25]:
        print("SELLER",json.dumps(s,ensure_ascii=False))
    for a in out["listings"]:
        if a["listing_type"] == "Ren auktion":
            print("AUCTION",json.dumps({k:a[k] for k in ("id","seller","title","url",
                 "auction_bid_sek","end_date","matched_cards")},ensure_ascii=False))
    path=os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path,"a",encoding="utf8") as f:
            f.write("## Ruby & Sapphire - open Tradera matches\n")
            f.write(f"{len(ads)} open listings / {len(ranking)} sellers, checked live.\n\n")
            f.write(f"### Listing types: {out['listing_type_counts']}\\n\\n")
            f.write("| Seller | Pure auction cards | Holo/EX auction cards | Pure auctions | Fixed |\\n|---|---:|---:|---:|---:|\\n")
            for x in ranking[:20]:
                f.write(f"| {x['seller'].replace('|','/')} | {x['pure_auction_distinct_cards']} | {x['pure_auction_holo_ex_cards']} | {x['pure_auctions']} | {x['fixed_price']} |\\n")

if __name__=="__main__": main()
