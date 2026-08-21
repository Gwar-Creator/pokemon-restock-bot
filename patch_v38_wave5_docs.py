from pathlib import Path

PATH = Path("AGENTS.md")
text = PATH.read_text(encoding="utf-8")

MARKER = "Wave 5-udvidelsen fra 2026-08-21"
if MARKER in text:
    print("Wave 5 documentation already applied")
    raise SystemExit(0)

old_sources = (
    "Scannerens nuværende aktive kilder omfatter Coolshop, Proshop, BR, Bilka, Føtex, "
    "PokeHulen, Rogerz, MTGwebshop, Luckbox, Spilforsyningen, Musen & Slottet, Symbizon, "
    "CardX, Matraws, Halmes Hule, CardsDirect, Baltzer Games, TCG Shoppen, Pokemons.dk, "
    "Pocket Monster, Fun-shop, PokéPulls, Staalz, PBCards, KoCardz, Nostalgic, &Cards, "
    "Pokecards.dk, Epic Panda, Steffen-O og Next Level Games."
)
new_sources = (
    "Scannerens nuværende aktive kilder omfatter Coolshop, Proshop, BR, Bilka, Føtex, "
    "PokeHulen, Rogerz, MTGwebshop, Luckbox, Spilforsyningen, Musen & Slottet, Symbizon, "
    "CardX, Matraws, Halmes Hule, CardsDirect, Baltzer Games, TCG Shoppen, Pokemons.dk, "
    "Pocket Monster, Fun-shop, PokéPulls, Staalz, PBCards, KoCardz, Vaulted, Pokedexet, "
    "Pokemonportalen, TCGBruuS, Pokemon Plaza, Kelz0r, Faraos, Goblin Games, ZZGames, "
    "Hyggeonkel, Nostalgic, &Cards, Pokecards.dk, Epic Panda, Steffen-O og Next Level Games."
)
if old_sources not in text:
    raise RuntimeError("Wave 5 docs failed: active source list marker not found")
text = text.replace(old_sources, new_sources, 1)

anchor = (
    "PokéPulls og Staalz bruger bredere Shopify-feeds med automatisk game-detection "
    "og de eksisterende sealed-/sprogfiltre."
)
addition = anchor + (
    "\n\nWave 4-udvidelsen fra 2026-08-21 tilføjede Vaulted, Pokedexet, Pokemonportalen, "
    "TCGBruuS og Pokemon Plaza med platformstilpassede feeds/parsers."
    "\n\nWave 5-udvidelsen fra 2026-08-21 tilføjer Kelz0r, Faraos, Goblin Games, ZZGames "
    "og Hyggeonkel. ZZGames bruger Shopify-feed; de øvrige bruger målrettede offentlige "
    "kategori-parsers og de eksisterende sealed-/English-only-filtre. Bog & idé blev "
    "bevidst udskudt, fordi webshoppen var midlertidigt password-lukket under platformsmigrering "
    "21/8, og Bræt & Brikker blev ikke tilføjet, fordi butikken er lukket."
)
if anchor not in text:
    raise RuntimeError("Wave 5 docs failed: Wave 3 paragraph marker not found")
text = text.replace(anchor, addition, 1)

log_anchor = (
    "- 2026-08-21: V31 tilføjede Fun-shop, PokéPulls, Staalz, PBCards og KoCardz som Wave 3-kilder "
    "med platformstilpassede feeds og uden at ændre de eksisterende sealed-/sprogfiltre."
)
log_line = (
    log_anchor
    + "\n- 2026-08-21: V38 tilføjede Kelz0r, Faraos, Goblin Games, ZZGames og Hyggeonkel "
      "som den sidste butiksekspansions-wave for nu; Bog & idé blev udskudt under "
      "platformsmigrering, og Bræt & Brikker blev fravalgt som lukket."
)
if log_anchor in text:
    text = text.replace(log_anchor, log_line, 1)

PATH.write_text(text, encoding="utf-8")
print("Documented Wave 5 retailer expansion")