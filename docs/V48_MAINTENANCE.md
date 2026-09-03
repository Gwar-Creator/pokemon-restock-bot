# V48 — Maintenance Cleanup

Dato: 2026-09-03

## Formål

V48 er en vedligeholdelsesrelease. Den ændrer ikke den tilsigtede restock-/prislogik, men reducerer teknisk gæld og Git-churn efter V23-V47.

## Ændringer

### Produktionsworkflow

- Fjerner runtime-kørsel af historiske `patch_vXX_*.py`-scripts.
- Fjerner afsluttede one-time retailer/price-preview jobs fra `restock.yml`.
- Fjerner ikke-live Market Radar validation/jobs fra hovedworkflowet.
- Bevarer Main Restock + Local Stock parallelisering.
- Bevarer scanner-health audit og Discord cleanup.
- Erstatter `git add -A` med eksplicit staging af produktionsstate/audit.

### State commit guard

`state_commit_guard.py` kompakterer kun kendte volatile felter før commit.

Det er vigtigt, at `_last_full_scan_epoch` i `restock_state_v2.json` ikke fjernes eller genbruges fra HEAD. Feltet er recovery-heartbeat og skal fortsat opdateres ved succesfulde hovedscans.

### Repository cleanup

Historiske patches slettes fra produktionsroden. Market Radar-forsøg flyttes til `experiments/market_radar/`. Salling pre-release probe flyttes til `tools/diagnostics/` og er ikke længere et aktivt workflow.

### Bevidst ikke ændret

- Ingen eksisterende state/historik nulstilles.
- Ingen aktive retailer parsers omskrives.
- Ingen Discord-regler eller prisgrænser ændres.
- Cardmarket-workflowet ændres ikke.

## Verifikation

Før merge skal følgende være opfyldt:

- YAML parser for begge ændrede workflows.
- `state_commit_guard.py` compiles.
- Unit tests for guardens Local Stock, Restock heartbeat, HOT og Salling timestamp-komprimering består.
- PR diff indeholder ingen ændringer af produktionsstate JSON-filer.
- Efter merge skal første Main Restock og første HOT-run være grønne før V48 betragtes som afsluttet.
