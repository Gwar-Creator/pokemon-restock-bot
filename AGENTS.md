# AGENTS.md

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
- `local_stock_state_v1.json`: vedvarende state for Local Stock Watch, når baseline er oprettet.
- `scanner_health_audit.py`: log-only audit af de aktive scannerkilder.
- `.github/workflows/restock.yml`: GitHub Actions-kørsel og commit af state.
- `cardmarket_chase_watch.py`: Cardmarket-overvågning.
- `cardmarket_v16_replay.py`: historisk replay/hjælpeværktøj, hvis filen findes.

Læs altid de live filer i GitHub. Stol ikke alene på en ældre chat, lokal kopi eller handover-fil.

## Drift og kanaler

- Ekstern scheduler udløser normalt `.github/workflows/restock.yml` cirka hvert 5. minut.
- Workflowet scanner butikker, sender relevante Discord-events og committer ændret state tilbage til `main`.
- Restock-kanalen er til lagerændringer og nye relevante varer.
- Price Watch er handlingsorienteret og skal være kompakt.
- Price History bevarer statistik, men Discord-output skal være let; fuld detalje hører til data/CSV.
- Webhooks, tokens og andre secrets må aldrig skrives i kode, logs, dokumentation eller commits.

## Overvågede kilder

Scannerens nuværende kilder omfatter Coolshop, Proshop, BR, Bilka, Føtex, Elgiganten (historisk/retired), PokeHulen, Rogerz, MTGwebshop, Luckbox, Spilforsyningen, Musen & Slottet, Symbizon, CardX, Matraws, Halmes Hule, CardsDirect, Baltzer Games, TCG Shoppen, Pokemons.dk, Pocket Monster, CardstoreCPH, Nostalgic, &Cards, Pokecards.dk, Epic Panda, Steffen-O og Next Level Games.

Wave 1-udvidelsen fra 2026-08-21 tilføjede Symbizon, CardX, Matraws, Halmes Hule og CardsDirect som Shopify-kilder.

Wave 2-udvidelsen fra 2026-08-21 tilføjer Baltzer Games og TCG Shoppen som Shopify-kilder, Pokemons.dk og Pocket Monster via målrettede WooCommerce Store API-søgninger samt CardstoreCPH via en separat linkbaseret kategori-parser. Nye kilder baseline-indlæses uden historiske produkt-alerts og går derefter ind i normal restock-/Price Watch-/Price History-logik, når de er friske og sunde.

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

## Anti-spam

- Restock-dubletter har 6 timers cooldown for samme dedupe-identitet.
- Nye produkter/preorders har fortsat 24 timers cooldown.
- Price alerts har 24 timers memory og dedupes på produkt/event, ikke retailer-URL.
- Et rent skift af billigste butik ved samme pris er ikke et intraday Discord-signal.
- Price Watch/Price History skal prioritere menneskelig beslutningsværdi over komplet Discord-output.

## Elgiganten

Signed Algolia var den foretrukne fulde kilde, men aktiv scanning er senere retired, fordi ingen stabil offentlig live-stock-path kunne dokumenteres fra GitHub-runneren. Historisk state bevares, men må ikke bruges som frisk Price Watch/History-data.

## Proshop

Direkte Proshop-parser er førstevalg. Jina Reader er fallback. Den direkte parser skal være link-baseret og finde den nærmeste relevante produktcontainer omkring hvert produktlink; den må ikke afhænge af skiftende CSS-klassenavne. Price-løse kommende produkter må bevares i state.

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
- Wave 2 med Baltzer Games, TCG Shoppen, Pokemons.dk, Pocket Monster og CardstoreCPH er lagt i workflowet og skal verificeres på første efterfølgende produktionsrun.
- Pokemons.dk og Pocket Monster bruger målrettet WooCommerce-søgning for at undgå at hente enorme single-card-kataloger.
- CardstoreCPH bruger en særskilt linkbaseret HTML-parser, fordi shoppen ikke følger de eksisterende Shopify/WooCommerce-feedmønstre.
- Proshop er sund via Jina Reader, mens direkte HTML fortsat kan være mere skrøbelig.
- Elgiganten aktiv scanning er retired; historisk state bevares.
- Workflowet committer state ved ændringer og kan derfor skabe mange commits.
- Local Stock Watch er i produktion for Bilka/Føtex med Kolding, Fredericia, Vejen, Brørup og Esbjerg.
- Coop app/live-stock reverse-engineering-sporet er lukket og eksperimentfilerne er fjernet.
- Workflowet har historisk haft trin til engangs-patches; primær kode skal være den varige løsning.

Kontrollér altid aktuel state, da disse forhold kan være løst eller ændret.

## Prioriteret videreudvikling

Gode næste trin, som skal indføres enkeltvis og sikkert:

1. Verificér Wave 2-kilderne i produktionsrun og ret evt. collection/search paths, hvis en butik giver for få produkter.
2. Evaluér støjniveau og datakvalitet over 12-24 timer efter Wave 1 + Wave 2.
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
- Lav-signal-produkter skal normalt forblive i state, men ikke sendes til Discord.

## Kommunikation

Skriv kort og konkret på dansk. Start med anbefalingen eller resultatet. Forklar tydeligt, hvad der blev ændret, hvad der ikke blev ændret, og hvordan det er verificeret. Bed om godkendelse før destruktive ændringer, historikmigreringer eller større adfærdsændringer.
