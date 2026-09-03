# V49 Cardmarket feasibility

## Formål

V49 er en shadow-only feasibility-test for en fremtidig personlig singles-scout. Den må ikke ændre Restock Core, sende Discord-signaler eller skrive produktionsstate.

Målet er at afgøre, om de eksisterende aggregate Cardmarket-priser kan bruges som andet end markedsradar.

## Aktuel datagrænse

Den eksisterende Cardmarket watcher har produkt-ID og aggregate prisfelter som low, trend, avg1, avg7, avg30 og foil-varianter. Den kan ikke selv verificere den konkrete listings sprog, condition, sælgerland eller shipping til Danmark.

Derfor er et automatisk "KØB"-signal ikke tilladt på V49-data alene.

## Testdesign

`cardmarket_feasibility.py`:

- læser kun eksisterende `cardmarket_chase_state.json`
- udvælger deterministisk 20 Pokémon-cases fordelt på flere prisniveauer og sæt
- laver en review-template til manuel kontrol af den konkrete Cardmarket listing
- kræver exact product match, English, MT/NM, EU/EEA-sælger og shipping til Danmark
- måler forskellen mellem aggregate API-low og den verificerede brugbare listing
- producerer kun en Markdown-rapport
- kalder ikke Cardmarket
- sender ikke Discord
- ændrer ikke state

## Verdicts

- `PENDING`: færre end 15 cases er fuldt verificeret.
- `PURCHASE_READY`: mindst 15 cases er verificeret, mindst 80% har en brugbar EN/NM EU→DK listing, median-gap fra aggregate low er højst 10%, og P90-gap er højst 25%.
- `RADAR_ONLY`: alt andet. Aggregate data kan stadig bruges til trend, historik og manuel chase-prioritering, men ikke som direkte købssignal.

Thresholds er bevidst konservative. Formålet er at undgå falsk præcision.

## Kørsel

```bash
python cardmarket_feasibility.py --write-review-template
```

Det opretter:

- `cardmarket_feasibility_report.md`
- `cardmarket_feasibility_reviews.json` hvis review-filen ikke allerede findes

Review-filen udfyldes kun med observationer fra den konkrete Cardmarket produktside. Ukendte felter må ikke gættes.

Derefter køres scriptet igen for at få verdict.

## Arkitekturregel

Hvis Personal Scout senere bygges, skal den ligge ved siden af/ovenpå Restock Core. Restock Core skal fortsat fungere uændret for øvrige brugere, selv hvis den personlige del er slået fra eller fejler.
