"""
01_clean_summary.py — Session 2
Reads data/reference/invoice_product_summary.csv (514 rows) and produces:
  data/reference/supplier_master.csv        (10 suppliers, IDs + anonymous names)
  data/reference/product_master_draft.csv   (501 products — YOU review, then save as product_master.csv)
  data/processed/clean_summary.csv          (cleaned rows + flags)
  data/processed/product_invoice_bridge.csv (one row per product-invoice pair)

Run from the project root:  python etl\01_clean_summary.py
"""

import re
from pathlib import Path

import pandas as pd

REF = Path("data/reference")
OUT = Path("data/processed")
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 1. LOAD
# Rename by exact header (never by position — positions break silently).
df = pd.read_csv(REF / "invoice_product_summary.csv")
df = df.rename(
    columns={
        "Item Name": "item_name_raw",
        "Latest Product Price (INR)": "latest_price_inr",
        "Quantity Till Date": "qty_till_date",
        "Total Product Price (INR)": "total_price_inr",
        "Date (latest purchase)": "latest_purchase_date",
        "Company": "supplier_raw",
        "Invoice(s)": "invoices_raw",
    }
)
# Dates: parse strictly in the expected "09-Nov-2023" format first; for any
# leftovers, retry assuming European day-first order (covers Excel resaves
# like "09/11/2023"). Anything STILL unparseable is printed and stops the
# script — bad dates must be fixed, never silently dropped.
raw_dates = df["latest_purchase_date"].astype(str).str.strip()
parsed = pd.to_datetime(raw_dates, format="%d-%b-%Y", errors="coerce")
if parsed.isna().any():
    fallback = pd.to_datetime(raw_dates, dayfirst=True, errors="coerce")
    parsed = parsed.fillna(fallback)
bad = df[parsed.isna()]
if len(bad):
    print("UNPARSEABLE DATES — fix these rows in the CSV, then rerun:")
    print(bad[["item_name_raw", "latest_purchase_date"]].to_string())
    raise SystemExit(1)
df["latest_purchase_date"] = parsed

# Normalize whitespace once, everywhere it can hide.
for col in ["item_name_raw", "supplier_raw"]:
    df[col] = df[col].str.strip().str.replace(r"\s+", " ", regex=True)

# ---------------------------------------------------------------- 2. FREE ITEMS
# Decision log 2026-08-01: keep them, flag them, exclude from price measures.
free_pat = re.compile(r"\s*\(free[^)]*\)\s*", flags=re.IGNORECASE)
df["is_free_item"] = df["item_name_raw"].str.contains(free_pat)
df["item_name"] = (
    df["item_name_raw"].str.replace(free_pat, " ", regex=True).str.strip()
)

# ---------------------------------------------------------------- 3. PACK SIZE
# Pull "3.5 LTR", "500 GM", "22CM", "50MM"... out of the name.
# Heuristic: first number+unit found. You correct edge cases in the draft review.
unit_pat = re.compile(
    r"(\d+(?:\.\d+)?)\s*(LTR|LITRE|LIT|KG|GM|ML|CM|MM|L|G)\b", re.IGNORECASE
)
UNIT_ALIASES = {"LTR": "L", "LITRE": "L", "LIT": "L", "GM": "G"}


def extract_unit(name: str):
    m = unit_pat.search(name)
    if not m:
        return pd.NA, pd.NA
    size = float(m.group(1))
    unit = m.group(2).upper()
    return size, UNIT_ALIASES.get(unit, unit)


df[["unit_size", "unit_type"]] = df["item_name"].apply(
    lambda n: pd.Series(extract_unit(n))
)

# ---------------------------------------------------------------- 4. BRAND
# Draft list from what we saw in the data — extend it during your review.
BRANDS = [
    "RAJ MATHA", "V SMART", "VIS", "PREMIER", "PREETHI",
    "SOWBAGHYA", "MAYURA", "BUTTERFLY", "PRESTIGE", "DIAMOND",
]


def extract_brand(name: str):
    up = name.upper()
    for b in BRANDS:
        if up.startswith(b + " ") or up.startswith(b + "."):
            return b
    return pd.NA


df["brand"] = df["item_name"].map(extract_brand)

# ---------------------------------------------------------------- 5. SUPPLIER MASTER
suppliers = sorted(df["supplier_raw"].unique())
sup = pd.DataFrame({"supplier_raw": suppliers})
sup["supplier_id"] = [f"S{i:02d}" for i in range(1, len(sup) + 1)]
sup["anon_name"] = [f"Supplier {chr(64 + i)}" for i in range(1, len(sup) + 1)]
sup.to_csv(REF / "supplier_master.csv", index=False)

# ---------------------------------------------------------------- 6. PRODUCT MASTER (draft)
# One row per product (a product bought from two suppliers is still ONE product —
# that identity is exactly what makes supplier comparison possible).
CATEGORY_RULES = [
    ("Appliances", ["GRINDER", "MIXER", "MIXIE", "TOASTER", "KETTLE", "STOVE",
                    "INDUCTION COOKTOP", "230V", "WATT", "ELECTRIC"]),
    ("Kitchenware", ["COOKER", "PAN", "POT", "IDLI", "IDLY", "PANIYARAM",
                     "APPACHATTY", "APPACHETTY", "TAWA", "KADAI", "SANCHA",
                     "MURUKKU", "MURAM", "SPOON", "PLATE", "BOX", "DRUM",
                     "VESSEL", "URULI", "CHATTY", "LID", "COOKWARE", "BOWL",
                     "STEAMER", "HANDY", "UTENSILS"]),
    ("Grocery", ["RICE", "DAL", "FLOUR", "MASALA", "SPICE", "OIL", "PICKLE",
                 "JAGGERY", "MILLET", "PAPAD"]),
    ("Beverages", ["TEA", "COFFEE", "JUICE", "DRINK", "SODA"]),
    # Draft guess from the Sri Durga Handicrafts items — rename or merge
    # this category as YOU see fit; it's a domain decision, log it.
    ("Pooja & Handicrafts", ["VILAKKU", "LAMP", "KUTHU", "POOJA", "SAMBRANI"]),
]


def guess_category(name: str):
    up = name.upper()
    for cat, keywords in CATEGORY_RULES:
        for k in keywords:
            # \b = word boundary: "TEA" must be the word TEA,
            # not three letters hiding inside "STEAMER".
            if re.search(rf"\b{re.escape(k)}\b", up):
                return cat
    return "REVIEW"  # the script admits what it doesn't know — you decide


prods = (
    df[["item_name", "brand", "unit_size", "unit_type"]]
    .drop_duplicates(subset=["item_name"])
    .sort_values("item_name")
    .reset_index(drop=True)
)
prods["product_id"] = [f"P{i:04d}" for i in range(1, len(prods) + 1)]
prods["category"] = prods["item_name"].map(guess_category)
# clean_name is where YOU fix typos by hand (PRESSER -> PRESSURE, JUNIER -> JUNIOR...).
prods["clean_name"] = prods["item_name"]
prods = prods[["product_id", "item_name", "clean_name", "brand",
               "category", "unit_size", "unit_type"]]
prods.to_csv(REF / "product_master_draft.csv", index=False)

# ---------------------------------------------------------------- 7. INVOICE BRIDGE
# Explode "2404; 4878" into one row per product-invoice pair. Provenance survives.
bridge = df[["item_name", "supplier_raw", "invoices_raw"]].copy()
bridge["invoice_id"] = bridge["invoices_raw"].astype(str).str.split(";")
bridge = bridge.explode("invoice_id")
bridge["invoice_id"] = bridge["invoice_id"].str.strip()
bridge = bridge.drop(columns="invoices_raw")
bridge.to_csv(OUT / "product_invoice_bridge.csv", index=False)

# ---------------------------------------------------------------- 8. FLAGS + SAVE
# Rows where latest_price x qty != total span invoices with different prices.
calc = df["latest_price_inr"] * df["qty_till_date"]
df["has_price_change"] = (calc - df["total_price_inr"]).abs() > 0.5
df.to_csv(OUT / "clean_summary.csv", index=False)

# ---------------------------------------------------------------- 9. REPORT
print("=" * 52)
print("CLEANING REPORT")
print("=" * 52)
print(f"rows in / out            : {len(df)} / {len(df)}")
print(f"suppliers                : {len(sup)}")
print(f"unique products          : {len(prods)}")
print(f"free items flagged       : {int(df['is_free_item'].sum())}")
print(f"pack size extracted      : {int(df['unit_size'].notna().sum())} rows")
print(f"brand identified         : {int(df['brand'].notna().sum())} rows")
print(f"price-change rows        : {int(df['has_price_change'].sum())}")
print(f"invoice-bridge rows      : {len(bridge)}")
review = int((prods['category'] == 'REVIEW').sum())
print(f"categories needing YOU   : {review}  -> open product_master_draft.csv")
print("=" * 52)
