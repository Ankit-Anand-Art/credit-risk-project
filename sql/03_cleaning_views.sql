-- 03_cleaning_views.sql

USE credit_risk

CREATE OR REPLACE VIEW stg_customer AS
SELECT
    customer_id,
    COALESCE(age, 0)                         AS age,
    COALESCE(income, 0)                      AS income,
    COALESCE(income_band, 'Unknown')         AS income_band,
    COALESCE(employment_type, 'Unknown')     AS employment_type,
    COALESCE(region, 'Unknown')              AS region,
    signup_date
FROM dim_customer
WHERE customer_id IS NOT NULL;

CREATE OR REPLACE VIEW stg_loan AS
SELECT
    loan_id,
    customer_id,
    COALESCE(loan_type, 'Unknown')  AS loan_type,
    loan_amount,
    interest_rate,
    term_months,
    origination_date,
    UPPER(TRIM(loan_status))        AS loan_status
FROM dim_loan
WHERE loan_id IS NOT NULL
  AND loan_amount > 0;

CREATE OR REPLACE VIEW stg_payments AS
SELECT
    payment_id,
    loan_id,
    due_date,
    paid_date,
    COALESCE(amount_due, 0)   AS amount_due,
    COALESCE(amount_paid, 0)  AS amount_paid,
    COALESCE(days_late, 0)    AS days_late,
    UPPER(TRIM(status))       AS status,
    
    CASE
        WHEN COALESCE(days_late, 0) = 0 THEN 'Current'
        WHEN days_late BETWEEN 1 AND 29 THEN '1-29 DPD'
        WHEN days_late BETWEEN 30 AND 59 THEN '30-59 DPD'
        WHEN days_late BETWEEN 60 AND 89 THEN '60-89 DPD'
        ELSE '90+ DPD'
    END AS dpd_bucket
FROM fact_payments
WHERE payment_id IS NOT NULL;
