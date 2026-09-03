# V50.1 · Personal Singles Radar

## Why this exists

V50 shadow proved that aggregate Cardmarket data is useful for finding unusual market movement, but it also exposed a critical mismatch: aggregate `trend`, `avg7`, `avg30` and especially `low` are not guaranteed to represent a concrete English, NM, EU/EEA offer that ships to Denmark.

The live Pikachu Delta Species HP79 check on 2026-09-03 is the reference example. Aggregate trend was about EUR 3.98, while the visible English NM EU offers started materially higher. Therefore aggregate market reference must not be treated as purchase price or compared directly with the user's 75 DKK purchase budget.

## V50.1 rules

- Restock Core is unchanged.
- The personal layer remains shadow-only: no Discord messages, no network calls, no state writes.
- `low` remains diagnostic only and has zero score weight.
- `trend`/`avg7`/`avg30` are market context, never a purchase-price claim.
- The purchase budget is metadata until a concrete offer is verified.
- Strongest aggregate-only status is `REVIEW`, meaning manual listing inspection is required.
- Only personal candidates enter scoring: wishlist/manual-priority IDs or configured priority/secondary Pokemon.
- Code cards and other explicit online-code products are filtered before scoring.
- Low-confidence aggregate data cannot receive `REVIEW`.
- Shadow output is narrowed to the top 10 candidates.

## Purchase verification remains external

A purchase-grade signal still requires a concrete listing that verifies all of the following:

1. Exact Cardmarket product/version.
2. English language.
3. MT/NM condition.
4. EU/EEA seller.
5. Shipping to Denmark.
6. Real purchase/landed price within the user's chosen target.

Without offer-level Cardmarket API access, V50.1 intentionally does not infer these fields.

## Decision boundary

V50.1 is successful if it produces a small set of personally relevant cards worth opening on Cardmarket. It is not intended to answer "buy this now". If manual checks continue to show that the radar does not save meaningful time, the personal singles automation should stop here rather than grow into a larger scraping system.
