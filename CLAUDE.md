# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

MADURO is a SKU economic-health intelligence pipeline for Amazon listings. It runs a chain of 5 sequential "agents" (Python scripts) that classify each SKU's financial health, diagnose what's driving decline, decide monitoring cadence, and emit actionable "missions" for product handlers (PHs). NNR% (Net Net Return %) over rolling windows (5D/10D/30D/3M) is the central metric.

The agents do NOT talk to the DB directly — they call a **FastAPI middle layer** (`api/main.py`) over HTTP, which is the only component that touches PostgreSQL (`config/db.py`). The original design intended "OpenClaw AI" to run the agent logic via these endpoints; the `agents/run_agent*.py` scripts are the concrete Python implementation of that logic.

## Commands

```bash
# Install deps
pip install -r requirements.txt

# One-time DB setup (runs sql/001_schema.sql + sql/002_rulestore_seed.sql)
python setup_db.py

# Start the API — NOTE: agents hardcode port 8088, not the README's 8000
cd api && uvicorn main:app --host 0.0.0.0 --port 8088 --reload

# Run the full daily pipeline (fetch → agents 0-5 → cleanup → analyze → Slack)
./run_pipeline.sh

# Run a single agent against the latest READY run (API must be up on 8088)
python3 agents/run_agent2.py
bash   agents/run_agent1.sh    # agent 1 needs PYTHONPATH, so it has a wrapper

# Load data manually from CSV instead of MySQL
python loaders/csv_loader.py --file your_amazon_data.csv
```

There is **no test framework** (the `tests/` dir is empty) and no linter configured. Verify changes by running the API and hitting endpoints / running an individual agent.

## Architecture

### The agent chain (order matters — each reads prior outputs)
`run_pipeline.sh` runs them in sequence; each agent pulls the latest run via `GET /runs/latest`, reads upstream results via `GET /agent-output/{run_id}/AGENT_N`, and writes its own via `POST /agent-output`.

- **Agent 0 — Data Guard** (`run_agent0.py`): scores data sufficiency (0-100) per SKU from order counts and null fields; flags FAIL/WARN and can trigger a global freeze.
- **Agent 1 — State Sentinel** (`run_agent1.py`): classifies each SKU into `Purple / Dark_Green / Light_Green / Amber / Red / Data_Risk` from NNR% thresholds. Uses **hysteresis** (a buffer so SKUs don't flip-flop) and **sustained-period counters** (`sp_amber`/`sp_red`) read from `sku_state_history`. Writes state history via `POST /state-history`.
- **Agent 2 — Driver Analyst** (`run_agent2.py`): for Amber/Red SKUs, picks the `primary_driver` (margin compression, PPC inflation, CVR decline, stock depth, etc.) and maps it to a category (MARGIN_COST / CONVERSION / OPERATIONAL / DEMAND) + type (Structural/Temporary) via the `TAXONOMY` dict.
- **Agent 3 — Cadence Control** (`run_agent3.py`): sets monitoring cadence (days) by state and applies escalation cooldowns.
- **Agent 4 — Mission Selector** (`run_agent4.py`): runs a series of **gates** (data score, sustained periods, confidence minimums) to APPROVE / HOLD / REJECT a mission, then `POST /missions` with type `RED_STRIKE` / `AMBER_FIX` / `AMBER_WATCH` and a deadline.
- **Agent 5 — Outcome Review** (`run_agent5.py`): re-evaluates OPEN missions after their review window, classifies SUCCESS/PARTIAL/FAIL by NNR improvement, and proposes doctrine/threshold changes.

After the agents, `run_pipeline.sh` does SQL cleanup (dedup agent_outputs/missions, backfill deadlines), then `openclaw_analyze.py` (writes a summary to `/tmp/maduro_analysis.txt`) and `slack_notify.py` (posts the daily report to Slack).

### RuleStore pattern (important)
**No thresholds are hardcoded in agent logic.** All tunable values live in the `rule_config` table (seeded by `sql/002_rulestore_seed.sql`), keyed `a{N}_*` per agent and scoped by `version` (`RULE_VERSION`, default `v1.0`). Agents fetch them via `GET /rules`. To change behavior, edit `rule_config` rows — do not add literals to the agent scripts. When adding a new rule, seed it in `002_rulestore_seed.sql` AND read it with a `rules.get(key, default)` fallback in the agent.

### Data ingestion (two paths)
- **MySQL fetcher** (`loaders/mysql_fetcher_v2.py`, driven by `run_fetcher.py`): pulls live Amazon UK order/account/PPC data from remote MySQL DBs (`config/mysql.py` maps logical names to physical DBs) and loads `raw_input_data`. `run_fetcher.py` creates the `RUN-YYYY-MM-DD-NNN` run id, and if the fetch yields 0 SKUs it **auto-copies base columns from the previous READY run** so the pipeline still has data.
- **CSV loader** (`loaders/csv_loader.py`): loads an Amazon export, mapping human column names (`NNR%_30D`, etc.) to DB columns via `COLUMN_MAP`.

### Database tables (`sql/001_schema.sql`)
`pipeline_runs` (run tracker) → `raw_input_data` (one row per SKU per run) → `agent_outputs` (JSONB blob per agent per SKU) → `sku_state_history` (feeds hysteresis) → `missions` (final output). `agent_outputs.output_data` is freeform JSONB, so agents read upstream fields with `.get()`.

## Conventions & gotchas

- **Port mismatch**: the README says port 8000 but every agent and the dashboard use **8088**. Run the API on 8088.
- **Hardcoded absolute paths**: `run_pipeline.sh`, `run_fetcher.py`, and `agents/run_agent1.sh` hardcode `/home/led284/Downloads/maduro`. The `/ui` endpoint in `api/main.py` still points at a stale `/root/maduro/...` path. Update these if the repo moves.
- **Run id format**: `RUN-YYYY-MM-DD-NNN` (IST-dated in `run_fetcher.py`, sequence per day).
- **Dedup is a post-step, not enforced**: agents may write duplicate `agent_outputs`/`missions`; uniqueness is achieved by the cleanup SQL at the end of `run_pipeline.sh` and by `DISTINCT ON` in API read queries. Preserve both when changing those queries.
- **Secrets**: `.env` (gitignored) holds both PostgreSQL and remote MySQL credentials; `config/settings.py` and `config/mysql.py` read them. Slack token comes from an external `~/.openclaw/openclaw.json`.
- `.py.backup` / `_OLD` / `_v2` files exist alongside the live versions — `mysql_fetcher_v2.py` and `api/main.py` are the active ones.
