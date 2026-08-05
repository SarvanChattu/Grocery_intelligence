r"""
99_repair_item_names.py — one-off repair (Session 3)
The typo Replace-All ran on the whole sheet instead of only clean_name,
so 4 raw join keys in product_master.csv were corrected out of existence.
This restores item_name for exactly those 4 rows, from the untouched source.
clean_name keeps the fixed spellings — that column was SUPPOSED to change.

Run once from the project root:  python etl\99_repair_item_names.py
"""

import re
from pathlib import Path

import pandas as pd

REF = Path("data/reference")

source = pd.read_csv(REF / "invoice_product_summary.csv")
master = pd.read_csv(REF / "product_master.csv", encoding="utf-8-sig")

# Rebuild item names EXACTLY as etl 01 does (whitespace collapse + free-suffix
# strip), so we compare like with like — the master never contained the
# "(Free ...)" suffixes by design.
free_pat = re.compile(r"\s*\(free[^)]*\)\s*", flags=re.IGNORECASE)
raw_names = set(
    source["Item Name"]
    .str.strip()
    .str.replace(r"\s+", " ", regex=True)
    .str.replace(free_pat, " ", regex=True)
    .str.strip()
)

# The forward mapping that was (wrongly) applied to item_name:
FIXES = [("PRESSER", "PRESSURE"), ("JUNIER", "JUNIOR"), ("SENIER", "SENIOR")]


def apply_fixes(name: str) -> str:
    for a, b in FIXES:
        name = name.replace(a, b)
    return name


repaired = 0
for raw in sorted(raw_names - set(master["item_name"])):
    mapped = apply_fixes(raw)  # what the broken master row says now
    hit = master["item_name"] == mapped
    if hit.sum() == 1:
        master.loc[hit, "item_name"] = raw  # restore the raw join key
        repaired += 1
        print(f"restored: {raw}")
    else:
        print(f"COULD NOT REPAIR (matches={int(hit.sum())}): {raw}")

still_missing = raw_names - set(master["item_name"])
print("-" * 50)
print(f"repaired rows        : {repaired}")
print(f"still unmatched      : {len(still_missing)}")
if not still_missing:
    master.to_csv(REF / "product_master.csv", index=False, encoding="utf-8-sig")
    print("product_master.csv saved — rerun the star schema build.")
else:
    print("NOT saved — send me this output.")
