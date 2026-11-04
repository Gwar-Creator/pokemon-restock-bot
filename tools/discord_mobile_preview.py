#!/usr/bin/env python3
"""Offline mobile-width Discord previews using actual production renderers.

Fixtures are synthetic, not live listings. No API calls, webhooks or state.
Run: python -m tools.discord_mobile_preview
"""
from __future__ import annotations

import os
import textwrap

from discord_v2_hot_adapter import hot_payload
from discord_v2_salling_adapter import (
    early_radar_event, hidden_stock_event, local_stock_event, preview_payload,
)
from personal.singles_discord_notify import embed_for as singles_embed
from test_main_restock_discord_presentation import formatter_namespace
from vintage_marketplace_live import payload as vintage_payload

URL = "https://example.org/eksempel"
NAME = "EKSEMPEL – Pokémon 151 Booster Bundle"
EXAMPLE_NOTE = (
    "**Kun syntetiske eksempler fra eksisterende renderere.** "
    "Ingen virkelige tilbud, priser eller lagerdata. Ingen beskeder sendes."
)
WIDTH = 52


def case_payloads():
    """Names, expected statuses and real renderer payloads; no send functions."""
    product = {"name": NAME, "url": URL, "price": 299, "fetch_via": "live_reader"}
    cases = []
    cases.append(("HOT · Coolshop online", "BUY_NOW",
                  hot_payload("coolshop", {**product, "online_stock": True}, "RESTOCK")[0]))
    cases.append(("HOT · Proshop bestillingsvare", "UNKNOWN",
                  hot_payload("proshop", {**product, "stock": "BESTILLINGSVARE"}, "RESTOCK")[0]))
    cases.append(("HOT · BR online systemlager", "UNKNOWN",
                  hot_payload("br", {**product, "online_count": 8, "is_exposed": True}, "RESTOCK")[0]))
    cases.append(("HOT · Bilka butikslager", "STORE_STOCK",
                  hot_payload("bilka", {**product, "online_count": 3,
                      "local_stocks": {"123": {"name": "Bilka Kolding", "stock": 2}}}, "RESTOCK")[0]))
    cases.append(("HOT · Proshop forudbestilling", "PREORDER",
                  hot_payload("proshop", {**product, "preorder": True}, "NEW")[0]))
    cases.append(("Local · BR Kolding", "STORE_STOCK",
                  preview_payload(local_stock_event(
                      {"site": "BR", "name": NAME, "price": 299, "url": URL,
                       "visibility": "EXPOSED", "sku": "EXAMPLE-SKU"},
                      [{"name": "BR Kolding", "old": 0, "new": 3}]))))
    cases.append(("Hidden · BR Kolding", "PREPUBLISH",
                  preview_payload(hidden_stock_event([
                      {"site": "br", "name": NAME, "price": 299, "url": URL,
                       "store": "BR Kolding", "stock": 3, "product_id": "demo",
                       "sku": "EXAMPLE-SKU"}]))))
    cases.append(("Early Radar · Bilka skjult", "PREPUBLISH",
                  preview_payload(early_radar_event(
                      "KATALOGFUND",
                      {"name": NAME, "id": "demo", "sku": "EXAMPLE-SKU",
                       "sites": {"bilka": {"is_exposed": False, "url": URL}}},
                      "Katalogsignal, ikke bestillingsbekræftelse", "bilka"))))
    main = formatter_namespace()["_discord_product_embed"]
    cases.append(("Restock · nyt katalogfund", "CATALOG",
                  {"username": "MasterBot", "allowed_mentions": {"parse": []},
                   "embeds": [main(
                       "🆕 **[POKÉMON] NYT PÅ BR**\n"
                       "**EKSEMPEL – Pokémon 151 Booster Bundle**\n"
                       "📦 Nyt katalogfund\n"
                       "🔗 https://example.org/eksempel")]}))
    cases.append(("Restock · forudbestilling", "PREORDER",
                  {"username": "MasterBot", "allowed_mentions": {"parse": []},
                   "embeds": [main(
                       "🚨 **[POKÉMON] NY FORUDBESTILLING HOS PROSHOP**\n"
                       "**EKSEMPEL – Illustration Collection**\n"
                       "📅 Forudbestilling\n"
                       "🔗 https://example.org/eksempel")]}))
    row = {
        "id": "demo", "name": "Umbreon", "set": "Undaunted",
        "canonical_rarity": "Holo Rare", "listing_signal": "RADAR_ONLY",
        "reference_dkk": 200, "purchase_budget_dkk": 150,
        "trend_vs_avg30_pct": -12, "score": 79, "alert_reason": "NEW_REVIEW",
    }
    meta = {"demo": {"canonical_name": "Umbreon", "canonical_number": "10",
                     "source_set_id": "hgss3"}}
    cases.append(("Cardmarket · kun prisreference", "REVIEW",
                  {"username": "MasterBot", "allowed_mentions": {"parse": []},
                   "embeds": [singles_embed(row, meta)]}))
    cases.append(("Cardmarket · konkret REVIEW", "REVIEW",
                  {"username": "MasterBot", "allowed_mentions": {"parse": []},
                   "embeds": [singles_embed({
                       **row, "listing_signal": "LISTING_REVIEW",
                       "listing_total_dkk": 185, "alert_reason": "EXACT_LISTING",
                   }, meta)]}))
    cases.append(("Vintage Finder · udvalgt fund", "REVIEW",
                  vintage_payload({
                      "title": "EKSEMPEL – Gym Heroes vintage lot",
                      "verification": "UNVERIFIED", "tier": "VINTAGE_LOT",
                      "url": "https://www.tradera.com/item/1001342/1234567/demo",
                      "image": "https://img.tradera.net/images/example.jpeg",
                      "price_label": "Næste bud", "price_sek": "150", "photo_count": 4,
                  })))
    return cases


def display_lines(text, prefix=""):
    """Wrap for an approximately 390 px phone; preserve source line boundaries."""
    lines = []
    for source_line in str(text or "").splitlines():
        cleaned = source_line.replace("**", "").replace(chr(96), "").strip()
        if not cleaned:
            continue
        lines.extend(textwrap.wrap(
            prefix + cleaned, width=WIDTH, break_long_words=True,
            break_on_hyphens=False,
        ) or [""])
    return lines


def preview_markdown(cases=None):
    cases = case_payloads() if cases is None else cases
    fence = chr(96) * 3
    result = [
        "# Discord V2 – mobilforhåndsvisning",
        "",
        EXAMPLE_NOTE,
        "",
        "Fremstillet offline fra de aktive formatteringsfunktioner. "
        "Tekstbredden simulerer en smal mobilskærm, ikke et Discord-screenshot.",
        "",
    ]
    for label, status, payload in cases:
        result.extend((f"### {label} — {status}", "", fence + "text"))
        embed = payload["embeds"][0]
        result.extend(display_lines(embed.get("title") or ""))
        result.append("-" * 32)
        result.extend(display_lines(embed.get("description") or ""))
        for field in embed.get("fields") or []:
            result.extend(display_lines(str(field["name"]) + ":"))
            result.extend(display_lines(field.get("value") or "", prefix="  "))
        result.append("PRODUKTLINK: " + ("JA" if embed.get("url") else "NEJ"))
        result.extend((fence, ""))
    return "\n".join(result)


def main():
    output = preview_markdown()
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as file:
            file.write(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
