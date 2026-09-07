"""
data/generate_sample_data.py

Generates data/sample_transactions.csv: a 12-month synthetic transaction
history for "Moyo Retail & Services", a fictional Zimbabwean SME, per
Section 28 of the master prompt.

Deliberately includes:
- Multiple currencies (USD, ZWL, ZAR, EUR, GBP, BWP, ZMW)
- Realistic SME categories (sales, purchases, rent, salaries, utilities,
  transport, supplier payments, customer receipts, bank charges, opex)
- A handful of deliberately unusual transactions for anomaly detection
  (spike amounts, odd timing, round-number outliers, a duplicate)
- A few rows with data-quality issues (missing VAT status, unknown
  currency code) to exercise the validation layer

Run directly: `python generate_sample_data.py`
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)  # deterministic across runs -- important for repeatable tests/demos

OUTPUT_PATH = Path(__file__).resolve().parent / "sample_transactions.csv"

CUSTOMERS = [
    "Chitungwiza Wholesalers", "Mbare Musika Traders", "Borrowdale Boutique",
    "Highfield Hardware", "Kadoma Cash & Carry", "Bulawayo Bulk Buyers",
    "Mutare Merchants", "Gweru General Store", "Avondale Essentials",
]
SUPPLIERS = [
    "Delta Beverages Zim", "Innscor Distribution", "National Foods Ltd",
    "Zimplow Holdings", "Proplastics Ltd", "PPC Zimbabwe",
    "TelOne Business", "ZESA Utility Payments", "SA Freight Logistics",
]
CURRENCIES = ["USD", "ZWL", "ZAR", "EUR", "GBP", "BWP", "ZMW"]
CURRENCY_WEIGHTS = [0.55, 0.20, 0.12, 0.03, 0.02, 0.05, 0.03]

INCOME_CATEGORIES = ["Sales - Retail", "Sales - Wholesale", "Customer Receipts", "Other Income"]
EXPENSE_CATEGORIES = [
    "Rent", "Salaries", "Utilities", "Transport", "Supplier Payments",
    "Bank Charges", "Operating Expenses", "Marketing", "Repairs & Maintenance",
]
PAYMENT_METHODS = ["EcoCash", "Bank Transfer", "Cash", "Swipe/POS", "RTGS"]
VAT_STATUSES = ["standard", "zero_rated", "exempt"]

START_DATE = date(2025, 9, 1)
NUM_MONTHS = 12


def daterange_months(start: date, months: int):
    y, m = start.year, start.month
    for i in range(months):
        yield y + (m - 1 + i) // 12, (m - 1 + i) % 12 + 1


def random_day(year: int, month: int) -> date:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    days_in_month = (next_month - date(year, month, 1)).days
    return date(year, month, random.randint(1, days_in_month))


def build_transactions() -> list[dict]:
    rows = []
    txn_counter = 1

    def new_id() -> str:
        nonlocal txn_counter
        tid = f"TX{txn_counter:04d}"
        txn_counter += 1
        return tid

    for year, month in daterange_months(START_DATE, NUM_MONTHS):
        # --- Recurring fixed costs, once a month, in USD ---
        rows.append(dict(
            transaction_id=new_id(), date=date(year, month, 1).isoformat(),
            description="Monthly shop rent - Borrowdale premises", account="Operations",
            customer="", supplier="Borrowdale Properties", transaction_type="expense",
            category="Rent", amount=850.00, currency="USD", payment_method="Bank Transfer",
            invoice_number=f"INV-RENT-{year}{month:02d}", vat_status="standard",
        ))
        rows.append(dict(
            transaction_id=new_id(), date=date(year, month, 28).isoformat(),
            description="Staff salaries - 6 employees", account="Payroll",
            customer="", supplier="", transaction_type="expense",
            category="Salaries", amount=2400.00, currency="USD", payment_method="Bank Transfer",
            invoice_number="", vat_status="exempt",
        ))
        rows.append(dict(
            transaction_id=new_id(), date=random_day(year, month).isoformat(),
            description="ZESA electricity bill", account="Operations",
            customer="", supplier="ZESA Utility Payments", transaction_type="expense",
            category="Utilities", amount=round(random.uniform(80, 180), 2), currency="USD",
            payment_method="RTGS", invoice_number=f"ZESA-{year}{month:02d}", vat_status="standard",
        ))

        # --- Sales transactions (income), 10-16 per month ---
        for _ in range(random.randint(10, 16)):
            currency = random.choices(CURRENCIES, weights=CURRENCY_WEIGHTS, k=1)[0]
            base_amount = random.uniform(150, 3200)
            rows.append(dict(
                transaction_id=new_id(), date=random_day(year, month).isoformat(),
                description=f"Sale of goods - {random.choice(['stationery','groceries','hardware','electronics','clothing'])}",
                account="Sales", customer=random.choice(CUSTOMERS), supplier="",
                transaction_type="income", category=random.choice(INCOME_CATEGORIES),
                amount=round(base_amount, 2), currency=currency,
                payment_method=random.choice(PAYMENT_METHODS),
                invoice_number=f"INV-{year}{month:02d}-{random.randint(100,999)}",
                vat_status=random.choice(VAT_STATUSES),
            ))

        # --- Supplier / purchase transactions, 6-10 per month ---
        for _ in range(random.randint(6, 10)):
            currency = random.choices(CURRENCIES, weights=CURRENCY_WEIGHTS, k=1)[0]
            rows.append(dict(
                transaction_id=new_id(), date=random_day(year, month).isoformat(),
                description=f"Stock purchase from {random.choice(SUPPLIERS)}",
                account="Purchases", customer="", supplier=random.choice(SUPPLIERS),
                transaction_type="expense", category="Supplier Payments",
                amount=round(random.uniform(300, 2600), 2), currency=currency,
                payment_method=random.choice(PAYMENT_METHODS),
                invoice_number=f"PO-{year}{month:02d}-{random.randint(100,999)}",
                vat_status="standard",
            ))

        # --- Misc small opex / transport / bank charges, 4-7 per month ---
        for _ in range(random.randint(4, 7)):
            rows.append(dict(
                transaction_id=new_id(), date=random_day(year, month).isoformat(),
                description=random.choice([
                    "Fuel and transport", "Bank charges", "Office supplies",
                    "Vehicle maintenance", "Marketing - flyers and social media",
                ]),
                account="Operations", customer="", supplier="", transaction_type="expense",
                category=random.choice(["Transport", "Bank Charges", "Operating Expenses",
                                          "Repairs & Maintenance", "Marketing"]),
                amount=round(random.uniform(20, 220), 2), currency="USD",
                payment_method=random.choice(PAYMENT_METHODS), invoice_number="",
                vat_status=random.choice(VAT_STATUSES),
            ))

    return rows


def inject_anomalies_and_quality_issues(rows: list[dict]) -> list[dict]:
    """Mutate a handful of rows to create deliberate anomalies + data-quality issues."""

    # 1) A single dramatically oversized supplier payment (spike anomaly)
    supplier_rows = [r for r in rows if r["transaction_type"] == "expense" and r["supplier"]]
    target = random.choice(supplier_rows)
    target["amount"] = 18500.00
    target["currency"] = "USD"
    target["description"] = f"Large one-off payment to {target['supplier']}"

    # 2) A duplicate transaction (same supplier/amount/date pattern, new ID)
    dup_source = random.choice(supplier_rows)
    dup = dict(dup_source)
    dup["transaction_id"] = f"TX{len(rows)+1:04d}"
    dup["description"] += " (possible duplicate submission)"
    rows.append(dup)

    # 3) Round-number outlier sale that's unusually large for the category
    sales_rows = [r for r in rows if r["transaction_type"] == "income"]
    round_target = random.choice(sales_rows)
    round_target["amount"] = 9000.00
    round_target["currency"] = "USD"

    # 4) A handful of rows missing VAT status (data-quality issue)
    for r in random.sample(rows, 12):
        r["vat_status"] = ""

    # 5) A handful of rows with an unrecognised currency code (data-quality issue)
    for r in random.sample(rows, 5):
        r["currency"] = "XXX"

    # 6) Two calibrated LOW-severity anomalies -- mildly elevated amounts (not
    # extreme enough for the MEDIUM/HIGH z-score tiers in
    # analytics/anomaly_detection.py) so the demo dataset reliably shows the
    # full LOW/MEDIUM/HIGH spectrum instead of only ever surfacing extremes.
    # Calibrated against each category's own USD mean/std so this holds even
    # if amounts elsewhere in the generator change.
    import pandas as pd

    usd_rows = [r for r in rows if r["currency"] == "USD"]
    by_category = pd.DataFrame(usd_rows).groupby("category")["amount"].agg(["mean", "std"])

    def _set_amount_at_zscore(candidate_rows: list[dict], target_z: float) -> None:
        row = random.choice(candidate_rows)
        stats = by_category.loc[row["category"]]
        if pd.isna(stats["std"]) or stats["std"] == 0:
            return  # category too uniform to calibrate a z-score against; skip
        row["amount"] = round(stats["mean"] + target_z * stats["std"], 2)
        row["currency"] = "USD"

    non_special_rows = [r for r in rows if r["currency"] == "USD" and r["amount"] not in (18500.00, 9000.00)]
    _set_amount_at_zscore(non_special_rows, target_z=1.82)  # lands near a 0.1 anomaly score
    _set_amount_at_zscore(non_special_rows, target_z=1.90)  # lands near a 0.2 anomaly score

    return rows


def write_csv(rows: list[dict], path: Path = OUTPUT_PATH) -> None:
    fieldnames = [
        "transaction_id", "date", "description", "account", "customer", "supplier",
        "transaction_type", "category", "amount", "currency", "payment_method",
        "invoice_number", "vat_status",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    txns = build_transactions()
    txns = inject_anomalies_and_quality_issues(txns)
    txns.sort(key=lambda r: r["date"])
    write_csv(txns)
    print(f"Wrote {len(txns)} transactions to {OUTPUT_PATH}")
