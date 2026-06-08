-- ============================================================
-- MADURO — Full Database Schema
-- Run this once to set up all tables
-- ============================================================

-- 1. Pipeline runs tracker
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id               VARCHAR(30) PRIMARY KEY,
    run_timestamp        TIMESTAMP   NOT NULL DEFAULT NOW(),
    rule_version_id      VARCHAR(20) NOT NULL DEFAULT 'v1.0',
    total_skus_processed INTEGER     DEFAULT 0,
    total_fail_count     INTEGER     DEFAULT 0,
    global_freeze        BOOLEAN     DEFAULT FALSE,
    status               VARCHAR(20) DEFAULT 'RUNNING'
);

-- 2. RuleStore — all thresholds here, ZERO hardcoded in code
CREATE TABLE IF NOT EXISTS rule_config (
    rule_key    VARCHAR(100) PRIMARY KEY,
    rule_value  TEXT         NOT NULL,
    agent       VARCHAR(20)  NOT NULL,
    description TEXT,
    version     VARCHAR(20)  DEFAULT 'v1.0',
    updated_at  TIMESTAMP    DEFAULT NOW()
);

-- 3. Raw input data (one row per SKU per run)
CREATE TABLE IF NOT EXISTS raw_input_data (
    run_id                VARCHAR(30) REFERENCES pipeline_runs(run_id),
    sku_id                VARCHAR(50) NOT NULL,
    sku_name              TEXT,
    asin                  VARCHAR(20),
    ph_holder             VARCHAR(100) NOT NULL,
    account               VARCHAR(50)  NOT NULL,
    nnr_pct_3m            NUMERIC(8,2),
    nnr_pct_30d           NUMERIC(8,2),
    nnr_pct_10d           NUMERIC(8,2),
    nnr_pct_5d            NUMERIC(8,2),
    orders_3m             INTEGER,
    orders_30d            INTEGER,
    orders_10d            INTEGER,
    orders_5d             INTEGER,
    revenue_3m            NUMERIC(12,2),
    revenue_30d           NUMERIC(12,2),
    revenue_10d           NUMERIC(12,2),
    revenue_5d            NUMERIC(12,2),
    nnr_gbp_3m            NUMERIC(12,2),
    nnr_gbp_30d           NUMERIC(12,2),
    sessions_3m           INTEGER,
    sessions_30d          INTEGER,
    cvr_pct_30d           NUMERIC(8,2),
    ppc_spend_30d         NUMERIC(12,2),
    ppc_sales_30d         NUMERIC(12,2),
    acos_pct_30d          NUMERIC(8,2),
    return_pct_30d        NUMERIC(8,2),
    postage_pct_income_3m NUMERIC(8,2),
    buybox_pct_30d        NUMERIC(8,2),
    total_income_3m       NUMERIC(12,2),
    total_expenses_3m     NUMERIC(12,2),
    margin_pct_3m         NUMERIC(8,2),
    stock_days_cover      INTEGER,
    cvr_pct_3m            NUMERIC(8,2),
    acos_pct_3m           NUMERIC(8,2),
    return_pct_3m         NUMERIC(8,2),
    buybox_pct_3m         NUMERIC(8,2),
    postage_pct_income    NUMERIC(8,2),
    PRIMARY KEY (run_id, sku_id)
);

-- 4. Agent outputs (all 5 agents write here)
CREATE TABLE IF NOT EXISTS agent_outputs (
    id              SERIAL,
    run_id          VARCHAR(30) REFERENCES pipeline_runs(run_id),
    sku_id          VARCHAR(50) NOT NULL,
    agent           VARCHAR(10) NOT NULL,  -- AGENT_0 to AGENT_4
    output_data     JSONB       NOT NULL,
    rule_version_id VARCHAR(20) DEFAULT 'v1.0',
    created_at      TIMESTAMP   DEFAULT NOW()
);

-- 5. SKU state history (most critical — feeds hysteresis)
CREATE TABLE IF NOT EXISTS sku_state_history (
    run_id            VARCHAR(30) REFERENCES pipeline_runs(run_id),
    sku_id            VARCHAR(50) NOT NULL,
    current_state     VARCHAR(20) NOT NULL,
    nnr_pct_30d       NUMERIC(8,2),
    nnr_pct_10d       NUMERIC(8,2),
    data_quality_flag VARCHAR(10),
    mission_decision  VARCHAR(10),
    state_change      VARCHAR(15),
    sp_amber          INTEGER    DEFAULT 0,
    sp_red            INTEGER    DEFAULT 0,
    run_timestamp     TIMESTAMP  NOT NULL DEFAULT NOW()
);

-- 6. Missions (final output)
CREATE TABLE IF NOT EXISTS missions (
    mission_id         VARCHAR(30) PRIMARY KEY,
    run_id             VARCHAR(30) REFERENCES pipeline_runs(run_id),
    sku_id             VARCHAR(50) NOT NULL,
    sku_name           TEXT,
    ph_holder          VARCHAR(100) NOT NULL,
    mission_type       VARCHAR(20)  NOT NULL,
    current_state      VARCHAR(20),
    primary_driver     VARCHAR(50),
    driver_type        VARCHAR(20),
    state_confidence   INTEGER,
    driver_confidence  INTEGER,
    mission_confidence INTEGER,
    action_required    TEXT,
    deadline           DATE,
    next_review_date   DATE,
    block_reason       VARCHAR(50),
    status             VARCHAR(20) DEFAULT 'OPEN',
    created_at         TIMESTAMP   DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_agent_outputs_run    ON agent_outputs(run_id, sku_id, agent);
CREATE INDEX IF NOT EXISTS idx_state_history_sku    ON sku_state_history(sku_id, run_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_missions_status      ON missions(status, ph_holder);
CREATE INDEX IF NOT EXISTS idx_raw_input_run        ON raw_input_data(run_id);
