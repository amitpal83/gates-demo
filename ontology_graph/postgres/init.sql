-- FICTIONAL demo data only: the names, dates and amounts below do not describe real people or policies.
-- Runs once, when the policy-postgres volume is first created.

CREATE TABLE policies (
    policy_number                TEXT PRIMARY KEY,
    holder_name                  TEXT NOT NULL,
    date_of_birth                DATE NOT NULL,
    age_at_entry                 INTEGER NOT NULL,
    plan_uin                     TEXT NOT NULL,
    plan_name                    TEXT NOT NULL,
    sum_assured_option           SMALLINT NOT NULL CHECK (sum_assured_option IN (1, 2)),
    basic_sum_assured            NUMERIC(14, 2) NOT NULL,
    single_premium               NUMERIC(14, 2) NOT NULL,
    sale_channel                 TEXT NOT NULL CHECK (sale_channel IN ('offline', 'online')),
    policy_term_years            INTEGER NOT NULL,
    fund_name                    TEXT NOT NULL,
    commencement_date            DATE NOT NULL,
    maturity_date                DATE NOT NULL,
    status                       TEXT NOT NULL,
    nominee_name                 TEXT,
    nominee_relationship         TEXT,
    rider_opted                  BOOLEAN NOT NULL DEFAULT FALSE,
    accident_benefit_sum_assured NUMERIC(14, 2),
    units_held                   NUMERIC(16, 4) NOT NULL,
    last_nav                     NUMERIC(10, 4) NOT NULL,
    unit_fund_value              NUMERIC(14, 2) NOT NULL,
    valuation_date               DATE NOT NULL
);

CREATE TABLE policy_transactions (
    id            SERIAL PRIMARY KEY,
    policy_number TEXT NOT NULL REFERENCES policies (policy_number),
    txn_date      DATE NOT NULL,
    txn_type      TEXT NOT NULL,
    amount_inr    NUMERIC(14, 2),
    note          TEXT
);

INSERT INTO policies VALUES
    ('LIC-NP-0001', 'Asha Verma', '1995-04-12', 26, '512L317V02', 'LIC''s Nivesh Plus', 2, 1250000.00, 125000.00, 'offline', 20,
     'Balanced Fund', '2021-03-15', '2041-03-15', 'In force', 'Rahul Verma', 'Spouse', FALSE, NULL,
     9480.2150, 17.8520, 169240.80, '2026-10-28'),
    ('LIC-NP-0002', 'Rohan Mehta', '1988-09-02', 36, '512L317V02', 'LIC''s Nivesh Plus', 1, 375000.00, 300000.00, 'online', 15,
     'Growth Fund', '2024-08-01', '2039-08-01', 'In force', 'Meera Mehta', 'Spouse', TRUE, 375000.00,
     21350.5000, 14.9120, 318378.66, '2026-10-28');

INSERT INTO policy_transactions (policy_number, txn_date, txn_type, amount_inr, note) VALUES
    ('LIC-NP-0001', '2023-09-04', 'switch', NULL, 'Growth Fund to Secured Fund'),
    ('LIC-NP-0001', '2026-05-20', 'switch', NULL, 'Secured Fund to Balanced Fund');
