#!/usr/bin/env python3
"""Fix categorisation for company_ocbc_real_statements directly in SQLite."""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "packages", "db", "dev.sqlite")
COMPANY_ID = "company_ocbc_real_statements"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

rows = cur.execute(
    "SELECT transaction_id, date, description, debit, credit, category, subcategory, is_taxable "
    "FROM transactions WHERE company_id = ?", (COMPANY_ID,)
).fetchall()

updates = []

for r in rows:
    tid = r["transaction_id"]
    desc = (r["description"] or "").upper()
    debit = r["debit"] or 0
    credit = r["credit"] or 0
    is_deposit = credit > 0
    old_cat = r["category"]
    old_sub = r["subcategory"]

    new_cat = None
    new_sub = None
    new_taxable = None

    # Director deposits → transfer (not revenue)
    if "TURRELL CRAIG JOHN" in desc and is_deposit:
        new_cat, new_sub, new_taxable = "transfer", None, 1

    # eBay → inventory/COGS
    elif "EBAY" in desc and not is_deposit:
        new_cat, new_sub, new_taxable = "expense", "inventory_cogs", 1

    # Large Isetan GIRO withdrawals = cash stock purchases
    elif "ISETAN" in desc and not is_deposit and debit > 1000:
        new_cat, new_sub, new_taxable = "expense", "inventory_cogs", 1

    # Phuket personal travel
    elif any(x in desc for x in ["HIDEAWAY PHU", "ZURICH BREAD CAFE-PHUK", "KING POWER TAX FR"]):
        new_cat, new_sub, new_taxable = "expense", "non_deductible", 0
    elif "JETSTAR" in desc and "THB" in desc:
        new_cat, new_sub, new_taxable = "expense", "non_deductible", 0

    # Beatport (personal music)
    elif "BEATPORT" in desc and not is_deposit:
        new_cat, new_sub, new_taxable = "expense", "non_deductible", 0

    # Supermarket/grocery → personal
    elif any(x in desc for x in [
        "ISETAN (SUPERMARKET)", "TOP CHOICE SUPERMARKET", "COLD STORAGE",
        "FP XTRA", "AVM SUPERMART"
    ]):
        new_cat, new_sub, new_taxable = "expense", "non_deductible", 0

    # ZARA → personal clothing
    elif "ZARA" in desc and not is_deposit:
        new_cat, new_sub, new_taxable = "expense", "non_deductible", 0

    # Clinic charges → personal medical
    elif "CLINIC CHARGES" in desc:
        new_cat, new_sub, new_taxable = "expense", "non_deductible", 0

    # M&S → personal clothing
    elif ("M & S -" in desc or "MARKS & SPENCER" in desc) and not is_deposit:
        new_cat, new_sub, new_taxable = "expense", "non_deductible", 0

    # TGP LIVING → personal lifestyle
    elif "TGP LIVING" in desc:
        new_cat, new_sub, new_taxable = "expense", "non_deductible", 0

    # VictoriaEnso transfers → contractor_payments
    elif "VICTORIAENS" in desc and not is_deposit and old_sub in (None, "operating_expense", "salary_wages"):
        new_cat, new_sub, new_taxable = "expense", "contractor_payments", 1

    if new_cat and (new_cat != old_cat or new_sub != old_sub):
        updates.append((new_cat, new_sub, new_taxable, tid))

print(f"Applying {len(updates)} updates to {COMPANY_ID}...")

cur.executemany(
    "UPDATE transactions SET category = ?, subcategory = ?, is_taxable = ? WHERE transaction_id = ?",
    updates
)

# Clear stale financial summaries so they get recomputed
cur.execute("DELETE FROM financial_summaries WHERE company_id = ?", (COMPANY_ID,))

conn.commit()

# Verify
print("\nUpdated breakdown:")
for row in cur.execute("""
    SELECT substr(date, 1, 4) as year, category, subcategory,
           count(*) as cnt, round(sum(credit), 2) as credits, round(sum(debit), 2) as debits
    FROM transactions WHERE company_id = ?
    GROUP BY substr(date, 1, 4), category, subcategory
    ORDER BY year, category, subcategory
""", (COMPANY_ID,)):
    print(f"  {row[0]} {row[1]:10s} {str(row[2]):20s} cnt={row[3]:4d}  cr={row[4] or 0:>12.2f}  dr={row[5] or 0:>12.2f}")

conn.close()
print("\nDone.")

