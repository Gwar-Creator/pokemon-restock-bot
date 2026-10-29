# Vintage Finder v0: Pokémon lots, not sealed deal hunting

**Status: independent read-only prototype, NOT a running Discord scanner.**

## Why

Keep the existing Restock/HOT pipeline for sealed Pokémon. Explore a separate
Vintage Finder only if it improves discovery of personally relevant WotC, Neo
Destiny Dark/Light, Gym, e-reader and early EX-era lots. Do **not** sell the
user on buying more: every candidate is a manual review lead, not a deal.

## Actual webhook destination verified (29 October 2026)

- **Webhook-destination er verificeret 29. oktober 2026:** GitHub Actions [run 40823401471](https://github.com/Gwar-Creator/pokemon-restock-bot/actions/runs/40823401471) sammenlignede den eksisterende `MARKETPLACE_WEBHOOK_URL` med brugerens bekræftede kanal-ID `1540094708439711904` og returnerede `VERIFIED` via read-only GET. Ingen webhook blev vist, og ingen POST blev sendt. **Vintage Finder Discord-alarmer er fortsat slået fra**, fordi uverificerede shortlist-fund ikke er KØB/BYD.

## Discord destination: existing #marketplace-deals

The existing Discord channel `#marketplace-deals` is reserved for
**verified, actionable KØB or BYD signals only**, as agreed in August 2026.
Never post ordinary listings, WATCH, OK PRIS, MÅSKE, or unverified REVIEW
candidates there. Do not create a new channel.

`vintage_marketplace_discord.py` currently builds **offline REVIEW previews
only**; these are internal diagnostic drafts, **not publishable alerts**.
It never posts or requires Discord credentials.

Use only verified public Tradera URLs; label candidates **TIL GENNEMGANG**.
Unknown total cost to Denmark, variant, English language, condition,
authenticity and resale value must remain explicitly unverified. Never
call a listing a confirmed deal, present an unsupported savings amount,
or encourage impulse purchases.

For a future controlled activation, first validate historical/live listing
relevance, delivery to Denmark, deduplication and posting frequency; then verify
the webhook for the **existing** channel, for example a dedicated
`MARKETPLACE_WEBHOOK_URL` GitHub secret (the earlier proposed name). Do not assume the secret already
exists and never repurpose existing Cardmarket/price webhooks. Before any live posting, require independently verified card identity,
condition, language, seller credibility, shipping/fees to Denmark and a
conservative maximum bid/buy price. If anything material is unknown,
leave the candidate off Discord. No live alerts are authorized by
this preview work.

## Vintage Finder Light: shortlist + exact webhook verification

- Keep discovery small: lot/binder/collection context plus convincing vintage set or explicit old collection signal. Do not attempt automatic identification of every card or speculative aggregate resale valuation.
- `vintage_marketplace_runner.py` queries the six established official Tradera REST v4 searches and archives at most **eight** internal REVIEW-only listings. It makes zero Discord calls and does not schedule or mutate any existing scanner state.
- `vintage_marketplace_shortlist.py` supplies a separate unactivated cross-run dedupe/baseline model and hard caps of three candidates per run/day and eight/week. It is currently **offline/tested**, not a production sender. An internal preview is not a BUY/BID recommendation.
- Discord readiness: one read-only verification workflow checks `MARKETPLACE_WEBHOOK_URL` against Discord's returned `channel_id`, which must exactly equal a separately verified GitHub Actions variable `MARKETPLACE_EXPECTED_CHANNEL_ID`. Existence of the secret alone is insufficient. Never print sensitive values or send a test message to a mismatched webhook.
- **No live alerts yet.** Confirm the existing channel, validate real-card/price/shipping evidence, and only then create a gated publisher for genuine KØB/BYD. Do not post normal shortlist listings to `#marketplace-deals`.

## Conservative manual budget and max-bid worksheet

- `vintage_lot_budget.py` accepts **independently checked** card-level inventory, condition, English edition, seller credibility, Danish shipping, fees, current Tradera price and a separately verified SEK/DKK rate. It never calls an API or Discord, and it NEVER labels a listing KØB/BYD.
- It requires both a **current available hobby budget in DKK** and a **personally approved conservative cap in DKK**, grounded in comparable European sales and collection interest. Neither input may be guessed or taken from title-only matches. The binding ceiling is the lower of the two.
- All-in DKK = (current required SEK price + verified DK shipping SEK + verified platform fees SEK) × verified SEK/DKK rate + payment fees DKK. Unknown or unverifiable values **block** calculation. Input timestamps must be current; numbers use exact Decimal arithmetic and conservative rounding.
- Maximum affordable *current* SEK bid is calculated from the remaining verified cap after all charges. This is strictly a manual affordability limit, **not a fair-market valuation, bargain score, guaranteed execution price or permission to bid**. Recheck price, FX and shipping before any action.
- Individually identified cards are marked KEEP, SELL (proposed resale only, no assumed liquidity) or FILLER for manual quality context. A lot with only FILLER cards is not relevant. Inventory status must be checked against the current Google Sheet, not guessed.
- All missing seller, authenticity, identity, photos, language, delivery, budget or market-comparable evidence returns `MISSING_EVIDENCE` with **no maximum bid**; over-ceiling returns `OVER_LIMIT`. This module has no webhook or purchase integration.

## Read-only listing detail schema validation

- `vintage_tradera_item_probe.py` uses only official `GET /v4/items/{itemId}` with app credentials; it reads **four fixed item IDs** previously returned by the successful Tradera search, without list pagination, scraping, seller login, bids or purchases.
- The one-shot `.github/workflows/tradera_item_detail_probe.yml` validates field names/types only. Seller values, listing text, actual prices, photos and full JSON **must not** be logged or committed. No Discord secret is passed.
- Treat a returned shipping field or price field as **unverified** until its semantics, delivery destination (Denmark), currency and actual cost are checked. Card photos, actual contents/condition, English edition and seller reliability still need separate review.
- A detail schema result is not an actionable recommendation. `#marketplace-deals` remains silent.

## Shadow quality audit — initial one-shot sample

- `vintage_tradera_quality.py` takes one page for each of six Tradera REST v4 vintage-oriented queries, deduplicates by item ID and counts TITLE_VINTAGE, TITLE_UNCERTAIN and EXCLUDED. It never sends Discord or writes persistent state.
- `.github/workflows/tradera_quality.yml` runs once on its initial deployment to main (and on explicit manual dispatch only). It checks whether `MARKETPLACE_WEBHOOK_URL` is configured without printing its value. It **does not** verify which Discord channel receives that webhook; live alerts remain disabled.
- Logs/artifact contain at most 20 public title/URL samples for human relevance review, not seller identities. Automated title categories are **not** verified deals or measured true-positive/false-positive counts: precision stays unknown until manual labeling and inspection of photos, language, seller and total DK cost.
- The future KØB/BYD gate needs current, listing-specific human evidence for real cards, authenticity, card language, condition, seller, DK shipping/fees, market comparisons and conservative cap. It is not wired into a sender or any automatic bids.
- This snapshot is the **first step** toward the previously proposed 14-day shadow validation, not evidence that the longer observation is complete. No production activation from this sample.

## First successful live shadow quality sample (28 October 2026)

- The official REST v4 six-query, first-page-only audit finished successfully: **300 search rows**, **297 distinct valid public listing links**, **3 repeated hits**, **0 malformed links**.
- Earlier failed runs were caused by untrimmed credential header values and Tradera-provided legacy HTTP item links; the client now trims credentials and strictly upgrades only whitelisted Tradera HTTP URLs to HTTPS.
- Initial *title-only* classes: 159 specific vintage text matches, 97 generic/uncertain leads and 41 excluded listings. These are NOT 159 confirmed vintage cards, NOT good buys and NOT a measured false-positive rate.
- In a first nonrandom set of 20 TITLE_VINTAGE samples, two titles ("Fossil Egg" and "Fossil Excavation Kit") were clearly not WotC Fossil-set evidence. The remainder primarily described individual vintage-era cards, not necessarily the target collections/lots. Neither photos nor shipping/seller/condition/prices have been independently verified.
- Follow-up shadow code separately counts **lot/context title signals**, excludes the two observed card-name collisions and takes balanced samples across vintage lots, other vintage singles, uncertain leads and excluded titles. This is still discovery QA, not BUY/BID qualification.
- The existing `MARKETPLACE_WEBHOOK_URL` secret is **configured**, but its destination remains unverified. No messages have been sent and `#marketplace-deals` remains BUY/BID-only after human verification.
- Before any activation, measure **manually labeled** relevance and false positives on real listing content and verify seller, DK delivery total, edition/variant, authenticity, condition and a conservative price ceiling. Existing 14-day shadow requirement remains outstanding.

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
