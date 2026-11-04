# AGENTS.md

## AKTIV BESLUTNING — Vintage Finder Light (29. oktober 2026)

Denne beslutning **erstatter** alle ældre krav nedenfor om kun at sende verificerede KØB/BYD i `#marketplace-deals`. Brugeren valgte eksplicit den enklere version: højst **3 UDVALGT FUND per dag / 8 per uge**, uden vurdering af kort, stand eller maksimumbud i botten.

- **Eksisterende** kanal: `#marketplace-deals`; webhooken er allerede verificeret til kanal-ID `1540094708439711904`. `vintage_marketplace_live.py` checker kanal-ID igen før enhver POST og benytter kun `MARKETPLACE_WEBHOOK_URL`. Ingen ny kanal, ingen anden webhook.
- Find gamle samlinger og vintage-lots via officiel Tradera REST v4. Ekskludér åbenlyst moderne bulk, kopier, sealed, graded og uinteressante enkeltkort. Svensk annoncetekst siger intet om kortenes sprog.
- Annoncer skal have aktuelt åbent status, mindst ét billede, læsbart offentligt link, verificerbart API-prisfelt og billed-URL. Discord viser link, billede og **næste bud/køb nu i SEK**, uden påstande om totalpris, stand, ægthed eller besparelse. **UDVALGT FUND er ikke et købsråd**.
- `.github/workflows/vintage_marketplace_live.yml` kører to gange dagligt og kan også startes manuelt. **Første kørsel er en tavs baseline**: eksisterende annoncer markeres sete uden alert. Derefter højst tre fund per kørsel og dag, otte på en uge.
- `vintage_marketplace_state_v1.json` er isoleret fra restock-/pris-/historik-state. Workflowet committer reservationen før nogen Discord-POST og stopper ved commitfejl. Ingen automatisk retry af tvivlsomme sends, bud eller køb. Støj/dubletter håndteres uden manuel kortidentifikation.
- Den gamle manuelle `vintage_lot_budget.py` og BUY/BID-kode beholdes som inaktive hjælperedskaber; de må **ikke** blokere eller påtvinges udvalgte vintage-fund. Den tidligere plan om 14 dages BUY/BID-shadow er ikke en forudsætning for denne eksplicit valgte discovery-version.


## Kendt kildebegrænsning — TCGBruus og Proshop (3. november 2026)

- **TCGBruus:** Verificeret fra GitHub Actions med samme curl_cffi Chrome-fingerprint som produktionen. Den offentlige sealed-kategori gav HTTP 200 men kun **3 unikke produktlinks**, **ingen normale WooCommerce-kort/pagination**, og priser i **USD** (ikke DKK). `?currency=DKK` hjalp ikke. Læs kun dette som et verificeret problem for GitHub-runnerens respons, ikke som en påstand om butikkens generelle danske lager.
- Hold derfor `SOURCE_MIN_PRODUCTS["tcgbruus"] = 5`; **sænk ikke til 3** for at få grøn health. Den gamle produktbaseline bevares ved fejl, og både source-health og Wave 4 skal forblive fail-closed, indtil dansk lokaliseret produkt-/lager-/prisdata er dokumenteret med en live test. Undgå at kalde cache for aktuelt lager.
- En read-only diagnose ligger i `tools/diagnostics/tcgbruus_coverage_probe.py` og kan køres manuelt via `.github/workflows/tcgbruus_coverage_probe.yml` (ingen secrets, køb, Discord eller state-mutation). Resultaterne er dokumenteret i GitHub issue **#62** og PR **#104**.
- **Proshop:** Hovedkilden viser ofte 3–5 friske kategoriprodukter mod en konservativ health-target på 6. Status **DEGRADED** er derfor tilsigtet, selvom kendte SKU'er kan verificeres separat. Supplerende detailcheck må aldrig gøre katalogdækning kunstigt grøn.
- **Proshop live-diagnose 4. november:** En read-only GitHub Actions-test af Jina Reader fandt 3 relevante TCG-produkter på `/pokemon-kort` (10 unikke rå SKU'er), 3 via søgning `?s=Pokemon+TCG`, kun 1 på generel Pokémon-brand-kategori. De alternative visninger udvider derfor ikke pålideligt katalogdækningen. Enkelte produkt-URL'er returnerer HTTP 200 **men omdirigeres til `/Pokemon/Pokemon`**. Kendt-SKU-verifikation skal afvise en forkert `Final URL`, uanset om der optræder salgs-/lagerord på den omdirigerede side. Hold fortsat status DEGRADED indtil mindst 6 faktisk friske relevante kategoriprodukter er dokumenteret. Se PR #107 og issue #62.
- P0 driftsovervågning (#62) er **delvist færdig**: kilde-audit og workflow-watchdog findes nu, men TCGBruus og Proshop har stadig kildebegrænsninger, og uafhængig ekstern heartbeat-overvågning er ikke etableret. Prisalarmer forbliver slået fra efter beslutningen 28. oktober, indtil kvaliteten er dokumenteret.

## Aktiv workflow-watchdog — 4. november 2026

- `.github/workflows/workflow_watchdog.yml` er separat fra Restock/HOT og kontrollerer hver halve time seneste **fuldførte succesfulde** GitHub Actions-kørsler via read-only API.
- Grænser: Restock senest **60 minutter**, HOT senest **75 minutter**, og Card Market Watch senest **36 timer**. For Cardmarket tæller **kun planlagte** runs (manuelle webhook-tests må ikke skjule en manglende daglig kontrol).
- `tools/workflow_watchdog.py` skriver kun én teknisk **FEJL** og én **GENOPRETTET**-kommentar per statusskifte på eksisterende GitHub-issue **#62**. Kommentarer skrevet af `github-actions[bot]` med skjult marker er den vedvarende dedupe-state. Ingen Discord-, kort- eller købssystemer røres.
- `workflow_dispatch` er **dry-run som standard**. Planlagt kørsel bruger `--notify`. Der kræves ingen nye GitHub-secrets, men workflowet skal have `actions:read` og `issues:write`.
- **Kendt begrænsning:** GitHub Actions kan selv forsinke/miste sine cron-jobs; denne selvhostede kontrol kan ikke varsle, hvis al GitHub Actions-planlægning ophører. En bruger modtager kun proaktiv besked, hvis vedkommendes GitHub-notifikationer for issue #62 er aktiveret. `SCANNER_HEALTH_WEBHOOK_URL` er hidtil tomt, og driftsfejl sendes derfor ikke til produkt-alertkanalerne.
- De tidligere kildefejl ved TCGBruus/Proshop er uafhængige af denne heartbeat og må ikke kaldes løst på baggrund af grønne workflows.

## Discord V2: sikker ordrevare-visning (4. november 2026)

- HOT Proshop `stock=BESTILLINGSVARE` betyder mulig bestilling men **ikke** dokumenteret varen på lager eller kort leveringstid. V2 viser neutral **UKENDT · PROSHOP**, feltet **BESTILLINGSVARE – IKKE LAGER-RESTOCK** og en manuel kontrolnote. Ingen grønt `KØB NU` og intet klikbart købslink på usikkert signal.
- Kun faktisk frisk `PÅ LAGER` fra Proshop kan opnå `BUY_NOW` i HOT V2, og gemt `fetch_via=preserved_previous_scan` må ikke ophøjes selv i sammensatte kilde-markører. Denne ændring ændrer ikke antal Discord-posts, den eksisterende 24-timers cooldown, lane ownership eller produktfilter.
- Øvrige Discord V2-spor er fortsat delvist gennemført. Navnlig Salling HOT-fallback og Restock/Cardmarket kræver separat kvalitetssikring. Price Watch/History Discord-alarmer er fortsat deaktiveret.

## Discord V2: Salling HOT-status (4. november 2026)

- BR/Bilka/Føtex HOT aktiverer samme `discord_alert_v2.py`-renderer som andre sikre HOT-alerts, men deres data om online- og butikssystemlager er **ikke** verificeret ordre-/reservationsmulighed. `online_count>0` og `is_exposed=True` giver derfor aldrig `BUY_NOW`. `RESERVE_NOW` kræver en særskilt, verificeret reserverbar butikstilstand; det findes ikke i HOT-kildedata.
- HOT beholder den eksisterende online-only lane-ownership, filtre, baselines, cooldowns og enkeltstående webhook-send. Forskellen er udelukkende visning: `BUTIKSLAGER` orange når positivt lokalt butikslager er identificeret, `KLARGØRES` gul ved PRE-PUBLISH, ellers `UKENDT` neutral med forklaring om online systemlager. Et HOT-event kaldet RESTOCK vises som `ONLINE LAGERSIGNAL – IKKE VERIFICERET RESTOCK`.
- Gemte `fetch_via=preserved_previous_scan`-records kan ikke bruges som friskt lokalt lager. Ved fejl i V2-rendereren eller en usikker grønt klassificeret Salling-hændelse bruges en neutral fail-closed tekst uden købslink; aldrig det grønne legacy RESTOCK-embed.
- Ingen flere Discord-POSTs, ingen nye kanaler, ingen nye produktsignaler og ingen ændring af Price Watch/History-pauser. Se issue #63 og Salling HOT PR.

## Formål

Dette repository driver en dansk Discord-scanner for Pokémon- og Lorcana-restocks, prisovervågning og Cardmarket-historik. Målet er få, relevante og troværdige notifikationer — ikke flest mulige notifikationer.

Denne fil er den varige projekthukommelse på tværs af chats. Før større ændringer skal den læses sammen med den aktuelle kode, workflowet og seneste state. Opdater kun filen, når arkitektur, faste regler, kendte risici eller væsentlige beslutninger ændrer sig.

## Kilde til sandhed

Repository: `Gwar-Creator/pokemon-restock-bot`
Produktionsgren: `main`

Vigtige filer:

- `restock_bot_github.py`: primær scanner, filtre, Discord-output, Price Watch og Price History.
- `restock_state_v2.json`: vedvarende lager-, pris-, historik- og source-health-state.
- `local_stock_watch.py`: separat lokal Salling-stock/PRE-PUBLISH overvågning.
- `hidden_stock_watch.py`: særskilt monitoring af PRE-PUBLISH Pokémon-sealed hos BR/Bilka/Føtex med direkte detail-lagerkontrol, 2 positive målinger og stille baseline.
- `hidden_stock_state_v1.json`: særskilt vedvarende state for skjult butikslager; må ikke sammenblandes med de normale restock-lagertal.
- `local_stock_state_v1.json`: vedvarende state for Local Stock Watch, når baseline er oprettet.
- `scanner_health_audit.py`: log-only audit af de aktive scannerkilder.
- `.github/workflows/restock.yml`: GitHub Actions-kørsel og commit af state.
- `cardmarket_chase_watch.py`: Cardmarket-overvågning.
- `cardmarket_v16_replay.py`: historisk replay/hjælpeværktøj, hvis filen findes.

Læs altid de live filer i GitHub. Stol ikke alene på en ældre chat, lokal kopi eller handover-fil.

## Hobbyfokus ændret 28. oktober 2026

- **Kun Pokémon er aktiv hobby og mål for MasterBot-købs-/restock-notifikationer.** Lorcana er ikke længere udviklingsprioritet.
- Eksisterende Lorcana-produkter, kilder og pris-/scannerhistorik må ikke slettes eller nulstilles. Eksisterende scannerkilder må fortsat indlæse data, så historisk state ikke migreres i dette trin.
- `send_discord` og `send_price_watch` afviser eksplicit Lorcana-notifikationer før Discord-POST og før alert-memory ændres. Daglige pris- og historikoversigter viser kun Pokémon, men bagvedliggende prisdata og CSV-historik bevares.
- Den nyudviklede Lorcana shadow price coverage-audit er stoppet; genoptag ikke Lorcana-købsalarmer uden brugerens nye beslutning. Prioritér Pokémon restocks, reprints, korrekt købbarhed og vintage/Price Watch.

## Tradera API skema verificeret (2026-10-28)

- Første faktiske `pokemon samling` REST v4-søgning lykkedes med HTTP 200; første side indeholdt 50 resultater.
- JSON envelope indeholder `items` og `errors`; produktet har bl.a. `id`, `shortDescription` og `itemUrl`. `maxBid` / `nextBid` er ikke fuld pris med fragt og må ikke kaldes god handel.
- `vintage_finder_tradera.py` er rettet efter dette reelle skema. Der er fortsat **ingen schedule, live Discord eller automatisk køb** i Vintage Finder.

## Tradera credentials og read-only API probe (2026-10-28)

- Brugeren har oprettet Tradera Developer-app og gemt `TRADERA_APP_ID` og `TRADERA_APP_KEY` i GitHub Actions secrets. Vis eller log ALDRIG deres værdier.
- `.github/workflows/tradera_probe.yml` udfører én enkelt læsebaseret REST v4-søgning ved første merge af workflow-filen, derefter kun manuelt via `workflow_dispatch`; ingen tidsplan, Discord, bud, køb, eller statefiler.
- `vintage_tradera_probe.py` logger kun ufølsomme JSON-feltnavne og længder. Hvis API-svar er ukendt, stop og undersøg responsens struktur før Vintage Finder-prototypen ændres.
- Når API-schema er verificeret fra en reel prøve, må en separat PR forbedre læsebaserede vintage-søgninger; ingen live Discord/notifikationer uden dokumenteret kvalitet.

## Eksisterende Discord-kanal: #marketplace-deals

- Brugeren har allerede oprettet `#marketplace-deals`; **opret aldrig en ny kanal til Vintage Finder**.
- Tidligere aftale (20. august 2026): Kanalen bruges **kun til handlingsklare KØB eller BYD**, aldrig WATCH, OK PRIS, MÅSKE eller almindelige annoncefund. Disse labelkrav gælder fortsat; ny kode må ikke aktivere REVIEW-output til kanalen.
- Tidligere foreslået webhook-secret-navn er `MARKETPLACE_WEBHOOK_URL`; kontrollér ved senere aktivering, om den allerede eksisterer og peger på den korrekte kanal. Opret ikke et nyt/andet navn eller brug Price Watch-/Cardmarket-webhook ved en fejl.

- `vintage_marketplace_discord.py` formatterer kun en ikke-publiceret preview for relevante Tradera-kandidater, med status **TIL GENNEMGANG**, ikke BUY eller handlingsanbefaling. Den indeholder ingen Discord-POST, scheduler, secrets eller state.
- Nye webhook-opslag skal senere sendes til den eksisterende kanal efter særskilt verifikation af den korrekte kanal/webhook. Genbrug ikke Cardmarket eller Price Watch webhook, og aktiver ikke en varselsstrøm før dokumenteret relevans og dubletbeskyttelse.
- Manuelt relevante fund er ikke nødvendigvis køb. Fragt til DK, sprog, stand, ægthed og pris holdes uverificerede indtil gennemgang.

## Verificeret marketplace-kanal (29. oktober 2026)

- **Webhook-destination er verificeret 29. oktober 2026:** GitHub Actions [run 40823401471](https://github.com/Gwar-Creator/pokemon-restock-bot/actions/runs/40823401471) sammenlignede den eksisterende `MARKETPLACE_WEBHOOK_URL` med brugerens bekræftede kanal-ID `1540094708439711904` og returnerede `VERIFIED` via read-only GET. Ingen webhook blev vist, og ingen POST blev sendt. **Vintage Finder Discord-alarmer er fortsat slået fra**, fordi uverificerede shortlist-fund ikke er KØB/BYD.

## Vintage Finder: Tradera forberedelse (28. oktober 2026)

- `vintage_finder_tradera.py` er en **ikke-planlagt, read-only prototype**, ikke en kørende bot. `VINTAGE_FINDER_PLAN.md` beskriver sikkerhedsgates.
- Tradera REST v4 søgning bruger eksisterende GitHub Actions-app-secrets, og HTTP 200/50 resultater er verificeret. Der er ingen Vintage Finder-scheduler, webhook-post eller automatiske bud/køb.
- Ingen DBA-scraping: brug DBAs indbyggede annonceagenter eller andet udtrykkeligt tilladt input. Ingen automatiske bud, sniping eller køb.
- Vintage-tekstmatch er et kvalificeret forslag til **manuel vurdering**, aldrig en påstand om korrekt kortidentitet, stand, sprog eller god pris.
- Hold brugers opmærksomhed og økonomi som prioritet: ingen køb opfordres på baggrund af uverificerede vintage-matches.

## Vintage Finder: shadow-kvalitet (28. oktober 2026)

- `vintage_tradera_quality.py` måler titelbaserede signaler fra op til seks officielle REST v4-søgninger. Kategorien TITLE_VINTAGE er kun et teksthit; TITLE_UNCERTAIN kræver mere dokumentation. Ingen af delene er en verificeret handel eller kvalificerer automatisk til Discord.
- `.github/workflows/tradera_quality.yml` kører kun ved første merge af den nye workflow-fil eller manuelt. Det er ikke en planlagt scanner; alle eksisterende restock- og historik-states er uberørte.
- Workflowet kontrollerer kun, om `MARKETPLACE_WEBHOOK_URL` er sat (ja/nej). Det bekræfter IKKE kanalen, sender aldrig en webhook og må ikke bruges som aktiveringsgodkendelse.
- Audit tæller unikke opslag, dubletter, ubrugelige links og tekstbaserede kandidater. Reelle falske positiver og præcision er ukendte, indtil et menneske har kontrolleret annonceindhold, kort, sprog, stand, sælger og dansk samlet pris.
- `actionable_signal` er en inert fail-closed berettigelseskontrol: kun KØB/BYD med dokumenteret, frisk, menneskeligt verificeret vurdering kan passere. Den er IKKE forbundet til nogen Discord-afsender; der er heller ingen automatisk budfunktion.

## Vintage Finder: udvalgte vintage-lots og webhook-verifikation

- `vintage_marketplace_shortlist.py` laver et **internt** shortlist-filter for gamle mapper/samlinger og konkrete WotC/e-reader/Gym-lots. Det kræver lot/samlingskontekst og sorterer åbenlyst moderne bulk, sealed, kopier og uønskede produkter fra. Svensk annoncetekst er IKKE et tegn på svensk kortsprog.
- `vintage_marketplace_runner.py` laver en manuel/engangs read-only Tradera-artifact med højst otte annoncer til vurdering. Det sender **ingen** Discord-beskeder, fortolker ingen billeder og laver ingen KØB/BYD-anbefalinger.
- `propose_shortlist` har separat, endnu ikke produktionsaktiveret baseline/dubletpolitik (første kørsel uden historiske alerts; max 3/run, 3/dag, 8/uge); der er ingen commit af bot-state eller live scheduler.
- `vintage_marketplace_webhook_check.py` kan med et GET-kald kontrollere den eksisterende `MARKETPLACE_WEBHOOK_URL` mod det **uafhængigt oplyste** kanal-ID i GitHub Actions-variablen `MARKETPLACE_EXPECTED_CHANNEL_ID`. Den skriver kun VERIFIED/NOT_VERIFIED, aldrig URL, token, kanalnavn eller ID. Hvis variablen ikke er opsat eller mismatch, forbliver kanalen uverificeret.
- Brugeren ønsker at få relevante notifikationer, men tidligere aftale om **kun verificerede KØB/BYD** i `#marketplace-deals` gælder fortsat. Shortlist/review må ikke postes der. Ingen webhook POST/publisher er aktiveret; budget og kortidentitet skal gennemgås separat.

## Vintage Finder: konservativt lotbudget (28. oktober 2026)

- Den officielle `GET /v4/items/{itemId}` er undersøgt sikkert for fire konkrete lots via `vintage_tradera_item_probe.py`. API'et indeholder bl.a. `longDescription`, `shippingOptions`, `seller`, `detailedImageLinks` og budfelter, men **verificerer ikke** i sig selv sprog, stand, ægthed, dansk levering eller god markedspris.
- `vintage_lot_budget.py` er en **offline, manuel, fail-closed** omkostnings-/budgetberegner. Den kræver verificeret dansk fragt, gebyrer, valutakurs, identitet, sælger, stand, billeder, EU-referencer, live pris og tilgængeligt hobbybudget, samt manuelt godkendt personligt maksimalbudget.
- Beregnet maksimumbud er udelukkende en økonomisk grænse, IKKE et KØB/BYD-signal. Modulet har ingen netværk, notifiering, automatisk køb eller state. Ufuldstændige data giver ingen maksimumbudsberegning.
- Før automatiske marketplace-alarmer kræves fortsat uafhængig webhook-kanalbekræftelse, reel kvalitetsmåling og krydskørsels-dubletbeskyttelse. Eksisterende `#marketplace-deals` må ikke modtage usikre REVIEW-fund.

## Forenkling vedtaget 28. oktober 2026: Restock først

- Brugeren vil prioritere funktioner med konkret hobbyværdi; den dyre ældre sealed/reprint-jagt er ikke et udviklingsspor.
- **Price Watch og Price History Discord-output er sat på pause** via `PRICE_WATCH_DISCORD_ENABLED=0` og `PRICE_HISTORY_DISCORD_ENABLED=0` i hovedworkflowet. Standard i scanneren er også 0. Samme moduler kan fortsat registrere prisdata og historik i eksisterende state.
- Eksisterende RESTOCK, HOT Restock, Local Stock, Early Radar og Cardmarket/Inventory Sync bevares.
- Eksisterende pris- og historikdata må ikke slettes eller nulstilles. Aktivering af Price Watch-alerts igen kræver dokumenteret nytte ud over HOT.
- Fremadrettet: afprøv vintage-fund fra Tradera kun gennem officiel read-only API og DBA gennem indbyggede annonceagenter, aldrig uautoriseret scraping eller automatisk budgivning. Vintage Finder skal først afprøves med tavs baseline og konservative signaler.

## Drift og kanaler

- Ekstern scheduler udløser normalt `.github/workflows/restock.yml` cirka hvert 5. minut.
- Workflowet scanner butikker, sender relevante Discord-events og committer ændret state tilbage til `main`.
- Restock-kanalen er til lagerændringer og nye relevante varer.
- Nye katalogprodukter sendes kun til Restock, når de aktuelt er køb-bare eller markeret som preorder. Udsolgte katalogfund bevares i state og kan senere give en reel restock.
- Scanner-health og recovery sendes kun til en separat `SCANNER_HEALTH_WEBHOOK_URL`; uden den logges hændelserne kun i workflowet.
- Price Watch er handlingsorienteret og skal være kompakt.
- Price History bevarer statistik, men Discord-output skal være let; fuld detalje hører til data/CSV.
- Price Watch og Price History sender ikke tomme daglige "ingen signaler"-beskeder.
- Card Market må aldrig falde tilbage til Price History-webhooken. Discord-output kræver en dedikeret `CARDMARKET_WEBHOOK_URL`, og fuld Excel sendes kun ugentligt.
- Webhooks, tokens og andre secrets må aldrig skrives i kode, logs, dokumentation eller commits.
- Discord-oprydning køres af `discord_cleanup.py` før hovedscannet. Den sletter
  kun ikke-fastgjorte webhook-/botopslag, der er ældre end 24 timer; pris- og
  lagerhistorik i state påvirkes ikke. Oprydning er fail-open, så scannerne
  fortsætter ved Discord-fejl.

## Overvågede kilder

Scannerens nuværende aktive kilder omfatter Coolshop, Proshop, BR, Bilka, Føtex, Boozt, Magasin, PokeHulen, Rogerz, MTGwebshop, Luckbox, Spilforsyningen, Musen & Slottet, Symbizon, CardX, Matraws, Halmes Hule, CardsDirect, Baltzer Games, TCG Shoppen, Pokemons.dk, Pocket Monster, Fun-shop, PokéPulls, Staalz, PBCards, KoCardz, Vaulted, Pokedexet, Pokemonportalen, TCGBruuS, Pokemon Plaza, Kelz0r, Faraos, Goblin Games, Hyggeonkel, Nostalgic, &Cards, Pokecards.dk, Epic Panda, Steffen-O og Next Level Games.

Elgiganten, CardstoreCPH og ZZGames er historiske/retired kilder. Deres state må gerne bevares, men de skal ikke fetches eller bruges som friske Price Watch-/Price History-kilder.

Wave 1-udvidelsen fra 2026-08-21 tilføjede Symbizon, CardX, Matraws, Halmes Hule og CardsDirect som Shopify-kilder.

Wave 2-udvidelsen fra 2026-08-21 tilføjede Baltzer Games og TCG Shoppen som Shopify-kilder samt Pokemons.dk og Pocket Monster via målrettede WooCommerce Store API-søgninger. CardstoreCPH blev kort tilføjet via en separat parser, men retired samme dag, da butikken i praksis primært består af enkeltkort og gav 0 relevante sealed produkter.

Wave 3-udvidelsen fra 2026-08-21 tilføjer Fun-shop, PokéPulls, Staalz og PBCards via Shopify samt KoCardz via målrettede WooCommerce Store API-søgninger. Fun-shop bruger kun sealed-tunge Pokémon-collections for at undgå butikkens store single-card-katalog. PBCards bruger Pokémon-kategorien plus et begrænset new-releases-feed til aktuelle Pokémon/Lorcana-produkter; sprogreglen er særlig vigtig her, fordi shoppen også fører flere ikke-engelske produkter. PokéPulls og Staalz bruger bredere Shopify-feeds med automatisk game-detection og de eksisterende sealed-/sprogfiltre.

Wave 4-udvidelsen fra 2026-08-21 tilføjede Vaulted, Pokedexet, Pokemonportalen, TCGBruuS og Pokemon Plaza med platformstilpassede feeds/parsers.

Wave 5-udvidelsen fra 2026-08-21 tilføjer Kelz0r, Faraos, Goblin Games, ZZGames og Hyggeonkel. ZZGames bruger Shopify-feed; de øvrige bruger målrettede offentlige kategori-parsers og de eksisterende sealed-/English-only-filtre. Bog & idé blev bevidst udskudt, fordi webshoppen var midlertidigt password-lukket under platformsmigrering 21/8, og Bræt & Brikker blev ikke tilføjet, fordi butikken er lukket.

ZZGames blev retired 2026-08-25 efter 975 fortløbende fejl og 0 brugbare produkter. Historisk state bevares. Kilden må først aktiveres igen, når et stabilt offentligt feed med relevante sealed produkter er dokumenteret.

Nye kilder baseline-indlæses uden historiske produkt-alerts og går derefter ind i normal restock-/Price Watch-/Price History-logik, når de er friske og sunde.

Butikslisten kan ændre sig. Koden og den seneste state er altid autoritative.

## Relevans for restock

**Aktuel sprogregel (2026-08-20): Kun engelske kortprodukter er brugerrelevante.** Produkter, der eksplicit er mærket japansk, kinesisk, koreansk, tysk, fransk, italiensk, spansk, portugisisk, hollandsk, thai eller indonesisk, må gerne bevares i rå state, men skal ikke udløse Restock-, Local Stock-, Price Watch- eller Price History-signaler. Produkter uden eksplicit sprogmærkning behandles som engelske.

Fokusér på officielle, forseglede Pokémon- og Lorcana-produkter: boosterprodukter, ETB'er, tins, officielle collections, premium collections og lignende. Nye releases, preorders, ældre eftertragtede sæt og meningsfulde lokale restocks har høj værdi.

Følgende skal som udgangspunkt ikke udløse restock-notifikationer:

- Penalhuse/pencil cases og repacks.
- Portfolios, binders, mapper, albums og løse pocket pages.
- Sleeves, deck protectors, Dragon Shield og Ultra Pro-tilbehør.
- Playmats, deck boxes, storage boxes og opbevaring.
- Toploaders, card savers/cases/displays/holders og kortbeskyttelse.
- Akryl/acrylic-produkter.
- Pokémon checklane-produkter og battle decks.
- Lorcana starter decks.
- Mega Zygarde EX Premium Collection / Bilkas tilsvarende Premium EX Box.

Vigtige undtagelser, der fortsat kan være relevante forseglede produkter:

- Binder Collection.
- Playmat Collection.
- Accessory Pouch Special Collection.
- Sleeved Booster.
- Andre officielle collection-produkter, selv hvis titlen indeholder et ord, som også bruges om tilbehør.

Filtrér helst notifikationer uden at slette produktet fra state. Det bevarer historik og gør ændringer nemme at rulle tilbage. Brug præcise regler og eksplicitte undtagelser frem for brede delstringsfiltre.

## Skjult butikslager

Fra 2026-10-20 overvåges skjulte Pokémon-produkter via `hidden_stock_watch.py` i hovedworkflowet. Salling Algolias `in_stock_stores_count=0` betyder ikke nødvendigvis, at `clickcollect/availability/{SKU}` mangler positive butikstal; BR Kolding Charizard ex Super-Premium Collection (4) og Mega Latias ex Box (1) er verificerede eksempler i den detaljerede API. Kilden er systemlager, ikke dokumentation for at varer kan købes i butikken.

Den nye lane scanner BR, Bilka og Føtex for `is_exposed=false` og `store_count=0`; almindelig Local Stock håndterer positive Algolia-lagertal separat. Skjult-lager-Discord-alarmer sendes **kun for butikker i Kolding, Esbjerg, Vejle og Fredericia** (beslutning 2026-10-20). Alle andre butikker, herunder Østerbro, Vejen og Brørup, må stadig registreres i landsdækkende state, men må ikke indgå i hidden-stock-Discord-alarmer. Filtreringen gælder både alarmkø og selve Discord-beskedens butikker. Første succesfulde butikskørsel opretter en stille baseline. Derefter kræves to på hinanden følgende positive SKU-/butiksaflæsninger til Discord; kun nye positive overgange efter nul er relevante, og maksimum er fire produktalerts per kørsel med lokal prioritet. API-fejl/tomme payloads betyder ukendt, ikke nul. Alarmer markeres tydeligt PRE-PUBLISH/ikke bekræftet salg. Den separate `br_hidden_stock_probe.py` er fortsat diagnostisk uden Discord.

## Lokalt fokus

Local Stock Watch fokuserer på Kolding, Fredericia, Vejen, Brørup og Esbjerg. Den bruger offentlige Salling-produktdata og Click & Collect availability. PRE-PUBLISH må kun bruges, når `is_exposed=false` er eksplicit; manglende/ukendt felt må ikke kaldes PRE-PUBLISH.

Den almindelige restock-scanner har fortsat eksplicit lokal dækning for Kolding og Esbjerg hos flere kæder. Udvidelser skal verificeres mod butikkernes faktiske lagerdata og må ikke gættes.

## Price Watch og historik

- Price Watch skal kun bruge aktuelt køb-bare produkter og friske, sunde kilder.
- Produkter fra en fejlet eller degraded/partiel kilde må ikke fremstå som aktuelle prisreference, medmindre datagrundlaget er fuldt nok til det.
- Prisnormalisering skal tage højde for sprog, produkttype, sæt og antal pakker.
- Cases/multi-displays må ikke sammenlignes med én normal Booster Box.
- Eksisterende pris- og Cardmarket-historik må ikke slettes, nulstilles eller migreres uden udtrykkelig godkendelse.
- Små prisbevægelser må gerne gemmes i historikken uden at blive Discord-signaler.
- Price Watch intraday skal kræve mindst 25 kr. OG 5% reel forbedring.
- Price Watch V1.5 fokuseret prisalarm anvender nu samme samtidige DKK- og procentgrænse før Discord. Mindre ændringer registreres stadig i pris-state, men sendes ikke. Denne rettelse ændrer ikke fokus-sæt, Lorcana-dækning eller prishistorik. (2026-10-28)
- Lorcana-kandidatdækning måles fra eksisterende friske Price History-kandidater via `price_watch_lorcana_shadow.py` og logges én gang pr. hovedscan (antal, kilder, formater og manglende links). Ingen Lorcana-fokusalarmer, nye Discord-opslag, price-state eller best-buy-konklusioner før datavalidering. (2026-10-28)
- Price Watch dagsoversigt må højst vise 3 Pokémon + 3 Lorcana-signaler.
- Price History Discord må højst vise 3 væsentlige signaler i alt pr. dag.
- Fuld Price History CSV sendes højst ugentligt; data beholdes løbende i state.

### Prislofter for Price Watch / Price History

Produkter over disse grænser bliver i rå restock-state og kan fortsat give restock-signaler, men skal ikke fylde Price Watch eller Price History:

- Booster Pack: 150 kr.
- Sleeved Booster: 175 kr.
- Booster Bundle: 750 kr.
- ETB: 1.500 kr.
- Booster Box: 1.750 kr.

## Discord V2 sikker udrulning (2026-10-28)

- `discord_alert_v2.py` indeholder ren renderering og seks statusser. `discord_v2_hot_adapter.py` omsætter HOT-kildedata uden at skrive state.
- HOT bruger `DISCORD_V2_HOT_MODE` med standarden `shadow`: render den nye besked diagnostisk, men send fortsat den eksisterende embed som hidtil.
- Kun `DISCORD_V2_HOT_MODE=on` skifter HOT's udsendte embed; det kræver separat vurdering af skyggeresultater og datakvalitet. Udsend aldrig to beskeder for samme event.
- Systemlager, PRE-PUBLISH og modstridende status må aldrig ophøjes til bekræftet købbarhed. `BESTILLINGSVARE` skal fremstå tydeligt som ordrevare, ikke garanteret øjeblikkelig levering.
- Local Stock, Hidden Stock og Salling Early Radar anvender `discord_v2_salling_adapter.py` til **shadow-only** klassifikation i loggen ved udsendte legacy-alerts. Ingen ekstra Discord-posts, ændret event-dedupe eller state. Positivt butikslager er `STORE_STOCK`, skjult produkt `PREPUBLISH`; Early Radar kan ikke udlede bekræftet købbarhed af katalog-/systemlagertal.
- Kontrolleret Discord V2-præsentation aktiveres fra workflowet via tre uafhængige flags: `DISCORD_V2_LOCAL_MODE=on`, `DISCORD_V2_HIDDEN_MODE=on` og `DISCORD_V2_EARLY_MODE=on`. Hver af disse erstatter kun formatteringen af en allerede godkendt alert og sender fortsat præcis ét opslag. Ved klassifikationsfejl bruges legacy.
- HOT bruger `DISCORD_V2_HOT_MODE=on`, men sender kun V2 ved frisk, eksplicit onlinekøb hos Coolshop eller `PÅ LAGER` hos Proshop (ikke cachede varer). Proshop `BESTILLINGSVARE` bruger nu V2 med neutral **UKENDT** status og tydelig ordrevare-note (aldrig grøn `KØB NU` eller et bekræftet lager-restock); det ændrer **kun visning** og ikke HOT event-gates/dublet-cooldown. BR/Bilka/Føtex HOT-events bruger nu V2 med **BUTIKSLAGER** for positive, lokalt identificerede lagertal, **KLARGØRES** ved skjult produkt, ellers **UKENDT** for rent online systemlager. Ingen Salling HOT-hændelse må få **KØB NU** / **RESERVÉR NU** alene fra `online_count`, `is_exposed` eller butikstal. Andre usikre statusser kræver stadig separat gennemgang.
- Rollback kræver kun at fjerne de fire `DISCORD_V2_*_MODE`-envlinjer eller sætte dem til `shadow` i workflows og merge. Ingen state- eller secretmigration.
- Price Watch og Cardmarket bruger fortsat eksisterende formater. `RESERVÉR NU` må ikke aktiveres på basis af systemlager alene.

## Anti-spam

- Restock-dubletter har 6 timers cooldown for samme dedupe-identitet.
- Nye produkter/preorders har fortsat 24 timers cooldown.
- Price alerts har 24 timers memory og dedupes på produkt/event, ikke retailer-URL.
- Et rent skift af billigste butik ved samme pris er ikke et intraday Discord-signal.
- Price Watch/Price History skal prioritere menneskelig beslutningsværdi over komplet Discord-output.

## Elgiganten

Signed Algolia var den foretrukne fulde kilde, men aktiv scanning er senere retired, fordi ingen stabil offentlig live-stock-path kunne dokumenteres fra GitHub-runneren. Historisk state bevares, men må ikke bruges som frisk Price Watch/History-data.

## Proshop

Proshop direkte HTML fra GitHub Actions er fortsat blokeret af HTTP 403. Jina Reader er den praktiske produktionskilde; direkte HTML er kun fallback. Parser V2 (`proshop_reader_v2.py`) læser image-led produktkort og knytter pris/lager til den konkrete card-container, fordi den gamle Markdown-heading-regex overså reelle produkter. Parseren deles af hovedscanner og HOT. Produkt-ID'er bevares, og ikke-prissatte kort skal fortsat kunne gemmes i state.

Proshop-vagten skelner nu mellem accepteret delvis dækning (mindst 3 friskparsede TCG-kort; health=degraded ved under 6) og grøn dækning (mindst 6). 6 er en foreløbig konservativ operationel tærskel, IKKE bevis for komplet Proshop-katalog. Baseline ved parser-migration er tavs for at undgå falske NYT-opslag, og HOT har 24-timers dublet-cooldown. Delvist skjulte/bestillingsvarer kan stadig mangle på den offentligt renderede kategoriside; 403 er ikke løst. Bedre officiel feed/produktkatalogvej skal undersøges separat uden omgåelse af adgangskontrol.

Proshop kendte SKU'er: `proshop_known_sku_watch.py` tilføjer `Pokemon TCG 2-pack Booster` til titel-filteret uden at medtage portfolios og sleeves. Hovedscanner og HOT verificerer højst 2 manglende kendte SKU'er pr. scan via Jina med mindst 15 minutters interval pr. SKU. Kun præcis URL + Proshop-varenummer + entydig egen-produktstatus er valide; HTTP 200, generisk omdirigering, generel juridisk tekst og lagerstatus på relaterede produkter er aldrig nok. Uklare svar skal ikke opdatere status. Gamle produkt-ID'er beholdes i state, og kendte produkter får tavs baseline før eventuelle fremtidige restock-alerts. Kategori-dækning måles fortsat særskilt fra detaljekontroller, så få validerede SKU'er ikke skaber falsk grøn driftvagt.

## Sikker ændringsproces

Før kodeændringer:

1. Hent live `AGENTS.md`, relevante kodefiler, workflowet, seneste state og nylige commits.
2. Fastslå den præcise årsag med konkrete eksempler.
3. Lav den mindst mulige ændring, der løser problemet.
4. Bevar state og historik; undgå håndredigering af state, medmindre opgaven kræver det.
5. Kontrollér at gamle patchfiler i workflowet ikke genanvender forældet logik.

Før levering:

1. Test konkrete produkter, der skal blokeres.
2. Test positive mod-eksempler, der fortsat skal tillades.
3. Kør mindst syntaks/compile-kontrol og relevante målrettede tests.
4. Kontrollér workflowfil og imports, hvis de er berørt.
5. Bekræft efter en produktionsændring, at en efterfølgende scannerkørsel lykkes og opdaterer state som forventet.
6. Beskriv kort ændringen, risikoen og hvad der er verificeret.

Ændr ikke flere uafhængige dele af systemet samtidig uden en klar grund. Brug shadow mode/logning først til nye brede relevansregler, så falske positive og falske negative kan vurderes uden Discord-støj.

## Kendte driftsforhold

Senest observeret 2026-08-21:

- Wave 1 med Symbizon, CardX, Matraws, Halmes Hule og CardsDirect har gennemført baseline-run og skrevet state.
- Wave 2 med Baltzer Games, TCG Shoppen, Pokemons.dk og Pocket Monster virker efter første produktionsrun.
- Pokemons.dk og Pocket Monster bruger målrettet WooCommerce-søgning for at undgå at hente enorme single-card-kataloger.
- CardstoreCPH er retired i V30, fordi sealed-filteret korrekt gav 0 relevante produkter; shoppen er primært enkeltkort. Historisk state bevares.
- Wave 3 med Fun-shop, PokéPulls, Staalz, PBCards og KoCardz er lagt i workflowet og skal verificeres på første efterfølgende produktionsrun.
- Proshop er sund via Jina Reader, mens direkte HTML fortsat kan være mere skrøbelig.
- Elgiganten aktiv scanning er retired; historisk state bevares.
- Workflowet committer state ved ændringer og kan derfor skabe mange commits.
- Local Stock Watch er i produktion for Bilka/Føtex med Kolding, Fredericia, Vejen, Brørup og Esbjerg.
- Coop app/live-stock reverse-engineering-sporet er lukket og eksperimentfilerne er fjernet.
- Workflowet har historisk haft trin til engangs-patches; primær kode skal være den varige løsning.

Kontrollér altid aktuel state, da disse forhold kan være løst eller ændret.

## Prioriteret videreudvikling

Gode næste trin, som skal indføres enkeltvis og sikkert:

1. Verificér Wave 3-kilderne i produktionsrun og ret kun dokumenterede feed/path-problemer.
2. Evaluér støjniveau og datakvalitet over 12-24 timer efter Wave 1-3.
3. Bedre datakvalitetskontrol for urimelige priser, lagertal og produktantal.
4. Release-/preorder-radar.
5. Relevansscore i shadow mode før eventuel yderligere automatisk filtrering.

## Beslutningslog

- 2026-08-18: Mega Zygarde-produktet blev gjort tavst i restock.
- 2026-08-18: Central filtrering af portfolios, penalhuse og øvrigt tilbehør blev indført med undtagelser for legitime forseglede collections.
- 2026-08-18: Proshop-parseren blev gjort linkbaseret; Jina Reader bruges som fallback.
- 2026-08-18: Elgigantens rate-limit-cooldown blev gjort persistent med eksponentiel backoff.
- 2026-08-20: Local Stock Watch blev produktionsgjort for Bilka/Føtex med Kolding, Fredericia, Vejen, Brørup og Esbjerg.
- 2026-08-20: Coop live-stock/app reverse-engineering-sporet blev lukket og eksperimentfiler fjernet.
- 2026-08-20: V23 fastsatte prislofter, 25 kr./5% prisændringsgate, 6 timers restock-dedupe, kompaktere Price Watch/History, ugentlig fuld CSV, Proshop direct-parser fix og konservativ Elgiganten-fallback.
- 2026-08-21: V27 fjernede individuelle Price History new-low Discord-beskeder, så dagsoutput holder sig kompakt.
- 2026-08-21: V28 tilføjede Symbizon, CardX, Matraws, Halmes Hule og CardsDirect som Wave 1-kilder via Shopify-scanneren.
- 2026-08-21: V29 tilføjede Baltzer Games, TCG Shoppen, Pokemons.dk, Pocket Monster og CardstoreCPH som Wave 2-kilder med platformstilpassede fetch-metoder.
- 2026-08-21: V30 retired CardstoreCPH fra aktiv scanning efter 0 relevante sealed produkter; historisk state bevares, og sealed-filteret blev ikke svækket.
- 2026-08-21: V31 tilføjede Fun-shop, PokéPulls, Staalz, PBCards og KoCardz som Wave 3-kilder med platformstilpassede feeds og uden at ændre de eksisterende sealed-/sprogfiltre.
- 2026-08-21: V38 tilføjede Kelz0r, Faraos, Goblin Games, ZZGames og Hyggeonkel som den sidste butiksekspansions-wave for nu; Bog & idé blev udskudt under platformsmigrering, og Bræt & Brikker blev fravalgt som lukket.
- 2026-08-25: Automatisk Discord-retention blev tilføjet: webhook-/botopslag
  ældre end 24 timer ryddes, mens pinned og manuelle opslag bevares.
- 2026-08-25: V45 tilføjede retry/backoff til Pocket Monster, retired ZZGames,
  krævede købbar/preorder-status for nye katalogalerts, flyttede scanner-health ud
  af Restock, ensrettede checklane/battle-deck-filteret i Price, fjernede tomme
  prisdigests og adskilte Card Market fra Price History.
- 2026-09-29: Local Stock undertrykker løse `BOOSTER PACK`-signaler for Mega Evolution: Perfect Order. Produktet bevares i state, og andre Perfect Order-formater samt andre booster packs påvirkes ikke.
- 2026-10-02: Housekeeping fjernede to forældede Price Watch V61 engangs-workflows og den retired `salling_victini_state.json`. `state_commit_guard.py` blev rettet, så Price Watch `listings[].last_seen` ikke længere skaber store no-op state-diffs på hvert scan. Ingen scanner-/alertsemantik blev ændret.
- 2026-09-26: Boozt og Magasin blev tilføjet til Tier A HOT-scanneren. Boozt læses via den offentligt renderede brand-katalogside (Reader transport), hvor forsvundne varer bevares som udsolgte. Magasin opdager TCG-produkter via de offentlige product-sitemaps og læser pris/lager direkte fra produktsidens GTM/produktdata; Magasin køres med ca. 5 minutters cadence. Retail-parserændringer baseline-indlæses stille via RETAIL_DISCOVERY_VERSION.
- Lav-signal-produkter skal normalt forblive i state, men ikke sendes til Discord.

- 2026-08-31: V47 tilføjede et Matraws-specifikt Discord-værn mod enkeltkort med Matraws' per-card titelkonvention (fx `[CLC-009]`). Produkterne bevares i state, men må ikke udløse Restock-alerts.

## Kommunikation

Skriv kort og konkret på dansk. Start med anbefalingen eller resultatet. Forklar tydeligt, hvad der blev ændret, hvad der ikke blev ændret, og hvordan det er verificeret. Bed om godkendelse før destruktive ændringer, historikmigreringer eller større adfærdsændringer.
