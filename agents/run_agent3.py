import requests

API = "http://127.0.0.1:8088"

run    = requests.get(f"{API}/runs/latest").json()
RUN_ID = run["run_id"]
print(f"Run: {RUN_ID}")

rules = requests.get(f"{API}/rules").json()
skus  = requests.get(f"{API}/runs/{RUN_ID}/skus").json()["skus"]
a1    = {r["sku_id"]: r["output_data"]
         for r in requests.get(f"{API}/agent-output/{RUN_ID}/AGENT_1").json()["results"]}
a2    = {r["sku_id"]: r["output_data"]
         for r in requests.get(f"{API}/agent-output/{RUN_ID}/AGENT_2").json()["results"]}
print(f"SKUs: {len(skus)}")

# ── Rule values from RuleStore ────────────────────────────────────
CADENCE_RED_AMB = int(rules.get("a3_cadence_red",         5))   # 5D for Red AND Amber
CADENCE_LG      = int(rules.get("a3_cadence_light_green", 14))  # 14D
CADENCE_DG      = int(rules.get("a3_cadence_dark_green",  14))  # 14D
CADENCE_PURPLE  = int(rules.get("a3_cadence_purple",      30))  # 30D
STATE_CONF_MIN  = int(rules.get("a3_state_conf_min",      70))
DRIVER_CONF_MIN = int(rules.get("a3_driver_conf_min",     70))
COOLDOWN_TRIGGER= int(rules.get("a3_cooldown_trigger_runs", 3)) # escalations in a row → cooldown
COOLDOWN_RESET  = int(rules.get("a3_cooldown_reset_runs",   3)) # cooldown lasts N runs
RULE_VERSION    = rules.get("rule_version", "v1.0")


def get_cadence_days(state):
    """Return monitoring cadence in days for a given state."""
    if state in ("Red", "Amber"):
        return CADENCE_RED_AMB    # 5 days for both
    elif state == "Light_Green":
        return CADENCE_LG         # 14 days
    elif state == "Dark_Green":
        return CADENCE_DG         # 14 days
    else:                          # Purple, Data_Risk
        return CADENCE_PURPLE     # 30 days


def check_cooldown(history):
    """
    CooldownActive = TRUE if the SKU was escalation-allowed in each
    of the last COOLDOWN_TRIGGER consecutive runs.
    Cooldown then blocks escalation for the next COOLDOWN_RESET runs.

    Returns (cooldown_active, escalation_count_recent)
    """
    if len(history) < COOLDOWN_TRIGGER:
        return False, len(history)

    # Count consecutive escalation-allowed runs from most recent
    recent = history[:COOLDOWN_TRIGGER]
    consecutive_escalated = sum(
        1 for h in recent if h.get("escalation_allowed") is True
    )

    cooldown_active = consecutive_escalated >= COOLDOWN_TRIGGER
    return cooldown_active, consecutive_escalated


for sku in skus:
    sid = sku["sku_id"]

    d1          = a1.get(sid, {})
    d2          = a2.get(sid, {})
    state       = d1.get("current_state", "Light_Green")
    state_conf  = int(d1.get("confidence_score", 85))
    driver_type = d2.get("driver_classification", "Mixed")
    driver_conf = int(d2.get("driver_confidence_score", 0))

    cadence_days = get_cadence_days(state)

    # ── Cooldown check ───────────────────────────────────────────
    history = requests.get(f"{API}/history/{sid}").json().get("history", [])
    cooldown_active, esc_count = check_cooldown(history)

    # Escalation gate
    block_reason = None
    # Red state always escalates — urgency overrides all confidence gates
    if state == "Red":
        escalation_allowed = True
        block_reason = None
    elif cooldown_active:
        block_reason = f"CooldownActive (escalated {esc_count} runs in a row)"
        escalation_allowed = False
    elif driver_type == "Temporary":
        block_reason = "Temporary driver - monitor only"
        escalation_allowed = False
    elif state_conf < STATE_CONF_MIN:
        block_reason = f"StateConf {state_conf} < {STATE_CONF_MIN}"
        escalation_allowed = False
    elif driver_conf < DRIVER_CONF_MIN:
        block_reason = f"DriverConf {driver_conf} < {DRIVER_CONF_MIN}"
        escalation_allowed = False
    else:
        escalation_allowed = True
    output = {
        "sku_id":                  sid,
        "current_state":           state,
        "monitoring_cadence":      f"{cadence_days}D",
        "escalation_allowed":      escalation_allowed,
        "escalation_block_reason": block_reason,
        "cooldown_active":         cooldown_active,
        "state_confidence":        state_conf,
        "driver_confidence":       driver_conf,
        "rule_version_id":         RULE_VERSION
    }

    requests.post(f"{API}/agent-output", json={
        "run_id": RUN_ID, "sku_id": sid,
        "agent": "AGENT_3", "output_data": output
    })
    print(f"  {sid[:35]} → {state} | cadence:{cadence_days}D "
          f"| escalation:{escalation_allowed} | cooldown:{cooldown_active}")

print("\n✅ Agent 3 complete!")
