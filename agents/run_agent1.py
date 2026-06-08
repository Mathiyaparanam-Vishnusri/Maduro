import requests

API = "http://127.0.0.1:8088"

run    = requests.get(f"{API}/runs/latest").json()
RUN_ID = run["run_id"]
print(f"Run: {RUN_ID}")

rules = requests.get(f"{API}/rules").json()
skus  = requests.get(f"{API}/runs/{RUN_ID}/skus").json()["skus"]
a0    = {r["sku_id"]: r["output_data"]
         for r in requests.get(f"{API}/agent-output/{RUN_ID}/AGENT_0").json()["results"]}
print(f"SKUs: {len(skus)}")

PURPLE_3M   = float(rules.get("a1_purple_min_3m",      25.00))
PURPLE_30D  = float(rules.get("a1_purple_min_30d",     20.00))
DG_3M       = float(rules.get("a1_dark_green_min_3m",  15.00))
DG_30D      = float(rules.get("a1_dark_green_min_30d", 12.00))
LG_3M       = float(rules.get("a1_light_green_min_3m",  8.00))
LG_30D      = float(rules.get("a1_light_green_min_30d", 6.00))
HYSTERESIS  = float(rules.get("a1_hysteresis_buffer",   2.00))
THIN_DSS    = float(rules.get("a1_thin_dss_threshold",  40))
RED_SUSTAIN = int(rules.get("a1_red_sustained",          3))
AMB_SUSTAIN = int(rules.get("a1_amber_sustained",        2))
RULE_VERSION = rules.get("rule_version", "v1.0")


def classify_state(nnr30, nnr3m, nnr10, dss_score, prev_state, sp_amber, sp_red):
    if nnr30 is None and nnr3m is None:
        return "Data_Risk", False
    if nnr30 is None:
        # 30D is required for state classification — without it we can't classify
        return "Data_Risk", False

    n30 = float(nnr30) if nnr30 is not None else 0.0
    n3m = float(nnr3m) if nnr3m is not None else 0.0
    # If 10D is NULL and 30D is negative → use 30D as proxy for 10D
    if nnr10 is not None:
        n10 = float(nnr10)
    elif nnr30 is not None and float(nnr30) < 0:
        n10 = float(nnr30)
    else:
        n10 = 0.0

    exit_to_lg_30d  = LG_30D  + HYSTERESIS
    exit_to_dg_30d  = DG_30D  + HYSTERESIS
    exit_to_pur_30d = PURPLE_30D + HYSTERESIS
    exit_red_30d    = 0.0 + HYSTERESIS

    if n3m >= PURPLE_3M and n30 >= PURPLE_30D:
        base = "Purple"
    elif n3m >= DG_3M and n30 >= DG_30D:
        base = "Dark_Green"
    elif n3m >= LG_3M and n30 >= LG_30D:
        base = "Light_Green"
    elif n30 < 0 and n10 < 0:
        base = "Red"
    else:
        base = "Amber"

    STATE_ORDER = {"Data_Risk": 0, "Red": 1, "Amber": 2,
                   "Light_Green": 3, "Dark_Green": 4, "Purple": 5}

    if prev_state and STATE_ORDER.get(prev_state, 3) < STATE_ORDER.get(base, 3):
        if prev_state == "Red" and base in ("Amber", "Light_Green", "Dark_Green", "Purple"):
            if n30 < exit_red_30d: base = "Red"
        elif prev_state == "Amber" and base in ("Light_Green", "Dark_Green", "Purple"):
            if n30 < exit_to_lg_30d: base = "Amber"
        elif prev_state == "Light_Green" and base in ("Dark_Green", "Purple"):
            if n30 < exit_to_dg_30d: base = "Light_Green"
        elif prev_state == "Dark_Green" and base == "Purple":
            if n30 < exit_to_pur_30d: base = "Dark_Green"

    if base == "Red" and sp_red < RED_SUSTAIN:
        base = "Amber"

    thin_data_cap_active = dss_score < THIN_DSS
    if thin_data_cap_active:
        base = "Light_Green"

    return base, thin_data_cap_active


for sku in skus:
    sid   = sku["sku_id"]
    nnr30 = sku.get("nnr_pct_30d")
    nnr3m = sku.get("nnr_pct_3m")
    nnr10 = sku.get("nnr_pct_10d")

    d0        = a0.get(sid, {})
    dss_score = int(d0.get("data_sufficiency_score", 0))

    history    = requests.get(f"{API}/history/{sid}").json().get("history", [])
    # Count distinct run_ids where state was Amber/Red (not duplicate runs)
    seen_runs  = set()
    sp_amber   = 0
    sp_red_raw = 0
    for h in history:
        rid = h.get("run_id","")
        if rid not in seen_runs:
            seen_runs.add(rid)
            if h["current_state"] == "Amber": sp_amber += 1
    # Count consecutive runs with negative NNR (for Red detection)
    seen_neg   = set()
    sp_red     = 0
    for h in history:
        rid = h.get("run_id","")
        if rid not in seen_neg:
            n30 = float(h.get("nnr_pct_30d") or 0)
            if n30 < 0:
                seen_neg.add(rid)
                sp_red += 1
    prev_state = history[0]["current_state"] if history else None

    # Add current run to sp counts if state matches
    # (history is read before current run is saved)
    state, thin_cap = classify_state(nnr30, nnr3m, nnr10,
                                      dss_score, prev_state,
                                      sp_amber, sp_red)
    if state == "Amber": sp_amber += 1
    if nnr30 is not None and float(nnr30) < 0: sp_red += 1
    # Re-classify with updated counts
    state, thin_cap = classify_state(nnr30, nnr3m, nnr10,
                                      dss_score, prev_state,
                                      sp_amber, sp_red)

    STATE_ORDER = {"Data_Risk": 0, "Red": 1, "Amber": 2,
                   "Light_Green": 3, "Dark_Green": 4, "Purple": 5}
    if prev_state:
        diff   = STATE_ORDER.get(state, 3) - STATE_ORDER.get(prev_state, 3)
        change = "Upgrade" if diff > 0 else "Downgrade" if diff < 0 else "No Change"
    else:
        change = "No Change"

    conf = 85
    ord3m_val = sku.get("orders_3m")
    if ord3m_val is not None and int(ord3m_val) < 10:
        conf -= 15
    if thin_cap:
        conf -= 10

    output = {
        "sku_id":               sid,
        "current_state":        state,
        "previous_state":       prev_state,
        "state_change":         change,
        "confidence_score":     conf,
        "sp_amber":             sp_amber,
        "sp_red":               sp_red,
        "thin_data_cap_active": thin_cap,
        "reason_anchor":        f"NNR%_30D={nnr30}",
        "reason_trend":         f"NNR%_3M={nnr3m}",
        "reason_10d":           f"NNR%_10D={nnr10}",
        "rule_version_id":      RULE_VERSION
    }

    requests.post(f"{API}/agent-output", json={
        "run_id": RUN_ID, "sku_id": sid,
        "agent": "AGENT_1", "output_data": output
    })
    requests.post(f"{API}/state-history", json={
        "run_id": RUN_ID, "sku_id": sid,
        "current_state": state, "nnr_pct_30d": nnr30,
        "state_change": change, "sp_amber": sp_amber,
        "sp_red": sp_red, "thin_data_cap_active": thin_cap
    })
    print(f"  {sid[:35]} → {state} (conf:{conf}) thin:{thin_cap} sp_amb:{sp_amber} sp_red:{sp_red}")

print("\n✅ Agent 1 complete!")
