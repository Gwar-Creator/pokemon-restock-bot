# AGENTS.md

## Formål

Dette repository driver en dansk Discord-scanner for Pokémon- og Lorcana-restocks, prisovervågning og Cardmarket-historik. Målet er få, relevante og troværdige notifikationer — ikke flest mulige notifikationer.

Denne fil er den varige projekthukommelse på tværs af chats. Før større ændringer skal den læses sammen med den aktuelle kode, workflowet og seneste state. Opdater kun filen, når arkitektur, faste regler, kendte risici eller væsentlige beslutninger ændrer sig.

## Kilde til sandhed

Repository: `Gwar-Creator/pokemon-restock-bot`
Produktionsgren: `main`

Vigtige filer:

- `restock_bot_github.py`: primær scanner, filtre, Discord-output og Price Watch.
- `restock_state_v2.json`: vedvarende lager-, pris-, historik- og source-health-state.
- `.github/workflows/restock.yml`: GitHub Actions-kørsel og commit af state.
- `cardmarket_chase_watch.py`: Cardmarket-/Price History-overvågning.
- `cardmarket_v16_replay.py`: historisk replay/hjælpeværktøj, hvis filen findes.

Læs altid de live filer i GitHub. Stol ikke alene på en ældre chat, lokal kopi eller handover-fil.

## Drift og kanaler

- Ekstern scheduler udløser normalt `.github/workflows/restock.yml` cirka hvert 5. minut.
- Workflowet scanner butikker, sender relevante Discord-events og committer ændret state tilbage til `main`.
- Restock-kanalen er til lagerændringer.
- Price Watch er en kompakt daglig prisoversigt.
- Price History/Cardmarket er til historik og markedsdata.
- Webhooks, tokens og andre secrets må aldrig skrives i kode, logs, dokumentation eller commits.

## Overvågede kilder

Scannerens nuværende kilder omfatter blandt andet Coolshop, Proshop, BR, Bilka, Føtex, Elgiganten, PokeHulen, Rogerz, MTGwebshop, Luckbox, Spilforsyningen, Musen & Slottet, Nostalgic, &Cards, Pokecards.dk, Epic Panda, Steffen-O og Next Level Games.

Butikslisten kan ændre sig. Koden og den seneste state er altid autoritative.

## Relevans for restock

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

Lokale fund er især relevante omkring Kolding/Fredericia samt Brørup og cirka 20 km omkring Vejen. Den nuværende kode har historisk haft eksplicit dækning for Kolding og Esbjerg; udvidelser skal verificeres mod butikkernes faktiske lagerdata og må ikke gættes.

## Price Watch og historik

- Price Watch skal kun bruge aktuelt køb-bare produkter og friske, sunde kilder.
- Produkter fra en fejlet eller forældet kilde må ikke fremstå som aktuelle tilbud.
- Oversigten skal være kompakt og undgå støj; detaljer hører hjemme i historik/Excel.
- Prisnormalisering skal tage højde for sprog, produkttype, sæt og antal pakker.
- Eksisterende pris- og Cardmarket-historik må ikke slettes, nulstilles eller migreres uden udtrykkelig godkendelse.
- Kendt legacy-data kan indeholde støjende nøgler og fejlklassifikationer, eksempelvis cases, checklanes eller forkert sprog.

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

Senest observeret 2026-08-18:

- Proshop blev gendannet som sund kilde med 7 relevante produkter efter en robust parserrettelse.
- Elgiganten er fortsat rate-limited med HTTP 429, men cooldown og eksponentiel backoff gemmes nu korrekt mellem GitHub-runs. Eksisterende 17 produkter bevares, indtil en frisk Algolia-nøgle kan hentes.
- Workflowet committer state ved ændringer og kan derfor skabe mange commits.
- Enkelte lokale lagerdata fra BR/Føtex kan være mistænkelige og bør diagnosticeres før ændringer.
- Workflowet har historisk haft trin til engangs-patches; primær kode skal være den varige løsning.

Kontrollér altid aktuel state, da disse forhold kan være løst eller ændret.

## Prioriteret videreudvikling

Gode næste trin, som skal indføres enkeltvis og sikkert:

1. Relevansscore i shadow mode før automatisk filtrering.
2. Bedre source-health, backoff og særskilte fejlalarmer.
3. Datakvalitetskontrol for urimelige priser, lagertal og produktantal.
4. Købssignaler baseret på pris, efterspørgsel, lager og produkttype.
5. Release-/preorder-radar.
6. Mere præcis lokal dækning omkring brugerens prioriterede områder.

## Beslutningslog

- 2026-08-18: Mega Zygarde-produktet blev gjort tavst i restock.
- 2026-08-18: Central filtrering af portfolios, penalhuse og øvrigt tilbehør blev indført med undtagelser for legitime forseglede collections.
- 2026-08-18: Proshop-parseren blev gjort linkbaseret og begyndte igen at levere 7 levende produkter; pris-løse preorders bevares.
- 2026-08-18: Elgigantens rate-limit-cooldown blev gjort persistent med eksponentiel backoff, og lokal `in_stock` blev rettet til Price Watch.
- Lav-signal-produkter skal normalt forblive i state, men ikke sendes til Discord.

## Kommunikation

Skriv kort og konkret på dansk. Start med anbefalingen eller resultatet. Forklar tydeligt, hvad der blev ændret, hvad der ikke blev ændret, og hvordan det er verificeret. Bed om godkendelse før destruktive ændringer, historikmigreringer eller større adfærdsændringer.
