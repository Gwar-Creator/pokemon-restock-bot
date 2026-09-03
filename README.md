# Pokémon + Lorcana Restock Bot

Discord-baseret overvågning af danske Pokémon- og Lorcana-forhandlere med fokus på relevante sealed restocks, lokale Salling-lagerfund, prisovervågning og Cardmarket-signaler.

## Produktionsarkitektur

Der er tre separate driftsbaner:

1. **Main Restock** — `.github/workflows/restock.yml`
   - kører den brede butiksscanner i `restock_bot_github.py`
   - kører `local_stock_watch.py` parallelt
   - sender Restock-, Price Watch- og Price History-signaler
   - kører scanner-health audit

2. **HOT + Salling Early** — `.github/workflows/hot_restock.yml`
   - kører `hot_restock.py`
   - kører Victini-watch og Salling Early Radar i et hurtigere loop
   - har separat state og separat GitHub-concurrency

3. **Cardmarket** — `.github/workflows/cardmarket.yml`
   - kører Cardmarket Watch dagligt
   - bruger dedikeret Cardmarket-webhook og separat state

## Vigtige produktionsfiler

- `restock_bot_github.py` — hovedscanner, matching, Price Watch og Price History
- `restock_state_v2.json` — vedvarende hovedstate og historik
- `local_stock_watch.py` / `local_stock_state_v1.json` — lokal Salling-stock og PRE-PUBLISH
- `hot_restock.py` / `hot_restock_state.json` — hurtig restock-bane
- `salling_early_radar.py` / `salling_early_radar_state.json` — skjulte/kommende Salling-produkter
- `cardmarket_chase_watch.py` / `cardmarket_chase_state.json` — Cardmarket Watch
- `scanner_health_audit.py` — diagnostik af aktive kilder
- `discord_cleanup.py` — 24 timers Discord-oprydning
- `alert_policy.py` — fælles signalpolitik
- `state_commit_guard.py` — reducerer timestamp-only Git-diffs uden at ændre scannerlogik

## V48 vedligeholdelsesmodel

V48 fjernede gamle engangs-patches fra den aktive produktionsvej. Produktionsworkflows må ikke længere køre historiske `patch_vXX_*.py`-scripts ved hvert scan.

State ligger fortsat i repository for at bevare eksisterende drift og historik. `state_commit_guard.py` reducerer kun volatile timestamp-diffs:

- Local Stock genbruger `observed_at`, når produktets reelle data er uændrede.
- HOT genbruger `last_success_at`/`updated_at`, når den øvrige source-state er uændret.
- Salling early/Victini genbruger top-level `updated_at`, når indholdet ellers er identisk.
- Hovedscannerens `_last_full_scan_epoch` **bevares altid frisk**, fordi den bruges af V44 recovery guard.

`restock.yml` stager kun kendte produktionsfiler og bruger ikke længere `git add -A`.

## Eksperimenter og diagnostik

Ikke-produktionskode ligger uden for root:

- `experiments/market_radar/` — tidligere Market Radar-forsøg
- `tools/diagnostics/salling_prerelease_probe.py` — manuel Salling pre-release probe

De må ikke kobles på live Discord-output uden ny shadow/testfase.

## Test

De aktive workflows kører compile-kontrol og målrettede unit tests før scanning. Lokal minimumskontrol:

```bash
python -m py_compile restock_bot_github.py local_stock_watch.py hot_restock.py state_commit_guard.py
python -m unittest test_alert_policy.py test_discord_cleanup.py test_matraws_single_guard.py test_state_commit_guard.py
```

## Driftssikkerhed

- Secrets må kun ligge i GitHub Actions secrets.
- Eksisterende state/historik må ikke nulstilles eller migreres uden eksplicit godkendelse.
- Nye brede relevansregler bør først køre i shadow mode.
- `AGENTS.md` er den varige projekt- og beslutningshukommelse; live kode og seneste state er autoritative ved driftstjek.
