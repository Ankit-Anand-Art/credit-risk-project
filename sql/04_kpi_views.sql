-- 04_kpi_views.sql

USE credit_risk


-- A) Overall & monthly default rate
    
CREATE OR REPLACE VIEW kpi_default_rate_overall AS
SELECT
    ROUND(SUM(CASE WHEN loan_status = 'DEFAULTED' THEN 1 ELSE 0 END) / COUNT(*), 4) AS default_rate,
    COUNT(*) AS total_loans,
    SUM(CASE WHEN loan_status = 'DEFAULTED' THEN 1 ELSE 0 END) AS defaulted_loans
FROM stg_loan;

CREATE OR REPLACE VIEW kpi_default_rate_by_month AS
SELECT
    CAST(DATE_FORMAT(origination_date, '%Y-%m-01') AS DATE) AS origination_month,
    COUNT(*) AS loans_originated,
    SUM(CASE WHEN loan_status = 'DEFAULTED' THEN 1 ELSE 0 END) AS defaults,
    ROUND(SUM(CASE WHEN loan_status = 'DEFAULTED' THEN 1 ELSE 0 END) / COUNT(*), 4) AS default_rate
FROM stg_loan
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE VIEW kpi_default_rate_by_segment AS
SELECT
    c.region,
    c.income_band,
    l.loan_type,
    COUNT(*) AS total_loans,
    SUM(CASE WHEN l.loan_status = 'DEFAULTED' THEN 1 ELSE 0 END) AS defaults,
    ROUND(SUM(CASE WHEN l.loan_status = 'DEFAULTED' THEN 1 ELSE 0 END) / COUNT(*), 4) AS default_rate
FROM stg_loan l
JOIN stg_customer c ON c.customer_id = l.customer_id
GROUP BY 1, 2, 3;


-- B) Delinquency rate, bucketed (30/60/90+ DPD)

CREATE OR REPLACE VIEW kpi_delinquency_buckets AS
SELECT
    dpd_bucket,
    COUNT(*) AS installment_count,
    SUM(amount_due) AS total_amount_due,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER (), 4) AS pct_of_installments
FROM stg_payments
GROUP BY dpd_bucket;


-- C) Portfolio at Risk (PAR): outstanding balance of delinquent loans / total outstanding balance.

CREATE OR REPLACE VIEW kpi_portfolio_at_risk AS
WITH loan_balances AS (
    SELECT
        loan_id,
        SUM(amount_due - amount_paid) AS outstanding_balance,
        MAX(CASE WHEN dpd_bucket <> 'Current' THEN 1 ELSE 0 END) AS is_delinquent
    FROM stg_payments
    GROUP BY loan_id
)
SELECT
    ROUND(
        SUM(CASE WHEN is_delinquent = 1 THEN outstanding_balance ELSE 0 END)
            / NULLIF(SUM(outstanding_balance), 0), 4
    ) AS portfolio_at_risk_ratio,
    SUM(CASE WHEN is_delinquent = 1 THEN outstanding_balance ELSE 0 END) AS balance_at_risk,
    SUM(outstanding_balance) AS total_outstanding
FROM loan_balances;


-- D) Exposure at Default (EAD) & Loss Given Default (LGD)

CREATE OR REPLACE VIEW kpi_ead_lgd AS
WITH loan_exposure AS (
    SELECT
        l.loan_id,
        l.loan_amount,
        l.loan_status,
        SUM(p.amount_due) AS total_due,
        SUM(p.amount_paid) AS total_paid,
        SUM(p.amount_due - p.amount_paid) AS exposure_at_default
    FROM stg_loan l
    JOIN stg_payments p ON p.loan_id = l.loan_id
    GROUP BY l.loan_id, l.loan_amount, l.loan_status
)
SELECT
    loan_id,
    loan_amount,
    exposure_at_default AS ead,
    ROUND(exposure_at_default / NULLIF(loan_amount, 0), 4) AS lgd_ratio
FROM loan_exposure
WHERE loan_status = 'DEFAULTED';


-- E) Recovery rate (1 - LGD, portfolio level)

CREATE OR REPLACE VIEW kpi_recovery_rate AS
SELECT
    1 - ROUND(SUM(ead) / NULLIF(SUM(loan_amount), 0), 4) AS recovery_rate
FROM kpi_ead_lgd;


-- F) Vintage / cohort analysis: default rate by origination month, tracked over months-on-book.

CREATE OR REPLACE VIEW kpi_vintage_analysis AS
SELECT
    CAST(DATE_FORMAT(l.origination_date, '%Y-%m-01') AS DATE) AS vintage_month,
    (YEAR(p.due_date) * 12 + MONTH(p.due_date))
      - (YEAR(l.origination_date) * 12 + MONTH(l.origination_date))
      AS months_on_book,
    COUNT(l.loan_id) AS loans_in_cohort,
    SUM(CASE WHEN p.status = 'DEFAULTED' THEN 1 ELSE 0 END) AS cumulative_defaults,
    ROUND(
        SUM(CASE WHEN p.status = 'DEFAULTED' THEN 1 ELSE 0 END)
            / NULLIF(COUNT(l.loan_id), 0), 4
    ) AS cohort_default_rate
FROM stg_loan l
JOIN stg_payments p ON p.loan_id = l.loan_id
GROUP BY 1, 2
ORDER BY 1, 2;


-- G) Approval-to-default funnel by region/income band/loan type

CREATE OR REPLACE VIEW kpi_funnel AS
SELECT
    c.region,
    c.income_band,
    l.loan_type,
    COUNT(*) AS loans_approved,
    SUM(CASE WHEN l.loan_status = 'DEFAULTED' THEN 1 ELSE 0 END) AS loans_defaulted,
    ROUND(SUM(CASE WHEN l.loan_status = 'DEFAULTED' THEN 1 ELSE 0 END) / COUNT(*), 4) AS default_rate
FROM stg_loan l
JOIN stg_customer c ON c.customer_id = l.customer_id
GROUP BY 1, 2, 3
ORDER BY default_rate DESC;


-- H) Window functions


-- H1) RANK top-N riskiest customers by total exposure at default
CREATE OR REPLACE VIEW kpi_top_risky_customers AS
SELECT
    c.customer_id,
    c.region,
    c.income_band,
    SUM(e.ead) AS total_ead,
    RANK() OVER (ORDER BY SUM(e.ead) DESC) AS risk_rank
FROM kpi_ead_lgd e
JOIN stg_loan l ON l.loan_id = e.loan_id
JOIN stg_customer c ON c.customer_id = l.customer_id
GROUP BY c.customer_id, c.region, c.income_band;

-- H2) Month-over-month change in default rate using LAG/LEAD
CREATE OR REPLACE VIEW kpi_default_rate_mom_change AS
SELECT
    origination_month,
    default_rate,
    LAG(default_rate) OVER (ORDER BY origination_month)  AS prev_month_default_rate,
    ROUND(
        default_rate - LAG(default_rate) OVER (ORDER BY origination_month), 4
    ) AS mom_change,
    LEAD(default_rate) OVER (ORDER BY origination_month) AS next_month_default_rate
FROM kpi_default_rate_by_month;

-- H3) Rolling 3-month average default rate (window frame)
CREATE OR REPLACE VIEW kpi_default_rate_rolling_avg AS
SELECT
    origination_month,
    default_rate,
    ROUND(
        AVG(default_rate) OVER (
            ORDER BY origination_month
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ), 4
    ) AS rolling_3mo_avg_default_rate
FROM kpi_default_rate_by_month;

-- H4) CTE-based cohort summary (loans reaching 6 months on book)
CREATE OR REPLACE VIEW kpi_cohort_6mo_snapshot AS
WITH cohort AS (
    SELECT *
    FROM kpi_vintage_analysis
    WHERE months_on_book = 6
)
SELECT
    vintage_month,
    loans_in_cohort,
    cumulative_defaults,
    cohort_default_rate,
    RANK() OVER (ORDER BY cohort_default_rate DESC) AS worst_cohort_rank
FROM cohort;


SHOW FULL TABLES IN credit_risk WHERE Table_type = 'VIEW';

SELECT * FROM kpi_default_rate_overall;
SELECT * FROM kpi_vintage_analysis ORDER BY vintage_month, months_on_book LIMIT 20;
