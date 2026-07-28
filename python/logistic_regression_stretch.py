"""
logistic_regression_stretch.py  (OPTIONAL, step 9 in the guide)
-----------------------------------------------------------------
Trains a basic logistic regression to predict probability of default
per loan, then writes the score back to a CSV you can load into Postgres
as a new table (dim_risk_score) and join into Power BI.

Run:
    pip install pandas scikit-learn sqlalchemy pymysql --break-system-packages
    python logistic_regression_stretch.py
"""

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from sqlalchemy import create_engine

DB_USER = "root"
DB_PASSWORD = "your_password"
DB_HOST = "localhost"
DB_PORT = "3306"
DB_NAME = "credit_risk"

engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Pull loan + customer features and the actual outcome label
query = """
SELECT
    l.loan_id,
    l.loan_amount,
    l.interest_rate,
    l.term_months,
    c.age,
    c.income,
    c.income_band,
    c.employment_type,
    (l.loan_status = 'DEFAULTED')::int AS defaulted
FROM dim_loan l
JOIN dim_customer c ON c.customer_id = l.customer_id
"""
df = pd.read_sql(query, engine)

# One-hot encode categoricals
df_encoded = pd.get_dummies(df, columns=["income_band", "employment_type"], drop_first=True)

feature_cols = [c for c in df_encoded.columns if c not in ("loan_id", "defaulted")]
X = df_encoded[feature_cols]
y = df_encoded["defaulted"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y
)

model = LogisticRegression(max_iter=1000)
model.fit(X_train, y_train)

auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
print(f"Test AUC: {auc:.3f}")

# Score the full dataset and export
df["default_probability"] = model.predict_proba(X)[:, 1]
scores = df[["loan_id", "default_probability"]]
scores.to_csv("../data/dim_risk_score.csv", index=False)
print("Wrote ../data/dim_risk_score.csv")
print("Load it into Postgres as `dim_risk_score` (loan_id, default_probability),")
print("then relate loan_id -> dim_loan.loan_id in Power BI to add a risk-score visual.")
