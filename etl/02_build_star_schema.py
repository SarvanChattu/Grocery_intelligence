"""
02_build_star_schema.py — Session 3
Turns the cleaned data + YOUR reviewed masters into the three star-schema files
that Power BI will load.

Reads:   data/processed/clean_summary.csv       (machine output of etl 01)
         data/reference/product_master.csv      (your reviewed judgment)
         data/reference/supplier_master.csv
Writes:  data/processed/dim_product.csv
         data/processed/dim_supplier.csv
         data/processed/fact_price_snapshot.csv

Run from the project root:  python etl\02_build_star_schema.py
"""

import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------- CONFIG
# Look up the CURRENT rate ("1 INR in EUR" on ecb.europa.eu or xe.com),
# update this number, and log value + date + source in docs/decisions.md.
# v1 uses one flat rate (documented approximation); v2 will use monthly rates.
EUR_PER_INR = 0.0091  # <-- PLACEHOLDER — update me before running

REF = Path("data/reference")
OUT = Path("data/processed")

# ---------------------------------------------------------------- LOAD
clean = pd.read_csv(OUT / "clean_summary.csv", parse_dates=["latest_purchase_date"])
# utf-8-sig: your Excel "CSV UTF-8" save adds an invisible BOM marker at the
# start of the file; this encoding strips it so the first column name is clean.
prod = pd.read_csv(REF / "product_master.csv", encoding="utf-8-sig")
sup = pd.read_csv(REF / "supplier_master.csv", encoding="utf-8-sig")

# ---------------------------------------------------------------- GATE
# A warehouse refuses bad inputs at the door. Fail loudly, list the problems.
problems = []
if EUR_PER_INR == 0.0100:
    problems.append("EUR_PER_INR is still the placeholder rate — update it (and decisions.md)")
n_review = int((prod["category"] == "REVIEW").sum())
if n_review:
    problems.append(f"product_master.csv still has {n_review} REVIEW categories")
missing_prod = sorted(set(clean["item_name"]) - set(prod["item_name"]))
if missing_prod:
    problems.append(f"{len(missing_prod)} item names not found in product_master, e.g. {missing_prod[:3]}")
missing_sup = sorted(set(clean["supplier_raw"]) - set(sup["supplier_raw"]))
if missing_sup:
    problems.append(f"{len(missing_sup)} suppliers not found in supplier_master: {missing_sup}")

if problems:
    print("INPUT GATE FAILED — fix these, then rerun:")
    for p in problems:
        print("  -", p)
    sys.exit(1)

# ---------------------------------------------------------------- DIMENSIONS
# dim_product: the reviewed master IS the dimension — your judgment, not the
# raw strings. clean_name becomes the display name the dashboard shows.
dim_product = prod[
    ["product_id", "clean_name", "brand", "category", "unit_size", "unit_type"]
].rename(columns={"clean_name": "product_name"})
dim_product.to_csv(OUT / "dim_product.csv", index=False)

dim_supplier = sup[["supplier_id", "supplier_raw", "anon_name"]].rename(
    columns={"supplier_raw": "supplier_name"}
)
dim_supplier.to_csv(OUT / "dim_supplier.csv", index=False)

# ---------------------------------------------------------------- FACT
# Grain: one row = one product from one supplier (latest-price snapshot).
# Names are swapped for IDs — names live in dimensions, keys live in facts.
fact = (
    clean.drop(columns=["unit_size", "unit_type", "brand"])  # master's values win
    .merge(prod[["item_name", "product_id", "unit_size"]], on="item_name", how="left")
    .merge(sup[["supplier_raw", "supplier_id"]], on="supplier_raw", how="left")
)

fact["latest_price_eur"] = (fact["latest_price_inr"] * EUR_PER_INR).round(4)
fact["total_spend_inr"] = fact["total_price_inr"]
fact["total_spend_eur"] = (fact["total_spend_inr"] * EUR_PER_INR).round(2)
# Comparable price across pack sizes (per litre / per kg / per piece):
fact["price_per_unit_inr"] = (
    fact["latest_price_inr"] / fact["unit_size"].where(fact["unit_size"] > 0)
).round(2)

fact = fact[
    [
        "product_id", "supplier_id", "latest_purchase_date",
        "qty_till_date", "latest_price_inr", "latest_price_eur",
        "price_per_unit_inr", "total_spend_inr", "total_spend_eur",
        "is_free_item", "has_price_change", "invoices_raw",
    ]
].rename(columns={"invoices_raw": "invoice_refs"})
fact.to_csv(OUT / "fact_price_snapshot.csv", index=False)

# ---------------------------------------------------------------- RECONCILIATION
# Prove the pipeline against the untouched source — to the rupee.
orig = pd.read_csv(REF / "invoice_product_summary.csv")
src_total = orig["Total Product Price (INR)"].sum()
fact_total = fact["total_spend_inr"].sum()
recon_ok = abs(src_total - fact_total) < 0.01

multi = fact.loc[~fact["is_free_item"]].groupby("product_id")["supplier_id"].nunique()
cross_supplier = int((multi > 1).sum())

spend_by_cat = (
    fact.merge(dim_product[["product_id", "category"]], on="product_id")
    .groupby("category")["total_spend_inr"].sum()
    .sort_values(ascending=False)
)

print("=" * 56)
print("STAR SCHEMA REPORT")
print("=" * 56)
print(f"fact rows                    : {len(fact)}")
print(f"dim_product rows             : {len(dim_product)}")
print(f"dim_supplier rows            : {len(dim_supplier)}")
print(f"null keys in fact            : {int(fact[['product_id','supplier_id']].isna().sum().sum())}")
print(f"total spend (INR)            : {fact_total:,.2f}")
print(f"total spend (EUR @ {EUR_PER_INR}) : {fact['total_spend_eur'].sum():,.2f}")
print(f"products from >1 supplier    : {cross_supplier}")
print(f"reconciliation vs source     : {'PASS - matches to the rupee' if recon_ok else 'FAIL'}")
print("-" * 56)
print("spend by category (INR):")
for cat, v in spend_by_cat.items():
    print(f"  {cat:<22} {v:>14,.0f}")
print("=" * 56)
if not recon_ok:
    print(f"source says {src_total:,.2f} — investigate before continuing.")
    sys.exit(1)
