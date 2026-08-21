from pathlib import Path

PATH = Path("patch_v40_matching_opportunity.py")
text = PATH.read_text(encoding="utf-8")
original = text

# V40 was generated with a few replacement markers where a literal "\\n"
# accidentally became a physical newline inside the patch string. That makes
# the patch look for code that does not exist in restock_bot_github.py.
# Repair the patch source itself before V40 runs. This is idempotent and does
# not touch scanner state/history.
text = text.replace('f"\\\\\n🔗 ', 'f"\\\\n🔗 ')
text = text.replace('f"\\\\\n🎯 ', 'f"\\\\n🎯 ')
text = text.replace('+ "\\\\\n".join(ranking_lines)', '+ "\\\\n".join(ranking_lines)')

if text != original:
    PATH.write_text(text, encoding="utf-8")
    print("Repaired V40 literal-newline replacement markers")
else:
    print("V40 replacement markers already repaired")
