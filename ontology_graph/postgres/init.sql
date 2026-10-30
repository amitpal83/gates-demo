-- FICTIONAL demo data only: the names, dates and amounts below do not describe real people or policies.
-- Idempotent: safe to run on a fresh volume (docker-entrypoint-initdb.d) and by hand on an existing one:
--   docker compose ... exec -T policy-postgres psql -U lic -d lic_policies < ontology_graph/postgres/init.sql
-- It replaces the earlier Nivesh Plus demo tables.

DROP TABLE IF EXISTS policy_transactions CASCADE;
DROP TABLE IF EXISTS policies CASCADE;
DROP TABLE IF EXISTS customer_policy CASCADE;
DROP TABLE IF EXISTS installment_master CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

CREATE TABLE customers (
    customer_id   TEXT PRIMARY KEY,
    full_name     TEXT NOT NULL,
    date_of_birth DATE NOT NULL,
    city          TEXT NOT NULL
);

-- Valid mode codes only. What each code means is deliberately NOT stored here (as in many legacy systems); it lives in the plan ontology.
CREATE TABLE installment_master (
    mode_code SMALLINT PRIMARY KEY,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE customer_policy (
    policy_number             TEXT PRIMARY KEY,
    customer_id               TEXT NOT NULL REFERENCES customers (customer_id),
    plan_uin                  TEXT NOT NULL,
    plan_name                 TEXT NOT NULL,
    installment_premium       NUMERIC(12, 2) NOT NULL,
    mode_code                 SMALLINT NOT NULL REFERENCES installment_master (mode_code),
    premium_paying_term_years INTEGER NOT NULL,
    policy_term_years         INTEGER NOT NULL,
    basic_sum_assured         NUMERIC(14, 2) NOT NULL,
    start_date                DATE NOT NULL,
    last_paid_date            DATE NOT NULL,
    status                    TEXT NOT NULL
);

COMMENT ON COLUMN customer_policy.installment_premium IS 'Amount in rupees paid at each installment';
COMMENT ON COLUMN customer_policy.mode_code IS 'Number of installments per year';
COMMENT ON COLUMN customer_policy.premium_paying_term_years IS 'Number of years for which premiums are paid';
COMMENT ON COLUMN customer_policy.policy_term_years IS 'Number of years the cover runs';
COMMENT ON COLUMN customer_policy.start_date IS 'Date the policy commenced; the first installment was paid on this date';
COMMENT ON COLUMN customer_policy.last_paid_date IS 'Due date of the most recent installment paid';

INSERT INTO installment_master (mode_code, is_active) VALUES (1, TRUE), (3, TRUE), (6, TRUE), (12, TRUE);

INSERT INTO customers (customer_id, full_name, date_of_birth, city) VALUES
    ('CUST-001', 'Anita Rao',      '1989-03-20', 'Pune'),
    ('CUST-002', 'Vikram Shah',    '1982-03-12', 'Ahmedabad'),
    ('CUST-003', 'Neha Kulkarni',  '1995-03-25', 'Nagpur'),
    ('CUST-004', 'Imran Qureshi',  '1986-03-08', 'Hyderabad');

-- All four: annualized premium 60,000, premium paying term 10, policy term 20, started 1 Apr 2024, so the truth is 6,00,000 over the paying term.
INSERT INTO customer_policy
    (policy_number, customer_id, plan_uin, plan_name, installment_premium, mode_code, premium_paying_term_years, policy_term_years, basic_sum_assured, start_date, last_paid_date, status) VALUES
    ('P012-0001', 'CUST-001', '512L361V01', 'LIC''s Protection Plus', 60000.00,  1, 10, 20,  600000.00, '2024-04-01', '2026-04-01', 'In force'),
    ('P012-0002', 'CUST-002', '512L361V01', 'LIC''s Protection Plus', 30000.00,  6, 10, 20,  600000.00, '2024-04-01', '2026-10-01', 'In force'),
    ('P012-0003', 'CUST-003', '512L361V01', 'LIC''s Protection Plus', 15000.00,  3, 10, 20,  900000.00, '2024-04-01', '2026-10-01', 'In force'),
    ('P012-0004', 'CUST-004', '512L361V01', 'LIC''s Protection Plus',  5000.00, 12, 10, 20,  600000.00, '2024-04-01', '2026-10-01', 'In force');
