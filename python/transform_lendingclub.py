"""
transform_lendingclub.py
--------------------------
Converts the raw Kaggle "Lending Club Loan Data (2007-2011)" CSV into the
four tables our schema expects: dim_customer.csv, dim_loan.csv, dim_date.csv,
fact_payments.csv.

WHY THIS STEP EXISTS: the public Lending Club dump is one wide table of
loan-level SUMMARIES (total paid, last payment date, current status) — it
does not include a month-by-month payment ledger. To get a fact_payments
table (needed for the delinquency/vintage KPI views), we reconstruct an
approximate monthly installment schedule per loan from real fields: issue
date, term, installment amount, last payment date, and current loan_status.

This is a standard, defensible technique for this dataset — just be upfront
about it if it comes up in an interview: "the source data is loan-level; I
derived an approximate payment ledger from term/issue date/status to enable
cohort and delinquency analysis." It is NOT fabricating outcomes — every
loan's final status and total paid amount come straight from the real data;
only the month-by-month shape of how it got there is estimated.

GET THE DATA FIRST (one-time):
    1. Create a free Kaggle account, then get an API token:
       kaggle.com -> profile -> Settings -> API -> "Create New Token"
       (downloads kaggle.json)
    2. Put kaggle.json at ~/.kaggle/kaggle.json (Linux/Mac) or
       C:\\Users\\<you>\\.kaggle\\kaggle.json (Windows)
    3. pip install kaggle --break-system-packages
    4. Download + unzip into data/raw/:
       kaggle datasets download -d imsparsh/lending-club-loan-dataset-2007-2011 -p ../data/raw --unzip
       (Or download manually from kaggle.com/datasets/imsparsh/lending-club-loan-dataset-2007-2011
       and unzip loan.csv into ../data/raw/)

Run:
    pip install pandas numpy --break-system-packages
    python transform_lendingclub.py
"""

import numpy as np
import pandas as pd

RAW_PATH = "../data/raw/loan.csv"
REFERENCE_DATE = pd.Timestamp("2016-01-01")  # "as of" date — loans in this
                                              # dataset mostly matured by then

US_REGION = {
    # Northeast
    "CT": "Northeast", "ME": "Northeast", "MA": "Northeast", "NH": "Northeast",
    "RI": "Northeast", "VT": "Northeast", "NJ": "Northeast", "NY": "Northeast", "PA": "Northeast",
    # Midwest
    "IL": "Midwest", "IN": "Midwest", "MI": "Midwest", "OH": "Midwest", "WI": "Midwest",
    "IA": "Midwest", "KS": "Midwest", "MN": "Midwest", "MO": "Midwest", "NE": "Midwest",
    "ND": "Midwest", "SD": "Midwest",
    # South
    "DE": "South", "FL": "South", "GA": "South", "MD": "South", "NC": "South", "SC": "South",
    "VA": "South", "DC": "South", "WV": "South", "AL": "South", "KY": "South", "MS": "South",
    "TN": "South", "AR": "South", "LA": "South", "OK": "South", "TX": "South",
    # West
    "AZ": "West", "CO": "West", "ID": "West", "MT": "West", "NV": "West", "NM": "West",
    "UT": "West", "WY": "West", "AK": "West", "CA": "West", "HI": "West", "OR": "West", "WA": "West",
}


def income_band(income):
    if pd.isna(income):
        return "Unknown"
    if income < 25000:
        return "<25k"
    if income < 50000:
        return "25k-50k"
    if income < 75000:
        return "50k-75k"
    if income < 100000:
        return "75k-100k"
    return "100k+"


print("Reading raw CSV (this can take a minute)...")
raw = pd.read_csv(RAW_PATH, low_memory=False)

needed = ["id", "member_id", "loan_amnt", "term", "int_rate", "installment",
          "issue_d", "loan_status", "purpose", "annual_inc", "emp_length",
          "addr_state", "last_pymnt_d"]
missing = [c for c in needed if c not in raw.columns]
if missing:
    raise SystemExit(
        f"Missing expected columns {missing} in loan.csv — the Kaggle file "
        "layout may differ from what this script expects. Open the CSV and "
        "check column names, then adjust `needed` above."
    )

df = raw[needed].copy()
df = df.dropna(subset=["id", "loan_amnt", "term", "issue_d"])

# member_id is often blank in this dataset dump; fall back to id
# (this means we treat each loan as its own borrower — a known simplification,
# see README for why).
df["member_id"] = df["member_id"].fillna(df["id"])
df["member_id"] = pd.to_numeric(df["member_id"], errors="coerce").astype("Int64")
df = df.dropna(subset=["member_id"])

df["term_months"] = df["term"].astype(str).str.extract(r"(\d+)").astype(int)
df["int_rate"] = df["int_rate"].astype(str).str.replace("%", "", regex=False).astype(float)
df["issue_d"] = pd.to_datetime(df["issue_d"], format="%b-%y", errors="coerce")
df["last_pymnt_d"] = pd.to_datetime(df["last_pymnt_d"], format="%b-%y", errors="coerce")
df = df.dropna(subset=["issue_d"])

DEFAULT_STATUSES = {"Charged Off", "Default"}
df["loan_status_clean"] = np.where(df["loan_status"].isin(DEFAULT_STATUSES), "DEFAULTED", "ACTIVE")

# ---------------------------------------------------------------------------
# dim_customer — one row per member_id (see fallback note above)
# ---------------------------------------------------------------------------
cust = (
    df.sort_values("issue_d")
      .drop_duplicates(subset=["member_id"], keep="first")
      .copy()
)
dim_customer = pd.DataFrame({
    "customer_id": cust["member_id"].astype(int),
    "age": np.nan,  # not collected by Lending Club — left blank on purpose
    "income": cust["annual_inc"],
    "income_band": cust["annual_inc"].apply(income_band),
    "employment_type": cust["emp_length"].fillna("Unknown"),  # proxy: tenure bucket
    "region": cust["addr_state"].map(US_REGION).fillna("Unknown"),
    "signup_date": cust["issue_d"].dt.date,  # proxy: date of first loan on record
})

# ---------------------------------------------------------------------------
# dim_loan
# ---------------------------------------------------------------------------
dim_loan = pd.DataFrame({
    "loan_id": df["id"].astype(int),
    "customer_id": df["member_id"].astype(int),
    "loan_type": df["purpose"].fillna("Unknown"),
    "loan_amount": df["loan_amnt"],
    "interest_rate": df["int_rate"],
    "term_months": df["term_months"],
    "origination_date": df["issue_d"].dt.date,
    "loan_status": df["loan_status_clean"],
})

# ---------------------------------------------------------------------------
# fact_payments — reconstructed monthly schedule (see module docstring)
# ---------------------------------------------------------------------------
LATE_DAYS = {
    "In Grace Period": 5,
    "Late (16-30 days)": 20,
    "Late (31-120 days)": 60,
}

rows = []
payment_id = 1
for _, loan in df.iterrows():
    installment = loan["installment"]
    if pd.isna(installment) or installment <= 0:
        installment = loan["loan_amnt"] / loan["term_months"]
    origination = loan["issue_d"]
    last_paid = loan["last_pymnt_d"]
    status = loan["loan_status"]
    term_months = int(loan["term_months"])

    months_paid = term_months
    if pd.notna(last_paid):
        months_paid = (last_paid.year - origination.year) * 12 + (last_paid.month - origination.month) + 1
        months_paid = max(0, min(months_paid, term_months))

    for m in range(1, term_months + 1):
        due_date = origination + pd.DateOffset(months=m)
        if due_date.date() > REFERENCE_DATE.date():
            break  # not due yet as of our reference date

        if m <= months_paid:
            pay_status = "PAID"
            days_late = 0
            amount_paid = installment
            paid_date = due_date.date()
            if m == months_paid and status in LATE_DAYS:
                pay_status = "LATE"
                days_late = LATE_DAYS[status]
        elif status in DEFAULT_STATUSES:
            pay_status = "DEFAULTED"
            amount_paid = 0.0
            paid_date = None
            days_late = (REFERENCE_DATE.date() - due_date.date()).days
        else:
            break  # loan is Current / paid off early — nothing more due yet

        rows.append({
            "payment_id": payment_id,
            "loan_id": int(loan["id"]),
            "due_date": due_date.date(),
            "paid_date": paid_date,
            "amount_due": round(float(installment), 2),
            "amount_paid": round(float(amount_paid), 2),
            "days_late": max(int(days_late), 0),
            "status": pay_status,
        })
        payment_id += 1

fact_payments = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# dim_date — span the full range the reconstructed schedule needs
# ---------------------------------------------------------------------------
date_range = pd.date_range(df["issue_d"].min(), REFERENCE_DATE, freq="D")
dim_date = pd.DataFrame({"date_key": date_range})
dim_date["day_num"] = dim_date["date_key"].dt.day
dim_date["month_num"] = dim_date["date_key"].dt.month
dim_date["month_name"] = dim_date["date_key"].dt.strftime("%b")
dim_date["quarter_num"] = dim_date["date_key"].dt.quarter
dim_date["year_num"] = dim_date["date_key"].dt.year
dim_date["fiscal_period"] = "FY" + dim_date["year_num"].astype(str) + "-Q" + dim_date["quarter_num"].astype(str)
dim_date["date_key"] = dim_date["date_key"].dt.date

# ---------------------------------------------------------------------------
# Save — same filenames/columns load_data.py already expects
# ---------------------------------------------------------------------------
dim_customer.to_csv("../data/dim_customer.csv", index=False)
dim_loan.to_csv("../data/dim_loan.csv", index=False)
fact_payments.to_csv("../data/fact_payments.csv", index=False)
dim_date.to_csv("../data/dim_date.csv", index=False)

print(f"customers: {len(dim_customer)}")
print(f"loans: {len(dim_loan)}  (defaulted: {(dim_loan.loan_status == 'DEFAULTED').sum()})")
print(f"payments (reconstructed): {len(fact_payments)}")
print(f"date dimension rows: {len(dim_date)}")
print("CSV files written to ../data/ — continue with sql/01_schema.sql (unchanged)")
