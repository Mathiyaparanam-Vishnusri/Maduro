import requests
from datetime import datetime, timedelta, timezone

API = "http://127.0.0.1:8088"

run    = requests.get(f"{API}/runs/latest").json()
RUN_ID = run["run_id"]
print(f"Run: {RUN_ID}")

rules = requests.get(f"{API}/rules").json()
skus  = {s["sku_id"]: s for s in requests.get(f"{API}/runs/{RUN_ID}/skus").json()["skus"]}
a0    = {r["sku_id"]: r["output_data"] for r in requests.get(f"{API}/agent-output/{RUN_ID}/AGENT_0").json()["results"]}
a1    = {r["sku_id"]: r["output_data"] for r in requests.get(f"{API}/agent-output/{RUN_ID}/AGENT_1").json()["results"]}
a2    = {r["sku_id"]: r["output_data"] for r in requests.get(f"{API}/agent-output/{RUN_ID}/AGENT_2").json()["results"]}
a3    = {r["sku_id"]: r["output_data"] for r in requests.get(f"{API}/agent-output/{RUN_ID}/AGENT_3").json()["results"]}
print(f"SKUs evaluated: {len(a1)}")

GATE1_SCORE_MIN  = int(rules.get("a4_gate1_score_min",   40))
GATE3_SP_AMBER   = int(rules.get("a4_gate3_sp_amber",     2))
GATE3_SP_RED     = int(rules.get("a4_gate3_sp_red",       3))
GATE4_CONF_MIN   = int(rules.get("a4_gate4_conf_min",    70))
GATE5_STATE_CONF = int(rules.get("a4_gate5_state_conf_min", 70))
CONF_THRESHOLD   = int(rules.get("a4_mission_conf_min",  75))
RED_DEADLINE     = int(rules.get("a4_red_strike_days",    1))
AMBER_DEADLINE   = int(rules.get("a4_amber_fix_days",     3))
RULE_VERSION     = rules.get("rule_version", "v1.0")

today    = datetime.now(timezone.utc).date()
approved = hold = rejected = 0

def persistence_score(periods):
    if   periods >= 4: return 100
    elif periods == 3: return 90
    elif periods == 2: return 75
    elif periods == 1: return 50
    else:              return 0

for sku_id, d1 in a1.items():
    d0   = a0.get(sku_id, {})
    d2   = a2.get(sku_id, {})
    d3   = a3.get(sku_id, {})
    sku  = skus.get(sku_id, {})

    state        = d1.get("current_state", "Light_Green")
    state_conf   = int(d1.get("confidence_score", 85))
    sp_amber     = int(d1.get("sp_amber", 0))
    sp_red       = int(d1.get("sp_red",   0))
    dss_score    = int(d0.get("data_sufficiency_score", 0))
    systemic     = bool(d0.get("systemic_issue_flag", False))
    driver_type  = d2.get("driver_classification", "Mixed")
    driver_conf  = int(d2.get("driver_confidence_score", 0))
    primary_drv  = d2.get("primary_driver", "unidentified")
    escalation   = bool(d3.get("escalation_allowed", False))
    ph_holder    = sku.get("ph_holder", "Unassigned")

    periods       = sp_red if state == "Red" else sp_amber
    persist_score = persistence_score(periods)
    mission_conf  = min(state_conf, driver_conf, persist_score)

    g1 = dss_score >= GATE1_SCORE_MIN and not systemic
    g2 = state in ("Amber", "Red")
    if state == "Red":
        g3 = sp_red >= GATE3_SP_RED
    elif state == "Amber":
        g3 = sp_amber >= GATE3_SP_AMBER
    else:
        g3 = False
    g4 = (driver_type == "Structural" and driver_conf >= GATE4_CONF_MIN) or state == "Red"
    g5 = (escalation and state_conf >= GATE5_STATE_CONF) or state == "Red"

    if not g1 or not g2:
        decision = "REJECT"; block_gate = "Gate1" if not g1 else "Gate2"
        mission_type = "N/A"; deadline_date = None; rejected += 1
    elif not g3:
        decision = "HOLD"; block_gate = "Gate3"
        mission_type = "N/A"; deadline_date = None; hold += 1
    elif not g4:
        decision = "HOLD"; block_gate = "Gate4"
        mission_type = "N/A"; deadline_date = None; hold += 1
    elif not g5:
        decision = "HOLD"; block_gate = "Gate5"
        mission_type = "N/A"; deadline_date = None; hold += 1
    elif mission_conf < CONF_THRESHOLD and state != "Red":
        decision = "HOLD"; block_gate = "MissionConf"
        mission_type = "N/A"; deadline_date = None; hold += 1
    else:
        decision = "OPEN"; block_gate = None
        if state == "Red":
            mission_type = "RED_STRIKE"
            deadline_date = str(today + timedelta(days=RED_DEADLINE))
        elif driver_type == "Mixed":
            # Amber + Mixed driver → AMBER_WATCH (7 days) per DOC-3
            mission_type = "AMBER_WATCH"
            deadline_date = str(today + timedelta(days=7))
        else:
            mission_type = "AMBER_FIX"
            deadline_date = str(today + timedelta(days=AMBER_DEADLINE))
        approved += 1

    # Write gate results to agent_outputs for dashboard gate analysis
    requests.post(f"{API}/agent-output", json={
        "run_id": RUN_ID, "sku_id": sku_id,
        "agent": "AGENT_4",
        "output_data": {
            "sku_id": sku_id,
            "current_state": state,
            "gate1_pass": g1,
            "gate2_pass": g2,
            "gate3_pass": g3,
            "gate4_pass": g4,
            "gate5_pass": g5,
            "block_gate": block_gate,
            "mission_type": mission_type,
            "mission_confidence": mission_conf,
            "persistence_score": persist_score,
            "decision": decision,
            "rule_version_id": RULE_VERSION
        }
    })

    requests.post(f"{API}/missions", json={
        "run_id": RUN_ID, "sku_id": sku_id, "sku_name": sku_id,
        "ph_holder": ph_holder, "mission_type": mission_type,
        "current_state": state, "primary_driver": primary_drv,
        "driver_classification": driver_type, "state_confidence": state_conf,
        "driver_confidence": driver_conf, "persistence_score": persist_score,
        "mission_confidence": mission_conf,
        "action_required": f"Review {primary_drv} for SKU {sku_id}",
        "deadline_date": deadline_date, "block_reason": block_gate,
        "status": decision, "rule_version_id": RULE_VERSION
    })
    print(f"  {sku_id[:35]} → {decision} | {mission_type} | conf:{mission_conf} | state:{state}")

print(f"\n✅ Agent 4 complete!")
print(f"   OPEN:{approved} | HOLD:{hold} | REJECT:{rejected}")
