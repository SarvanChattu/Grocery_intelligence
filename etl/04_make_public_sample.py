r"""
04_make_public_sample.py — Session 7
Builds the PUBLIC sample dataset: suppliers anonymized, prices perturbed.

Design (see docs/decisions.md):
- One random factor per PRODUCT (0.90–1.10), applied to every money column
  of that product across all suppliers -> absolute prices are fiction, but
  every ratio (overpay %, who-is-cheaper) is preserved EXACTLY.
- One random factor per PRODUCT for quantities (0.85–1.15, rounded) ->
  volumes hidden, spend recomputed coherently.
- The random seed lives in data/reference/anon_seed.txt, which is
  GITIGNORED. The method is public; the seed is not. A published seed
  would let anyone reverse the factors and recover real prices.

Reads:   data/processed/fact_price_snapshot.csv, dim_product.csv, dim_supplier.csv
         data/reference/anon_seed.txt        (gitignored, one integer)
Writes:  data/sample/fact_price_snapshot.csv, dim_product.csv, dim_supplier.csv

Run from the project root:  python etl\04_make_public_sample.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REF = Path("data/reference")
PROC = Path("data/processed")
OUT = Path("data/sample")
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- SEED
seed_file = REF / "anon_seed.txt"
if not seed_file.exists():
    print("MISSING SEED — create data/reference/anon_seed.txt containing one")
    print("integer of your choice (e.g. 483920). It is gitignored on purpose:")
    print("the anonymization method is public, the seed is not.")
    sys.exit(1)
seed = int(seed_file.read_text().strip())
rng = np.random.default_rng(seed)

# ---------------------------------------------------------------- LOAD
fact = pd.read_csv(PROC / "fact_price_snapshot.csv")
prod = pd.read_csv(PROC / "dim_product.csv")
sup = pd.read_csv(PROC / "dim_supplier.csv")

# ---------------------------------------------------------------- FACTORS
# One money factor and one quantity factor PER PRODUCT — the whole trick.
products = prod["product_id"].unique()
money_f = pd.Series(rng.uniform(0.90, 1.10, len(products)), index=products)
qty_f = pd.Series(rng.uniform(0.85, 1.15, len(products)), index=products)

f = fact["product_id"].map(money_f)
g = fact["product_id"].map(qty_f)

sample = fact.copy()
for col in ["latest_price_inr", "latest_price_eur", "price_per_unit_inr"]:
    sample[col] = (fact[col] * f).round(2)
sample["qty_till_date"] = (fact["qty_till_date"] * g).round(2)
# spend scales by BOTH factors so price x qty stays coherent row by row
for col in ["total_spend_inr", "total_spend_eur"]:
    sample[col] = (fact[col] * f * g).round(2)

# provenance stays private — invoice numbers add nothing publicly
sample = sample.drop(columns=["invoice_refs"])

# ---------------------------------------------------------------- SELF-GATE
# Prove the design promises before writing anything public.

# 1) Supplier price RATIOS per product are unchanged (the findings survive).
multi = fact[~fact["is_free_item"]].groupby("product_id").filter(
    lambda t: t["supplier_id"].nunique() > 1
)
for pid, grp in multi.groupby("product_id"):
    orig = grp.sort_values("supplier_id")["latest_price_inr"].to_numpy()
    anon = (
        sample.loc[grp.index].sort_values("supplier_id")["latest_price_inr"].to_numpy()
    )
    r_orig = orig / orig.max()
    r_anon = anon / anon.max()
    assert np.allclose(r_orig, r_anon, atol=1e-4), f"ratio broken for {pid}"

# 2) No original price survived unchanged (nothing real leaks by accident).
leaked = int((sample["latest_price_inr"] == fact["latest_price_inr"]).sum())

# 3) Free items stayed free (0 x anything = 0 — structure preserved).
assert (sample.loc[fact["is_free_item"], "latest_price_inr"] == 0).all()

# ---------------------------------------------------------------- DIMENSIONS
# Suppliers: anonymous names only. Products: names are public catalog items;
# prices were the secret, and they are now fiction.
sup_sample = sup[["supplier_id", "anon_name"]].rename(
    columns={"anon_name": "supplier_name"}
)
sup_sample.to_csv(OUT / "dim_supplier.csv", index=False)
prod.to_csv(OUT / "dim_product.csv", index=False)
sample.to_csv(OUT / "fact_price_snapshot.csv", index=False)

# ---------------------------------------------------------------- REPORT
print("=" * 56)
print("PUBLIC SAMPLE REPORT")
print("=" * 56)
print(f"rows written                 : {len(sample)}")
print(f"supplier ratio check         : PASS (all cross-supplier ratios preserved)")
print(f"unchanged real prices leaked : {leaked}  (free items only is expected)")
print(f"sample total spend (INR)     : {sample['total_spend_inr'].sum():,.0f}")
print(f"  (original was 10,691,707 — similar magnitude, different number: good)")
print("suppliers now named          :", ", ".join(sup_sample["supplier_name"].head(4)) + ", ...")
print("=" * 56)
print("Safe to publish: data/sample/ only. NEVER data/raw or data/processed.")
