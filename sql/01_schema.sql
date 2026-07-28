-- 01_schema.sql
-- Creates a star-ish schema for the credit risk analytics.
-- Run: mysql -u root -p credit_risk < 01_schema.sql
-- (create the database first: CREATE DATABASE credit_risk;)

CREATE DATABASE credit_risk;
USE credit_risk

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS fact_payments;
DROP TABLE IF EXISTS dim_loan;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_date;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE dim_customer (
    customer_id     INT PRIMARY KEY,
    age             INT,
    income          DECIMAL(12,2),
    income_band     VARCHAR(20),
    employment_type VARCHAR(30),
    region          VARCHAR(30),
    signup_date     DATE
) ENGINE=InnoDB;

CREATE TABLE dim_date (
    date_key      DATE PRIMARY KEY,
    day_num       INT,
    month_num     INT,
    month_name    VARCHAR(10),
    quarter_num   INT,
    year_num      INT,
    fiscal_period VARCHAR(10)
) ENGINE=InnoDB;

CREATE TABLE dim_loan (
    loan_id           INT PRIMARY KEY,
    customer_id       INT,
    loan_type         VARCHAR(30),
    loan_amount       DECIMAL(14,2),
    interest_rate     DECIMAL(5,2),
    term_months       INT,
    origination_date  DATE,
    loan_status       VARCHAR(20),  -- ACTIVE / DEFAULTED
    FOREIGN KEY (customer_id) REFERENCES dim_customer(customer_id)
) ENGINE=InnoDB;

CREATE TABLE fact_payments (
    payment_id   INT PRIMARY KEY,
    loan_id      INT,
    due_date     DATE,
    paid_date    DATE,
    amount_due   DECIMAL(12,2),
    amount_paid  DECIMAL(12,2),
    days_late    INT,
    status       VARCHAR(20),  -- PAID / LATE / DEFAULTED
    FOREIGN KEY (loan_id) REFERENCES dim_loan(loan_id),
    FOREIGN KEY (due_date) REFERENCES dim_date(date_key)
) ENGINE=InnoDB;

CREATE INDEX idx_fact_loan_id ON fact_payments(loan_id);
CREATE INDEX idx_fact_due_date ON fact_payments(due_date);
CREATE INDEX idx_loan_customer_id ON dim_loan(customer_id);


SELECT COUNT(*) FROM dim_customer;
SELECT COUNT(*) FROM dim_loan;
SELECT COUNT(*) FROM dim_date;
SELECT COUNT(*) FROM fact_payments;
