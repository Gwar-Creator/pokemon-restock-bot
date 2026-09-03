# V51 · Collection Baseline

V51 adds a permanent, machine-readable personal collection beside the shared Restock Core.

## Scope

- `personal/collection.json` is the source of truth for photographed owned cards.
- `personal/incoming.json` is reserved for already-purchased cards that have not yet moved into the photographed collection.
- `personal/singles_collection_runner.py` wraps the existing V50.1 radar and feeds it only **verified Cardmarket product IDs** from owned/incoming data.
- No fuzzy name/set matching is used for suppression. A missing Cardmarket product ID means the card stays unlinked and cannot hide a radar candidate by accident.
- No monetary valuation is persisted in the collection baseline. Value is calculated separately when needed.
- Restock Core, shop scanning, shared state and Discord behavior are unchanged.

## Baseline imported 2026-09-03

The approved image inventories contain:

- 133 physical cards total
- 125 exact unique records
- 132 Pokémon cards
- 1 Lorcana card
- 93 modern cards
- 40 vintage cards
- 0 verified Cardmarket product-ID links at initial import

The baseline merges the corrected 93-image modern inventory and the 40-image vintage inventory. Previous incomplete modern inventory output is not used.

## Safety rule

Collection identity and Cardmarket identity are separate fields. `cardmarket_product_id` remains `null` until the exact Cardmarket product/version has been verified. V51 never guesses an ID from name alone.

When a verified ID exists on an `owned` record, or on an `incoming` record, the wrapper adds that ID to the effective V50.1 `owned_ids` filter before scoring. Existing legacy `owned_ids` in the profile are preserved.

## Validation

`test_collection_integration.py` checks the real baseline counts, exact-ID filtering, incoming filtering, legacy compatibility, duplicate-key detection, total consistency and invalid-ID rejection.
