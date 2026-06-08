"""
MADURO FastAPI — Middle layer between OpenClaw and PostgreSQL
OpenClaw agents call these endpoints to read data and write results
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Any
import json
from datetime import datetime, timedelta, timezone
from config.db import query
from config.settings import RULE_VERSION

app = FastAPI(title="MADURO API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": RULE_VERSION}


# ─────────────────────────────────────────────
# RULESTORE — OpenClaw reads thresholds here
# ─────────────────────────────────────────────
@app.get("/rules")
def get_all_rules():
    rows = query("SELECT rule_key, rule_value, agent, description FROM rule_config WHERE version=%s", (RULE_VERSION,))
    return {r["rule_key"]: r["rule_value"] for r in rows}

@app.get("/rules/{rule_key}")
def get_rule(rule_key: str):
    rows = query("SELECT rule_value FROM rule_config WHERE rule_key=%s AND version=%s", (rule_key, RULE_VERSION))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_key}' not found")
    return {"rule_key": rule_key, "rule_value": rows[0]["rule_value"]}


# ─────────────────────────────────────────────
# RAW DATA — OpenClaw reads input SKU data
# ─────────────────────────────────────────────
@app.get("/runs")
def list_runs():
    return query("SELECT * FROM pipeline_runs ORDER BY run_timestamp DESC LIMIT 20")

@app.get("/runs/{run_id}/skus")
def get_skus(run_id: str):
    rows = query("""
        SELECT DISTINCT ON (r.sku_id) r.*,
               (a.output_data->>'current_state') AS current_state,
               (a.output_data->>'confidence_score')::float AS state_confidence,
               (a.output_data->>'thin_data_cap_active')::boolean AS thin_data_cap_active
        FROM raw_input_data r
        LEFT JOIN agent_outputs a 
            ON a.run_id = r.run_id 
            AND a.sku_id = r.sku_id 
            AND a.agent = 'AGENT_1'
        WHERE r.run_id=%s
        ORDER BY r.sku_id, a.id DESC
    """, (run_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"No SKUs found for run {run_id}")
    return {"run_id": run_id, "total": len(rows), "skus": rows}

@app.get("/runs/{run_id}/pipeline-status")
def get_pipeline_status(run_id: str):
    rows = query("""
        SELECT agent,
               COUNT(*) as skus_processed,
               SUM(CASE
                   WHEN agent='AGENT_0' AND (output_data->>'data_quality_flag') IN ('OK','WARN','PASS') THEN 1
                   WHEN agent='AGENT_1' AND (output_data->>'current_state') IS NOT NULL THEN 1
                   WHEN agent='AGENT_2' AND (output_data->>'primary_driver') IS NOT NULL THEN 1
                   WHEN agent='AGENT_3' AND (output_data->>'monitoring_cadence') IS NOT NULL THEN 1
                   WHEN agent='AGENT_4' AND (output_data->>'status') IS NOT NULL THEN 1
                   WHEN agent='AGENT_5' AND (output_data->>'outcome_classification') IS NOT NULL THEN 1
                   ELSE 0
               END) as passed
        FROM agent_outputs
        WHERE run_id=%s
        GROUP BY agent
        ORDER BY agent
    """, (run_id,))
    result = {}
    for r in rows:
        result[r['agent']] = {
            'status': 'ok',
            'skus_processed': r['skus_processed'],
            'passed': r['passed'],
            'failed': int(r['skus_processed']) - int(r['passed'])
        }
    return {"agents": result, "run_id": run_id}

@app.get("/runs/{run_id}/skus/{sku_id}")
def get_sku(run_id: str, sku_id: str):
    rows = query("SELECT * FROM raw_input_data WHERE run_id=%s AND sku_id=%s", (run_id, sku_id))
    if not rows:
        raise HTTPException(status_code=404, detail="SKU not found")
    return rows[0]


# ─────────────────────────────────────────────
# STATE HISTORY — Agent 1 reads this
# ─────────────────────────────────────────────
@app.get("/history/{sku_id}")
def get_history(sku_id: str, limit: int = 10):
    rows = query(
        "SELECT * FROM sku_state_history WHERE sku_id=%s ORDER BY run_timestamp DESC LIMIT %s",
        (sku_id, limit)
    )
    return {"sku_id": sku_id, "history": rows}


# ─────────────────────────────────────────────
# AGENT OUTPUTS — OpenClaw writes results here
# ─────────────────────────────────────────────
class AgentOutputRequest(BaseModel):
    run_id: str
    sku_id: str
    agent: str       # AGENT_0, AGENT_1, AGENT_2, AGENT_3, AGENT_4
    output_data: dict

@app.post("/agent-output")
def save_agent_output(req: AgentOutputRequest):
    query(
        """INSERT INTO agent_outputs (run_id, sku_id, agent, output_data, rule_version_id)
           VALUES (%s, %s, %s, %s, %s)""",
        (req.run_id, req.sku_id, req.agent, json.dumps(req.output_data), RULE_VERSION),
        fetch=False
    )
    return {"status": "saved", "run_id": req.run_id, "sku_id": req.sku_id, "agent": req.agent}

@app.get("/agent-output/{run_id}/{agent}")
def get_agent_output(run_id: str, agent: str):
    rows = query("""
        SELECT DISTINCT ON (sku_id) sku_id, output_data 
        FROM agent_outputs 
        WHERE run_id=%s AND agent=%s
        ORDER BY sku_id, created_at DESC
    """, (run_id, agent.upper()))
    return {"run_id": run_id, "agent": agent, "results": rows}

@app.get("/agent-output/{run_id}/{agent}/{sku_id}")
def get_agent_output_sku(run_id: str, agent: str, sku_id: str):
    rows = query(
        "SELECT output_data FROM agent_outputs WHERE run_id=%s AND agent=%s AND sku_id=%s",
        (run_id, agent.upper(), sku_id)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Agent output not found")
    return rows[0]["output_data"]


# ─────────────────────────────────────────────
# STATE HISTORY WRITE — Agent 1 writes here
# ─────────────────────────────────────────────
class StateHistoryRequest(BaseModel):
    run_id: str
    sku_id: str
    current_state: str
    nnr_pct_30d: Optional[float] = None
    nnr_pct_10d: Optional[float] = None
    data_quality_flag: Optional[str] = None
    state_change: Optional[str] = None
    sp_amber: int = 0
    sp_red: int = 0

@app.post("/state-history")
def save_state_history(req: StateHistoryRequest):
    query(
        """INSERT INTO sku_state_history 
           (run_id, sku_id, current_state, nnr_pct_30d, nnr_pct_10d,
            data_quality_flag, state_change, sp_amber, sp_red)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (req.run_id, req.sku_id, req.current_state, req.nnr_pct_30d,
         req.nnr_pct_10d, req.data_quality_flag, req.state_change,
         req.sp_amber, req.sp_red),
        fetch=False
    )
    return {"status": "saved"}


# ─────────────────────────────────────────────
# MISSIONS — Agent 4 writes final output here
# ─────────────────────────────────────────────
class MissionRequest(BaseModel):
    run_id: str
    sku_id: str
    sku_name: Optional[str] = None
    ph_holder: str
    mission_type: str
    current_state: str
    primary_driver: Optional[str] = None
    driver_type: Optional[str] = None
    state_confidence: Optional[int] = None
    driver_confidence: Optional[int] = None
    mission_confidence: Optional[int] = None
    action_required: Optional[str] = None
    deadline_days: Optional[int] = None
    next_review_days: Optional[int] = None
    deadline_date: Optional[str] = None
    block_reason: Optional[str] = None
    status: str = "OPEN"
    persistence_score: Optional[int] = None
    rule_version_id: Optional[str] = None

@app.post("/missions")
def create_mission(req: MissionRequest):
    today = datetime.now(timezone.utc).date()
    import uuid
    mission_id = f"MSN-{today.strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"

    if req.deadline_days:
        deadline = today + timedelta(days=req.deadline_days)
    elif req.deadline_date:
        try:
            from datetime import date
            deadline = date.fromisoformat(req.deadline_date)
        except:
            deadline = None
    else:
        deadline = None
    next_review = (today + timedelta(days=req.next_review_days)) if req.next_review_days else None

    query(
        """INSERT INTO missions 
           (mission_id, run_id, sku_id, sku_name, ph_holder, mission_type,
            current_state, primary_driver, driver_type, state_confidence,
            driver_confidence, mission_confidence, action_required,
            deadline, next_review_date, block_reason, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (mission_id, req.run_id, req.sku_id, req.sku_name, req.ph_holder,
         req.mission_type, req.current_state, req.primary_driver, req.driver_type,
         req.state_confidence, req.driver_confidence, req.mission_confidence,
         req.action_required, deadline, next_review, req.block_reason, req.status),
        fetch=False
    )
    return {"status": "created", "mission_id": mission_id}

@app.get("/missions")
def list_missions(status: str = "OPEN", ph_holder: Optional[str] = None):
    if ph_holder:
        rows = query(
            "SELECT * FROM missions WHERE status=%s AND ph_holder=%s ORDER BY created_at DESC",
            (status, ph_holder)
        )
    else:
        rows = query("SELECT * FROM missions WHERE status=%s ORDER BY created_at DESC", (status,))
    return {"total": len(rows), "missions": rows}

@app.get("/missions/{run_id}")
def get_run_missions(run_id: str):
    rows = query("SELECT * FROM missions WHERE run_id=%s ORDER BY mission_type", (run_id,))
    return {"run_id": run_id, "total": len(rows), "missions": rows}


# ─────────────────────────────────────────────
# RUN COMPLETE — call after all agents finish
# ─────────────────────────────────────────────
class RunCompleteRequest(BaseModel):
    run_id: str
    total_skus: int
    fail_count: int
    global_freeze: bool = False

@app.post("/runs/complete")
def complete_run(req: RunCompleteRequest):
    query(
        """UPDATE pipeline_runs 
           SET status='COMPLETED', total_skus_processed=%s,
               total_fail_count=%s, global_freeze=%s
           WHERE run_id=%s""",
        (req.total_skus, req.fail_count, req.global_freeze, req.run_id),
        fetch=False
    )
    return {"status": "completed", "run_id": req.run_id}

@app.get("/runs/latest")
def get_latest_run():
    rows = query("SELECT * FROM pipeline_runs WHERE status='READY' ORDER BY run_timestamp DESC LIMIT 1")
    if not rows:
        raise HTTPException(status_code=404, detail="No ready runs found")
    return rows[0]


from fastapi.responses import FileResponse

@app.get("/ui")
def dashboard():
    return FileResponse("/root/maduro/maduro_dashboard.html")
