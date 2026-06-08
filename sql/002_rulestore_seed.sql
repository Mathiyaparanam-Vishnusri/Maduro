-- ============================================================
-- MADURO — RuleStore Seed Data v1.0
-- TL can edit these values directly — no code change needed
-- ============================================================

INSERT INTO rule_config (rule_key, rule_value, agent, description) VALUES
-- AGENT 0: Data Guard
('a0_orders_3m_min',        '30',   'AGENT_0', 'Min 3M orders for data sufficiency'),
('a0_orders_30d_min',       '10',   'AGENT_0', 'Min 30D orders'),
('a0_orders_10d_min',       '5',    'AGENT_0', 'Min 10D orders'),
('a0_orders_5d_min',        '3',    'AGENT_0', 'Min 5D orders'),
('a0_deduct_3m',            '10',   'AGENT_0', 'Deduction if 3M orders < min'),
('a0_deduct_30d',           '10',   'AGENT_0', 'Deduction if 30D orders < min'),
('a0_deduct_10d',           '5',    'AGENT_0', 'Deduction if 10D orders < min'),
('a0_deduct_5d',            '5',    'AGENT_0', 'Deduction if 5D orders < min'),
('a0_deduct_per_null',      '2',    'AGENT_0', 'Deduction per null field'),
('a0_score_rich',           '71',   'AGENT_0', 'Score >= this = Rich category'),
('a0_score_adequate',       '40',   'AGENT_0', 'Score >= this = Adequate category'),
('a0_score_warn',           '32',   'AGENT_0', 'Score >= this = WARN (Thin)'),
('a0_global_freeze_min',    '20',   'AGENT_0', 'Min FAIL count to trigger global freeze'),
('a0_global_freeze_pct',    '20',   'AGENT_0', 'Pct of SKUs to trigger global freeze'),

-- AGENT 1: State Sentinel
('a1_dark_green_min',       '15',   'AGENT_1', 'NNR%_30D > this = Dark_Green'),
('a1_light_green_min',      '5',    'AGENT_1', 'NNR%_30D >= this = Light_Green'),
('a1_amber_min',            '0',    'AGENT_1', 'NNR%_30D >= this = Amber'),
('a1_hysteresis_buffer',    '2',    'AGENT_1', 'Buffer pp above threshold for state exit'),
('a1_sp_amber_confirm',     '2',    'AGENT_1', 'Sustained periods to confirm Amber'),
('a1_sp_red_confirm',       '3',    'AGENT_1', 'Sustained periods to confirm Red'),
('a1_thin_cap_score',       '40',   'AGENT_1', 'Score below this caps state at Light_Green'),
('a1_persistence_1',        '50',   'AGENT_1', 'PersistenceScore: 1 period'),
('a1_persistence_2',        '75',   'AGENT_1', 'PersistenceScore: 2 periods'),
('a1_persistence_3',        '90',   'AGENT_1', 'PersistenceScore: 3 periods'),
('a1_persistence_4plus',    '100',  'AGENT_1', 'PersistenceScore: 4+ periods'),

-- AGENT 2: Driver Analyst
('a2_postage_high',         '25',   'AGENT_2', 'Postage% > this = margin driver'),
('a2_margin_low',           '5',    'AGENT_2', 'Margin% < this = margin driver'),
('a2_traffic_drop_pct',     '20',   'AGENT_2', 'Sessions drop >= this% = traffic driver'),
('a2_cvr_decline_pct',      '30',   'AGENT_2', 'CVR relative decline >= this% = conversion driver'),
('a2_acos_increase',        '8',    'AGENT_2', 'ACoS increase >= this pp = PPC driver'),
('a2_return_increase',      '5',    'AGENT_2', 'Return% increase >= this pp = returns driver'),
('a2_buybox_drop',          '20',   'AGENT_2', 'BuyBox drop >= this pp = buybox driver'),
('a2_stock_low_days',       '7',    'AGENT_2', 'Stock < this days = stockout risk'),
('a2_conf_high',            '80',   'AGENT_2', 'High confidence threshold'),
('a2_conf_medium',          '70',   'AGENT_2', 'Medium confidence threshold'),
('a2_conf_low',             '60',   'AGENT_2', 'Low confidence threshold'),

-- AGENT 3: Cadence Control
('a3_cadence_red',          '5',    'AGENT_3', 'Review frequency days for Red state'),
('a3_cadence_amber',        '5',    'AGENT_3', 'Review frequency days for Amber state'),
('a3_cadence_light_green',  '14',   'AGENT_3', 'Review frequency days for Light_Green'),
('a3_cadence_dark_green',   '14',   'AGENT_3', 'Review frequency days for Dark_Green'),
('a3_cooldown_flips',       '3',    'AGENT_3', 'State alternations to trigger cooldown'),
('a3_state_conf_min',       '70',   'AGENT_3', 'Min StateConfidence for escalation'),
('a3_driver_conf_min',      '70',   'AGENT_3', 'Min DriverConfidence for escalation'),

-- AGENT 4: Mission Selector gates
('a4_gate1_score_min',      '40',   'AGENT_4', 'Gate 1: min data quality score'),
('a4_gate3_sp_amber',       '2',    'AGENT_4', 'Gate 3: min sustained Amber periods'),
('a4_gate3_sp_red',         '3',    'AGENT_4', 'Gate 3: min sustained Red periods'),
('a4_gate4_conf_min',       '70',   'AGENT_4', 'Gate 4: min DriverConfidence'),
('a4_gate5_state_conf_min', '70',   'AGENT_4', 'Gate 5: min StateConfidence'),
('a4_mission_conf_min',     '75',   'AGENT_4', 'Min MissionConfidence to OPEN'),
('a4_red_strike_days',      '1',    'AGENT_4', 'Deadline days: RED_STRIKE'),
('a4_amber_fix_days',       '3',    'AGENT_4', 'Deadline days: AMBER_FIX'),
('a4_amber_watch_days',     '7',    'AGENT_4', 'Deadline days: AMBER_WATCH')

ON CONFLICT (rule_key) DO NOTHING;
