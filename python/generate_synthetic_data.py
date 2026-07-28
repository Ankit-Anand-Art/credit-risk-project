"""
generate_data.py
-----------------
Generates synthetic but realistic credit-risk data:
  - dim_customer.csv
  - dim_loan.csv
  - fact_payments.csv

Why synthetic instead of Kaggle? You get a schema you fully control (matches
the ER diagram exactly), reproducible row counts, and no download/login step.
If you'd rather use a real Kaggle dataset ("Lending Club Loan Data" or
"Home Credit Default Risk"), skip this script and adapt 03_cleaning_views.sql
column names instead.

Run:
    pip install pandas faker numpy --break-system-packages   (or in a venv)
    python generate_data.py
"""

import numpy as np
import pandas as pd
from faker import Faker
from datetime import date, timedelta
import random

random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

N_CUSTOMERS = 5000
N_LOANS = 6500
START_ORIGINATION = date(2021, 1, 1)
END_ORIGINATION = date(2024, 12, 31)

REGIONS = ["North", "South", "East", "West", "Central"]
EMPLOYMENT = ["Salaried", "Self-Employed", "Business Owner", "Unemployed", "Retired"]
LOAN_TYPES = ["Personal", "Auto", "Home", "Business", "Education"]
INCOME_BANDS = ["<25k", "25k-50k", "50k-75k", "75k-100k", "100k+"]

# ---------------------------------------------------------------------------
# 1. dim_customer
# ---------------------------------------------------------------------------
customers = []
for cid in range(1, N_CUSTOMERS + 1):
    age = int(np.clip(np.random.normal(40, 12), 21, 75))
    income = max(15000, np.random.lognormal(mean=10.9, sigma=0.45))
    if income < 25000:
        band = "<25k"
    elif income < 50000:
        band = "25k-50k"
    elif income < 75000:
        band = "50k-75k"
    elif income < 100000:
        band = "75k-100k"
    else:
        band = "100k+"
    customers.append({
        "customer_id": cid,
        "age": age,
        "income": round(income, 2),
        "income_band": band,
        "employment_type": random.choices(EMPLOYMENT, weights=[55, 20, 10, 8, 7])[0],
        "region": random.choice(REGIONS),
        "signup_date": fake.date_between(start_date=date(2019, 1, 1), end_date=date(2021, 1, 1)),
    })
dim_customer = pd.DataFrame(customers)

# ---------------------------------------------------------------------------
# 2. dim_loan  (risk baked in: lower income band / self-employed / young age
#    -> higher default probability, so segmentation KPIs later look real)
# ---------------------------------------------------------------------------
def days_between(d1, d2):
    return (d2 - d1).days

def random_origination_date():
    delta = days_between(START_ORIGINATION, END_ORIGINATION)
    return START_ORIGINATION + timedelta(days=random.randint(0, delta))

loans = []
for lid in range(1, N_LOANS + 1):
    cust = dim_customer.iloc[random.randint(0, N_CUSTOMERS - 1)]
    loan_type = random.choices(LOAN_TYPES, weights=[35, 20, 20, 15, 10])[0]
    base_amount = {
        "Personal": 8000, "Auto": 18000, "Home": 150000, "Business": 40000, "Education": 15000
    }[loan_type]
    loan_amount = round(base_amount * np.random.uniform(0.5, 1.8), 2)
    term_months = random.choice([12, 24, 36, 48, 60])
    interest_rate = round(np.random.uniform(6, 22), 2)
    origination_date = random_origination_date()

    # risk score drives default probability
    risk = 0.05
    if cust["income_band"] in ["<25k", "25k-50k"]:
        risk += 0.10
    if cust["employment_type"] in ["Unemployed", "Self-Employed"]:
        risk += 0.08
    if cust["age"] < 28:
        risk += 0.05
    if interest_rate > 15:
        risk += 0.06
    risk = min(risk, 0.55)

    is_default = np.random.rand() < risk
    loans.append({
        "loan_id": lid,
        "customer_id": int(cust["customer_id"]),
        "loan_type": loan_type,
        "loan_amount": loan_amount,
        "interest_rate": interest_rate,
        "term_months": term_months,
        "origination_date": origination_date,
        "will_default": is_default,   # used only to drive payment simulation below
    })
dim_loan = pd.DataFrame(loans)

# ---------------------------------------------------------------------------
# 3. fact_payments  (one row per scheduled monthly installment)
# ---------------------------------------------------------------------------
payment_rows = []
payment_id = 1
today = date(2025, 6, 1)  # "as of" date for the dataset

for _, loan in dim_loan.iterrows():
    monthly_amount = round(loan["loan_amount"] / loan["term_months"], 2)
    origination = loan["origination_date"]
    will_default = loan["will_default"]
    # pick a random month in the term at which default happens (if it does)
    default_month = random.randint(3, loan["term_months"]) if will_default else None

    for m in range(1, loan["term_months"] + 1):
        due_date = origination + timedelta(days=30 * m)
        if due_date > today:
            break  # installment not due yet

        status = "PAID"
        days_late = 0
        paid_date = due_date + timedelta(days=random.choice([-2, -1, 0, 0, 0, 1, 2]))
        amount_paid = monthly_amount

        if will_default and default_month and m >= default_month:
            status = "DEFAULTED"
            amount_paid = 0.0
            paid_date = None
            days_late = (today - due_date).days
        else:
            # small chance of a late-but-eventually-paid installment
            if np.random.rand() < 0.12:
                late_days = random.choice([5, 15, 32, 65, 95])
                days_late = late_days
                paid_date = due_date + timedelta(days=late_days)
                status = "LATE"

        payment_rows.append({
            "payment_id": payment_id,
            "loan_id": loan["loan_id"],
            "due_date": due_date,
            "paid_date": paid_date,
            "amount_due": monthly_amount,
            "amount_paid": round(amount_paid, 2),
            "days_late": max(days_late, 0),
            "status": status,
        })
        payment_id += 1

fact_payments = pd.DataFrame(payment_rows)

# drop helper column before export
dim_loan_export = dim_loan.drop(columns=["will_default"]).copy()
# add a derived loan-level status for convenience (used by dim_loan in the DB)
defaulted_loan_ids = set(fact_payments.loc[fact_payments.status == "DEFAULTED", "loan_id"])
dim_loan_export["loan_status"] = dim_loan_export["loan_id"].apply(
    lambda x: "DEFAULTED" if x in defaulted_loan_ids else "ACTIVE"
)

# ---------------------------------------------------------------------------
# 4. Save
# ---------------------------------------------------------------------------
dim_customer.to_csv("../data/dim_customer.csv", index=False)
dim_loan_export.to_csv("../data/dim_loan.csv", index=False)
fact_payments.to_csv("../data/fact_payments.csv", index=False)

# ---------------------------------------------------------------------------
# 5. dim_date — generated here (not in SQL) to avoid MySQL recursion-depth
#    limits on generate_series-style date spines.
# ---------------------------------------------------------------------------
date_range = pd.date_range("2021-01-01", "2026-12-31", freq="D")
dim_date = pd.DataFrame({"date_key": date_range})
dim_date["day_num"] = dim_date["date_key"].dt.day
dim_date["month_num"] = dim_date["date_key"].dt.month
dim_date["month_name"] = dim_date["date_key"].dt.strftime("%b")
dim_date["quarter_num"] = dim_date["date_key"].dt.quarter
dim_date["year_num"] = dim_date["date_key"].dt.year
dim_date["fiscal_period"] = "FY" + dim_date["year_num"].astype(str) + "-Q" + dim_date["quarter_num"].astype(str)
dim_date["date_key"] = dim_date["date_key"].dt.date
dim_date.to_csv("../data/dim_date.csv", index=False)

print(f"customers: {len(dim_customer)}")
print(f"loans: {len(dim_loan_export)}  (defaulted: {len(defaulted_loan_ids)})")
print(f"payments: {len(fact_payments)}")
print(f"date dimension rows: {len(dim_date)}")
print("CSV files written to ../data/")
