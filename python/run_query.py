"""
run_query.py
-------------
Bypasses MySQL Workbench's client-side read timeout (which can't be found/changed in some Workbench versions) by running queries directly.
Run:
    python run_query.py
"""

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

DB_USER = "root"
DB_PASSWORD = "Your_Password"
DB_HOST = "localhost"
DB_PORT = "3306"
DB_NAME = "credit_risk"

url = URL.create(
    "mysql+pymysql",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=int(DB_PORT),
    database=DB_NAME,
)



engine = create_engine(
    url,
    connect_args={"connect_timeout": 30, "read_timeout": 900, "write_timeout": 900},
)

QUERY = "SELECT * FROM kpi_vintage_analysis ORDER BY vintage_month, months_on_book LIMIT 20;"

print("Running query (this may take a minute for heavy views)...")
with engine.connect() as conn:
    df = pd.read_sql(text(QUERY), conn)

print(df)
print(f"\n{len(df)} rows returned.")
