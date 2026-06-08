# MADURO — SKU Economic Health Intelligence System

## Stack
- **OpenClaw AI** — runs the 5 agents (logic)
- **Python FastAPI** — middle layer API between OpenClaw and DB
- **PostgreSQL** — stores all data

## How It Works
```
CSV (Amazon export)
      ↓
python loaders/csv_loader.py   ← loads raw data into DB
      ↓
PostgreSQL (raw_input_data)
      ↓
OpenClaw Agent 0  →  POST /agent-output  (Data Guard)
OpenClaw Agent 1  →  POST /agent-output  (State Sentinel)
OpenClaw Agent 2  →  POST /agent-output  (Driver Analyst)
OpenClaw Agent 3  →  POST /agent-output  (Cadence Control)
OpenClaw Agent 4  →  POST /missions      (Mission Selector)
      ↓
PostgreSQL (missions) ← Final output
```

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your Postgres credentials
```

### 3. Create database
```bash
psql -U postgres -c "CREATE DATABASE maduro;"
psql -U postgres -c "CREATE USER maduro_user WITH PASSWORD 'changeme';"
psql -U postgres -c "GRANT ALL ON DATABASE maduro TO maduro_user;"
```

### 4. Setup tables + RuleStore
```bash
python setup_db.py
```

### 5. Start the API
```bash
cd api
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Load your CSV data
```bash
python loaders/csv_loader.py --file your_amazon_data.csv
```

## API Endpoints (for OpenClaw)

| Method | Endpoint | Used By |
|--------|----------|---------|
| GET | /rules | All agents — load thresholds |
| GET | /runs/{run_id}/skus | All agents — read SKU data |
| GET | /history/{sku_id} | Agent 1 — read state history |
| POST | /agent-output | Agents 0-3 — save results |
| POST | /state-history | Agent 1 — save state |
| POST | /missions | Agent 4 — save mission cards |
| POST | /runs/complete | After all agents done |

## API Docs
Visit: http://localhost:8000/docs
