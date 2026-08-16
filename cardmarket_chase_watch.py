import json, math, os, statistics, tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

API="https://tcg-api-production-5148.up.railway.app"
KEY=os.getenv("TCG_CARDMARKET_API_KEY","").strip()
WEBHOOK=os.getenv("CARDMARKET_WEBHOOK_URL","").strip() or os.getenv("PRICE_HISTORY_WEBHOOK_URL","").strip()
TZ=os.getenv("CARDMARKET_TIMEZONE","Europe/Copenhagen")
HOUR=int(os.getenv("CARDMARKET_DAILY_HOUR","8") or 8)
FORCE=os.getenv("CARDMARKET_FORCE_RUN","0")=="1"
STATE=Path("cardmarket_chase_state.json")
WATCH=Path("cardmarket_chase_watchlist.json")
SOURCE="https://www.tcg-cardmarket-api.com/"


def f(v):
    try:return float(v)
    except (TypeError,ValueError):return None

def pct(a,b):
    a,b=f(a),f(b)
    return None if a is None or b is None or b<=0 else (a/b-1)*100

def eur(v):
    v=f(v)
    if v is None:return "–"
    if v>=1000:return f"€{v:,.0f}".replace(",",".")
    return f"€{v:,.2f}".replace(",","X").replace(".",",").replace("X",".")

def pc(v):
    v=f(v)
    if v is None:return "–"
    return (f"{'+' if v>0.05 else ''}{v:.1f}%").replace(".",",")

def load(path,default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return default

def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

def post(embeds=None,content=None,file=None):
    if not WEBHOOK:return
    payload={"username":"MasterBot","allowed_mentions":{"parse":[]}}
    if embeds:payload["embeds"]=embeds[:10]
    if content:payload["content"]=content[:2000]
    if file:
        with open(file,"rb") as h:
            r=requests.post(WEBHOOK,data={"payload_json":json.dumps(payload,ensure_ascii=False)},files={"files[0]":(Path(file).name,h,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},timeout=45)
    else:r=requests.post(WEBHOOK,json=payload,timeout=30)
    r.raise_for_status()

def emb(title,text,color):return {"title":title[:256],"description":text[:4096] or " ","color":color}


def fetch_cards(watch):
    s=requests.Session();s.headers.update({"X-API-Key":KEY,"Accept":"application/json","User-Agent":"Pokemon-Lorcana-MasterBot/1.5"})
    out=[];used=0;remaining=None;limit=None
    for game in watch["games"]:
        for st in game["sets"]:
            ids=[str(x) for x in st["cardIds"]]
            for i in range(0,len(ids),10):
                r=s.post(API+"/cards/batch",json={"game":game["slug"],"cardIds":ids[i:i+10]},timeout=30);used+=1
                try:remaining=int(r.headers.get("X-RateLimit-Remaining",""));limit=int(r.headers.get("X-RateLimit-Limit",""))
                except Exception:pass
                if r.status_code==429:raise RuntimeError("TCG Cardmarket API rate limit ramt")
                r.raise_for_status();rows=r.json();rows=rows.get("data",rows) if isinstance(rows,dict) else rows
                for raw in rows:
                    p=raw.get("price") or {};trend=f(p.get("trend"));foil=f(p.get("foilTrend"));low=f(p.get("low"));flow=f(p.get("foilLow"))
                    mv=trend;variant="Normal"
                    if foil is not None and (mv is None or foil>mv):mv,variant=foil,"Foil"
                    if mv is None:mv=low
                    if mv is None and flow is not None:mv,variant=flow,"Foil"
                    out.append({"game":game["game"],"set":st["name"],"expansion":st["expansionId"],"id":str(raw.get("externalId")),"name":raw.get("name") or "Ukendt kort","variant":variant,"market":mv,"low":low,"trend":trend,"avg1":f(p.get("avg1")),"avg7":f(p.get("avg7")),"avg30":f(p.get("avg30")),"foilLow":flow,"foilTrend":foil,"updated":p.get("updatedAt") or ""})
    return out,used,remaining,limit


def add_history(cards,old,stamp):
    prev=old.get("cards",{}) if isinstance(old,dict) else {};nxt={};lows=[]
    for c in cards:
        k=c["game"]+"|"+c["id"];p=prev.get(k,{}) if isinstance(prev.get(k,{}),dict) else {}
        c["daily"]=pct(c["market"],p.get("market"));oldlow=f(p.get("histLow"));cur=c["low"]
        c["histLow"]=cur if oldlow is None else (min(oldlow,cur) if cur is not None else oldlow)
        c["histLowAt"]=stamp if oldlow is None or (cur is not None and cur<oldlow) else p.get("histLowAt",stamp)
        if oldlow and cur is not None and cur<=oldlow*.98 and (c["market"] or 0)>=5:lows.append({**c,"oldLow":oldlow})
        c["firstSeen"]=p.get("firstSeen",stamp);c["lastSeen"]=stamp;nxt[k]=dict(c)
    return nxt,lows


def ranked(cards):
    groups={}
    for c in cards:groups.setdefault((c["game"],c["set"]),[]).append(c)
    out=[]
    for rows in groups.values():
        rows=sorted(rows,key=lambda x:f(x["market"]) or -1,reverse=True)
        for i,c in enumerate(rows,1):out.append({**c,"rank":i})
    return out

def heat(rows):
    vals=[x for x in (pct(c["avg7"],c["avg30"]) for c in rows) if x is not None]
    return statistics.median(vals) if vals else None

def summaries(cards,game):
    sets={}
    for c in cards:
        if c["game"]==game:sets.setdefault(c["set"],[]).append(c)
    out=[]
    for name,rows in sets.items():
        top=max(rows,key=lambda x:f(x["market"]) or -1);out.append((heat(rows),name,top))
    return out

def block(c,i=None,extra=None):
    a=f"**{str(i)+'. ' if i else ''}{c['name']}**\n{c['set']}\nTrend **{eur(c['market'])}** · Low {eur(c['low'])}"
    if c["variant"]=="Foil":a+=" · Foil signal"
    if extra:a+="\n"+extra
    return a

def discord(cards,game,first,lows,used):
    col=0x5865F2 if game=="POKÉMON" else 0x9B59B6;icon="⚡" if game=="POKÉMON" else "✨";rows=[c for c in cards if c["game"]==game]
    sets=len({c["set"] for c in rows});E=[emb(f"{icon} {game.title()} · CARD MARKET WATCH",f"**{sets} sæt** · **{len(rows)} chase cards** · **{used} API requests**\n\nDiscord viser kun de vigtigste signaler. Den fulde Top 20 pr. sæt ligger i Excel.",col)]
    top=sorted(rows,key=lambda x:f(x["market"]) or -1,reverse=True)[:10];E.append(emb("🏆 Top 10 chases lige nu","\n\n".join(block(c,i) for i,c in enumerate(top,1)),col))
    hs=sorted([x for x in summaries(cards,game) if x[0] is not None],reverse=True)[:6];E.append(emb("🌡️ Set Heat","\n\n".join(f"**{i}. {name}**\n7d vs 30d median: **{pc(h)}**" for i,(h,name,_) in enumerate(hs,1)) or "Ikke nok data endnu.",0xF1C40F))
    if not first:
        move=[c for c in rows if c["daily"] is not None];up=sorted([c for c in move if c["daily"]>.05],key=lambda x:x["daily"],reverse=True)[:5];down=sorted([c for c in move if c["daily"]<-.05],key=lambda x:x["daily"])[:5]
        if up:E.append(emb("📈 Største risers siden i går","\n\n".join(block(c,i,f"Siden i går: **{pc(c['daily'])}**") for i,c in enumerate(up,1)),0x57F287))
        if down:E.append(emb("📉 Største fald siden i går","\n\n".join(block(c,i,f"Siden i går: **{pc(c['daily'])}**") for i,c in enumerate(down,1)),0xED4245))
        nl=[c for c in lows if c["game"]==game][:5]
        if nl:E.append(emb("🏷️ Nye observerede lows","\n\n".join(block(c,i,f"Low {eur(c['oldLow'])} → **{eur(c['low'])}**") for i,c in enumerate(nl,1)),0xF1C40F))
    post(embeds=E)


def workbook(cards,stamp,used,remaining):
    wb=Workbook();read=wb.active;read.title="README";read.sheet_view.showGridLines=False
    info=[("CARD MARKET WATCH","Top 20 chase tracker for Pokémon and Disney Lorcana"),("Updated",stamp),("Source",SOURCE),("API requests",used),("Rate remaining",remaining),("Selection","20 recent mainstream Pokémon sets + all 13 mainstream Lorcana booster sets"),("Method","Top 20 seeded from Cardmarket product/price-guide snapshot 2026-08-07; daily prices refresh via API and rerank inside the tracked 20."),("Set Heat","Median Avg7 vs Avg30 movement across tracked cards."),("Observed Low","Lowest API Low observed by this bot; shipping excluded."),("Limitation","Aggregate data only; no seller country/condition/sales filters.")]
    for i,(a,b) in enumerate(info,1):read.cell(i,1,a).font=Font(bold=True);read.cell(i,2,b).alignment=Alignment(wrap_text=True)
    read.column_dimensions["A"].width=22;read.column_dimensions["B"].width=100
    allr=ranked(cards)
    for game,title,color in [("POKÉMON","Pokemon Top 20","17365D"),("LORCANA","Lorcana Top 20","7030A0")]:
        ws=wb.create_sheet(title);ws.sheet_view.showGridLines=False;headers=["Rank","Set","Card","CM ID","Signal","Market €","Low €","Trend €","Avg 1d €","Avg 7d €","Avg 30d €","Foil Low €","Foil Trend €","Daily change %","Observed Low €","7d vs 30d %","Updated","Source"];ws.append(headers)
        for c in sorted([x for x in allr if x["game"]==game],key=lambda x:(x["set"],x["rank"])):ws.append([c["rank"],c["set"],c["name"],c["id"],c["variant"],c["market"],c["low"],c["trend"],c["avg1"],c["avg7"],c["avg30"],c["foilLow"],c["foilTrend"],None if c["daily"] is None else c["daily"]/100,c["histLow"],None if pct(c["avg7"],c["avg30"]) is None else pct(c["avg7"],c["avg30"])/100,c["updated"],SOURCE])
        for cell in ws[1]:cell.fill=PatternFill("solid",fgColor=color);cell.font=Font(color="FFFFFF",bold=True)
        ws.freeze_panes="A2";ws.auto_filter.ref=ws.dimensions
        for col in "FGHIJKLMO":
            for cell in ws[col][1:]:cell.number_format='€#,##0.00';cell.font=Font(color="008000")
        for col in "NP":
            for cell in ws[col][1:]:cell.number_format="0.0%"
        for column in ws.columns:ws.column_dimensions[get_column_letter(column[0].column)].width=min(52,max(10,max(len(str(c.value or "")) for c in column)+2))
        ws.column_dimensions["C"].width=52
    ov=wb.create_sheet("Set Overview");ov.append(["Game","Set","Cards","Set Heat %","Top Chase","Top Chase €"])
    for game in ("POKÉMON","LORCANA"):
        for h,name,top in sorted(summaries(allr,game),key=lambda x:x[1]):ov.append([game,name,len([c for c in allr if c["game"]==game and c["set"]==name]),None if h is None else h/100,top["name"],top["market"]])
    for cell in ov[1]:cell.fill=PatternFill("solid",fgColor="17365D");cell.font=Font(color="FFFFFF",bold=True)
    ov.freeze_panes="A2";ov.auto_filter.ref=ov.dimensions
    for c in ov["D"][1:]:c.number_format="0.0%"
    for c in ov["F"][1:]:c.number_format='€#,##0.00';c.font=Font(color="008000")
    for column in ov.columns:ov.column_dimensions[get_column_letter(column[0].column)].width=min(50,max(10,max(len(str(c.value or "")) for c in column)+2))
    p=Path(tempfile.gettempdir())/f"cardmarket_top20_{stamp[:10]}.xlsx";wb.save(p);return p,allr


def main():
    if not KEY:print("CARD MARKET: TCG_CARDMARKET_API_KEY mangler");return
    now=datetime.now(ZoneInfo(TZ));today=now.date().isoformat();old=load(STATE,{})
    if not FORCE and (now.hour<HOUR or old.get("last_run_date")==today):print("CARD MARKET: ikke tid til ny daglig kørsel");return
    watch=load(WATCH,{});planned=sum(len(s["cardIds"]) for g in watch.get("games",[]) for s in g.get("sets",[]));print(f"CARD MARKET V1: {planned} kort / {math.ceil(planned/10)} requests")
    cards,used,remaining,limit=fetch_cards(watch)
    if len(cards)<planned*.8:raise RuntimeError(f"Kun {len(cards)}/{planned} kort hentet; state gemmes ikke")
    stamp=now.isoformat();nextcards,lows=add_history(cards,old,stamp);file,allr=workbook(list(nextcards.values()),stamp,used,remaining);first=not bool(old.get("cards"))
    discord(allr,"POKÉMON",first,lows,used);discord(allr,"LORCANA",first,lows,used);post(content="📎 **Card Market Watch · fuld Excel**\nTop 20 pr. sæt med Low, Trend, 1d/7d/30d, foil-data, movers og observeret historik.",file=file)
    save(STATE,{"version":1,"last_run_date":today,"last_run_at":stamp,"requests_used":used,"rate_limit":limit,"rate_remaining":remaining,"cards":nextcards});print(f"CARD MARKET færdig: {len(cards)} kort | {used} requests | remaining={remaining}")

if __name__=="__main__":main()
