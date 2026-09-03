# V50 · Personal Singles Opportunity Engine

## Formål

V50 er et separat, personligt shadow-lag oven på den eksisterende Cardmarket-state. Det må ikke ændre Restock Core, sende Discord-beskeder eller foretage ekstra Cardmarket/API-kald.

Målet er at rangere de allerede trackede Pokémon-singles efter, hvilke der er værd at kontrollere manuelt på Cardmarket.

## V49-konklusion som designregel

Aggregate Cardmarket `low` er ikke purchase-grade for brugerens krav om korrekt version, English, MT/NM, EU/EEA seller og shipping til Danmark. Derfor har `low` **0 vægt** i V50-score og vises kun som diagnostik.

Prisreference:

1. `trend` som primær reference.
2. `avg7`/`avg30` som kontekst og fallback.
3. `low` bruges aldrig til ranking eller target-check.

## Personligt lag

`personal/singles_profile.json` indeholder kun bruger-specifikke regler. V50 starter bevidst småt:

- standard target: 75 DKK
- prioriterede Pokémon
- sekundære Pokémon
- tomme lister til verificerede wishlist-/owned-/ignore-Cardmarket-IDs
- tomme per-card target-overrides

Wishlist, owned og overrides må først fyldes med exact Cardmarket product IDs, når de er verificeret.

## Score

V50 kombinerer:

- 40% budget fit mod personlig target
- 25% trend vs avg30
- 15% avg1 vs avg7 timing
- 20% personlig relevans

Dataconfidence beregnes ud fra spredningen mellem trend, avg7 og avg30. LOW confidence kan aldrig blive `CHECK_NOW`.

## Signaler

- `CHECK_NOW`: interessant nok til at åbne Cardmarket og kontrollere konkrete offers nu.
- `WATCH`: tæt nok på til at holde øje med.
- `PASS`: ingen handling.

V50 må **aldrig** emitte `BUY`. Før et køb kræves manuel verifikation af:

- exact version/product
- English
- MT/NM
- EU/EEA seller
- shipping til Danmark

## Drift

V50 er shadow-only. Scriptet læser `cardmarket_chase_state.json`, laver ingen netværkskald og skriver kun en midlertidig Markdown-rapport, når det køres fra workflow/logging.

Det kan derfor slukkes eller fjernes uden effekt på Restock Core eller Cardmarket-historikken.
