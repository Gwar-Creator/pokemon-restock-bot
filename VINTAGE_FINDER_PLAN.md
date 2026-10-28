# Vintage Finder v0: Pokémon lots, not sealed deal hunting

**Status: independent read-only prototype, NOT a running Discord scanner.**

## Why

Keep the existing Restock/HOT pipeline for sealed Pokémon. Explore a separate
Vintage Finder only if it improves discovery of personally relevant WotC, Neo
Destiny Dark/Light, Gym, e-reader and early EX-era lots. Do **not** sell the
user on buying more: every candidate is a manual review lead, not a deal.

## Discord destination: existing #marketplace-deals

The existing Discord channel `#marketplace-deals` is the destination for
**future manually useful** Vintage Finder notifications; do not create a new
channel. `vintage_marketplace_discord.py` currently builds **offline preview
embeds only**. It never posts or requires Discord credentials.

Use only verified public Tradera URLs; label candidates **TIL GENNEMGANG**.
Unknown total cost to Denmark, variant, English language, condition,
authenticity and resale value must remain explicitly unverified. Never
call a listing a confirmed deal, present an unsupported savings amount,
or encourage impulse purchases.

For a future controlled activation, first validate historical/live listing
relevance, delivery to Denmark, deduplication and posting frequency; then verify
the webhook for the **existing** channel, for example a dedicated
`MARKETPLACE_DEALS_WEBHOOK_URL` GitHub secret. Do not assume the secret already
exists and never repurpose existing Cardmarket/price webhooks. No live alerts
are authorized by the preview work.

## First official Tradera live result verified

- **28 October 2026:** `tradera_probe.yml` returned HTTP 200 and `GET /v4/search?query=pokemon+samling&pageNumber=0` returned exactly 50 rows on the first page, without printing titles, sellers, prices or secrets.
- Verified outer JSON fields: `errors`, `items`, `totalNumberOfItems`, `totalNumberOfPages`.
- Verified first item fields include `id`, `shortDescription`, `itemUrl`, `maxBid`, `nextBid`, `hasBids`, `sellerAlias` and others. In `vintage_finder_tradera.py` we now map `shortDescription` as the candidate title and validate public `itemUrl`, with no inference of a total offer price, English card language or shipping to Denmark.
- These 50 are **search results**, NOT verified vintage cards, bargains or candidate matches. A separate no-Discord quality test is still needed before monitoring can be scheduled.

## First credentials test (read-only, 28 October 2026)

- The user has added `TRADERA_APP_ID` and `TRADERA_APP_KEY` as GitHub Actions repository secrets. Never print, copy, commit, or share them.
- `.github/workflows/tradera_probe.yml` runs exactly **one live read-only search** for `pokemon samling` during initial deployment to main because its path is new; afterward only explicit `workflow_dispatch` can run it again.
- The probe has no `schedule`, no Discord/webhook secrets, no write permission, no persisted state, no bid or buy capability.
- The only live log contains API HTTP status and the JSON field names/array lengths; no seller names, titles, prices, full responses or secret headers.
- Confirm green CI first, merge the PR, inspect initial diagnostic workflow. A failed/unknown schema should be fixed in a second PR, not by retrying repeatedly.
- Only after an actual verified Tradera v4 search response should `extract_search_rows` be adapted to the documented structure and a shadow candidate sample collected without notifications.

## Tradera integration: officially documented path

- Use the official [Tradera Developer Program](https://api.tradera.com/documentation)
  and [REST v4 GET /search](https://api.tradera.com/documentation/rest/search).
- Read-only requests require an **application** ID and key in
  `X-App-Id` / `X-App-Key` headers. No account purchase authorization,
  bidding token, or login automation is needed for the search operation.
- v4 is beta; the current OpenAPI SearchResult schema is opaque. **Check real
  search response format before treating any listing data as verified.**
- Create and register a Tradera application to obtain app credentials. Store
  values **only as GitHub Actions secrets** when a real workflow is approved,
  never as repository files, links, logs or chat text.
- Local offline dry run: `python vintage_finder_tradera.py` prints search
  phrases and has no network, state changes or Discord effects.
- Read-only API test after credentials are configured in a secure runtime:
  `TRADERA_APP_ID=... TRADERA_APP_KEY=... python vintage_finder_tradera.py --live --query "pokemon samling"`.
  This is **not** a scheduled workflow. Do not paste actual credentials into
  chat or tracked files.
- Response field/variant validation is a release gate. Until real data
  validates them, no production messages, new webhook or purchase valuations.
- Automatic bidding, auction sniping, automatic buying and close-time bid
  timing are **not allowed**. The integration must remain advisory.

## DBA: built-in agents instead of scraping

- [DBA annonceagent](https://support.dba.dk/hc/da/articles/23815382363666-Annonceagent-Hvad-er-det-tilmelding-og-afmelding)
  provides push or daily email for saved searches.
- Test 2-3 specific saved searches in DBA itself, e.g. `gamle pokemon kort`,
  `pokemon kort samling`, `pokemon mappe`. Do not scrape DBA: its help
  center explicitly prohibits regular/systematic collection without written
  permission. This repo must not add an automated DBA crawler.
- For future aggregation, use only a user-authorized data channel where
  provider policy allows it (e.g. manually shared listing URLs).

## Initial review policy

- Keep the search term list narrow and dedupe by validated Tradera item ID.
- **Review candidates only:** vintage set names, old collections and lots,
  not booster products, modern bulk, mystery packs, replicas or explicit
  non-English card editions.
- Swedish listing language is **not evidence of Swedish-language cards**.
- Titles do not establish the actual card list, condition, edition, English
  language, shipping to DK, legitimacy, or a fair total price.
- Always include shipping and possible fees in any *future* valuation.
- Ask for clear fronts/backs and the card inventory before any purchase
  recommendation; no automatic bidding or messaging sellers.
- First API trial should be a 14-day *shadow* observation with no Discord
  notifications; record only count, duplicate rate and manually verified
  relevance in a separate, approved state namespace.
- Proposed future activation gate: at least 5 distinct verified relevant
  opportunities and a demonstrably low false-positive rate. Notifications,
  if ever enabled, should be capped and require a separate PR.

## Exclusions

No automatic sealed-market “reprint hunting”, no speculative price alerts,
no historical state migration, no weakening of the restock policy and
no auto-purchases.
