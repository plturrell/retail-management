#!/usr/bin/env python3
"""
Re-categorise transactions in tax-categorisation-output.json based on manual analysis.

Business: CRAELL PTE. LTD. — crystal/jewelry retail through Isetan, Takashimaya, direct sales.
Director: TURRELL CRAIG JOHN
Staff: TAN LAY PENG, RINKU, GLADHENG/HENG HIAN LOI, SALITRE MIC, KHOO YI KAI, etc.
Brand: VictoriaEnso
"""

import json, sys, copy

CATEGORY_META = {
    "revenue": {"label": "Revenue / Income", "deductible": False, "deductionRate": 0},
    "salary_wages": {"label": "Salary & Wages", "deductible": True, "deductionRate": 1.0},
    "contractor_payments": {"label": "Contractor / Freelancer Payments", "deductible": True, "deductionRate": 1.0},
    "rent_property": {"label": "Rent & Property", "deductible": True, "deductionRate": 1.0},
    "utilities": {"label": "Utilities", "deductible": True, "deductionRate": 1.0},
    "professional_fees": {"label": "Professional Fees", "deductible": True, "deductionRate": 1.0},
    "bank_charges": {"label": "Bank Charges & Fees", "deductible": True, "deductionRate": 1.0},
    "insurance": {"label": "Insurance", "deductible": True, "deductionRate": 1.0},
    "transport_travel": {"label": "Transport & Business Travel", "deductible": True, "deductionRate": 1.0},
    "meals_entertainment": {"label": "Meals & Entertainment", "deductible": "partial", "deductionRate": 0.5},
    "office_supplies": {"label": "Office Supplies & General Expenses", "deductible": True, "deductionRate": 1.0},
    "inventory_cogs": {"label": "Inventory / COGS", "deductible": True, "deductionRate": 1.0},
    "it_software": {"label": "IT, Software & Digital Services", "deductible": True, "deductionRate": 1.0},
    "marketing_advertising": {"label": "Marketing & Advertising", "deductible": True, "deductionRate": 1.0},
    "subscriptions": {"label": "Subscriptions & Memberships", "deductible": True, "deductionRate": 1.0},
    "repairs_maintenance": {"label": "Repairs & Maintenance", "deductible": True, "deductionRate": 1.0},
    "training_development": {"label": "Training & Development", "deductible": True, "deductionRate": 1.0},
    "medical_benefits": {"label": "Medical & Health Benefits", "deductible": True, "deductionRate": 1.0},
    "cpf_contributions": {"label": "CPF Contributions", "deductible": True, "deductionRate": 1.0},
    "donations": {"label": "Donations (Approved IPCs)", "deductible": True, "deductionRate": 2.5},
    "capital_expenditure": {"label": "Capital Expenditure", "deductible": "partial", "deductionRate": 0},
    "loan_repayment": {"label": "Loan Repayment", "deductible": False, "deductionRate": 0},
    "cash_withdrawal": {"label": "Cash Withdrawal", "deductible": False, "deductionRate": 0},
    "transfer_internal": {"label": "Internal Transfer", "deductible": False, "deductionRate": 0},
    "personal_non_deductible": {"label": "Personal / Non-Deductible", "deductible": False, "deductionRate": 0},
    "uncategorised": {"label": "Uncategorised", "deductible": False, "deductionRate": 0},
}

def recategorise(t):
    """Return new category or None to keep existing."""
    desc = t["description"].upper()
    is_deposit = bool(t.get("deposit"))
    cat = t["category"]

    # 1. Director (TURRELL CRAIG JOHN) deposits = capital injection, not revenue
    if "TURRELL CRAIG JOHN" in desc and is_deposit:
        return "transfer_internal"

    # 2. eBay purchases = inventory (crystal/jewelry stock), not IT
    if "EBAY" in desc and not is_deposit:
        return "inventory_cogs"

    # 3. Phuket personal travel (THB transactions, hotel, duty-free)
    if any(x in desc for x in ["HIDEAWAY PHU", "ZURICH BREAD CAFE-PHUK", "KING POWER TAX FR"]):
        return "personal_non_deductible"
    if "JETSTAR" in desc and "THB" in desc:
        return "personal_non_deductible"

    # 4. Beatport = personal music platform
    if "BEATPORT" in desc:
        return "personal_non_deductible"

    # 5. Supermarket/grocery = personal, not meals_entertainment
    if any(x in desc for x in [
        "ISETAN (SUPERMARKET)", "TOP CHOICE SUPERMARKET", "COLD STORAGE",
        "FP XTRA", "AVM SUPERMART"
    ]):
        return "personal_non_deductible"

    # 6. ZARA = personal clothing
    if "ZARA" in desc:
        return "personal_non_deductible"

    # 7. Clinic charges ($2000 each) = likely personal medical, not staff benefit
    if "CLINIC CHARGES" in desc:
        return "personal_non_deductible"

    # 8. M&S clothing = personal (not inventory for crystal/jewelry business)
    if "M & S -" in desc or "MARKS & SPENCER" in desc:
        return "personal_non_deductible"

    # 9. TGP LIVING = home/lifestyle, personal
    if "TGP LIVING" in desc:
        return "personal_non_deductible"

    # 10. Cheers at airport = convenience store snacks
    if "CHEERS" in desc:
        return "meals_entertainment"

    # 11. FR SHAW food outlets
    if "FR SHAW-HONGLU MI" in desc:  # noodle shop
        return "meals_entertainment"
    if "FR SHAW-SERGEANT CHICK" in desc:  # chicken shop
        return "meals_entertainment"

    # 12. FAST TRANSFER to VictoriaEnso (uncategorised) → contractor_payments
    if "FAST TRANSFER" in desc and "VICTORIAENS" in desc and not is_deposit:
        return "contractor_payments"

    # 13. Large Isetan GIRO withdrawals = cash stock purchases (inventory)
    if "ISETAN" in desc and not is_deposit and (t.get("withdrawal") or 0) > 1000:
        return "inventory_cogs"

    return None  # keep existing

with open("tax-categorisation-output.json") as f:
    data = json.load(f)

changes = []
for i, t in enumerate(data["transactions"]):
    new_cat = recategorise(t)
    if new_cat and new_cat != t["category"]:
        old_cat = t["category"]
        meta = CATEGORY_META[new_cat]
        t["category"] = new_cat
        t["categoryLabel"] = meta["label"]
        t["deductible"] = meta["deductible"]
        amt = t.get("withdrawal") or 0
        t["deductionAmount"] = amt * meta["deductionRate"] if not t.get("deposit") else 0
        changes.append(f"  [{i:3d}] {old_cat:25s} → {new_cat:25s}  ${t.get('deposit') or t.get('withdrawal') or 0:>10.2f}  {t['description'][:55]}")

# Rebuild summaries
def build_summary(txns, year):
    yt = [t for t in txns if t["year"] == year]
    dep = sum(t.get("deposit", 0) or 0 for t in yt)
    wd = sum(t.get("withdrawal", 0) or 0 for t in yt)
    ded = sum(t["deductionAmount"] for t in yt)
    by_cat = {}
    for t in yt:
        c = t["category"]
        if c not in by_cat:
            by_cat[c] = {"count": 0, "withdrawal": 0, "deposit": 0, "deduction": 0}
        by_cat[c]["count"] += 1
        by_cat[c]["withdrawal"] += t.get("withdrawal", 0) or 0
        by_cat[c]["deposit"] += t.get("deposit", 0) or 0
        by_cat[c]["deduction"] += t["deductionAmount"]
    return {"totalDeposits": dep, "totalWithdrawals": wd, "totalDeductions": ded, "transactionCount": len(yt), "byCategory": by_cat}

data["summary"] = {"2023": build_summary(data["transactions"], 2023), "2024": build_summary(data["transactions"], 2024), "2025": build_summary(data["transactions"], 2025)}

with open("tax-categorisation-output.json", "w") as f:
    json.dump(data, f, indent=2)

print(f"Applied {len(changes)} recategorisations:\n")
for c in changes:
    print(c)

print(f"\nUpdated summaries:")
for yr in ["2023", "2024", "2025"]:
    s = data["summary"][yr]
    print(f"  {yr}: deposits=${s['totalDeposits']:,.2f}  withdrawals=${s['totalWithdrawals']:,.2f}  deductions=${s['totalDeductions']:,.2f}  txns={s['transactionCount']}")

