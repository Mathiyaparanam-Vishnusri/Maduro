import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict

API = "http://127.0.0.1:8088"

run    = requests.get(f"{API}/runs/latest").json()
RUN_ID = run["run_id"]
print(f"Run: {RUN_ID}")

rules  = requests.get(f"{API}/rules").json()
skus   = {s["sku_id"]: s for s in requests.get(f"{API}/runs/{RUN_ID}/skus").json()["skus"]}
print(f"Evaluating OPEN missions...")

SUCCESS_PP   = float(rules.get("a5_success_threshold_pp", 2.00))
PARTIAL_PP   = float(rules.get("a5_partial_threshold_pp", 0.50))
RULE_VERSION = rules.get("rule_version", "v1.0")

REVIEW_WINDOWS = {
    "MARGIN_COST" : {"earliest_days": 3,  "primary_days": 7,  "final_days": 14},
    "CONVERSION"  : {"earliest_days": 14, "primary_days": 21, "final_days": 30},
    "OPERATIONAL" : {"earliest_days": 7,  "primary_days": 14, "final_days": 30},
    "DEMAND"      : {"earliest_days": 14, "primary_days": 30, "final_days": 45},
    "UNKNOWN"     : {"earliest_days": 7,  "primary_days": 14, "final_days": 30},
}

def classify_outcome(nnr_at_open, nnr_current):
    if nnr_at_open is None or nnr_current is None:
        return "UNKNOWN"
    improvement = float(nnr_current) - float(nnr_at_open)
    if   improvement >= SUCCESS_PP: return "SUCCESS"
    elif improvement >= PARTIAL_PP: return "PARTIAL"
    else:                           return "FAIL"

def doctrine_proposal(fail_count, driver_cat, total):
    if total == 0: return None
    if fail_count / total >= 0.50:
        return (f"REVIEW THRESHOLD: {fail_count}/{total} missions in "
                f"{driver_cat} category FAILED — consider tightening "
                f"entry criteria or adding a new driver signal.")
    return None

approved_missions = requests.get(f"{API}/missions?status=OPEN").json().get("missions", [])
print(f"Found {len(approved_missions)} OPEN missions")

processed      = 0
outcome_by_cat = defaultdict(lambda: {"total": 0, "fail": 0})
today          = datetime.now(timezone.utc).date()

for m in approved_missions:
    sku_id       = m["sku_id"]
    mission_id   = m.get("mission_id", "UNKNOWN")
    mission_type = m.get("mission_type", "UNKNOWN")
    ph_holder    = m.get("ph_holder", "Unassigned")
    primary_drv  = m.get("primary_driver", "unidentified")
    driver_cat   = m.get("driver_category") or "UNKNOWN"

    sku         = skus.get(sku_id, {})
    nnr_current = sku.get("nnr_pct_30d") or sku.get("nnr_pct_3m")

    mission_run_id = m.get("run_id", RUN_ID)
    a1_at_open = requests.get(f"{API}/agent-output/{mission_run_id}/AGENT_1").json().get("results", [])
    a1_map = {r["sku_id"]: r["output_data"] for r in a1_at_open}

    nnr_at_open = None
    reason_anchor = a1_map.get(sku_id, {}).get("reason_anchor", "")
    try:
        nnr_at_open = float(reason_anchor.split("=")[-1])
    except (ValueError, IndexError):
        nnr_at_open = None

    outcome = classify_outcome(nnr_at_open, nnr_current)

    window = REVIEW_WINDOWS.get(driver_cat, REVIEW_WINDOWS["UNKNOWN"])
    mission_date = m.get("created_at")
    try:
        opened_on = datetime.fromisoformat(str(mission_date)).date()
    except Exception:
        opened_on = today

    earliest_review = str(opened_on + timedelta(days=window["earliest_days"]))
    primary_review  = str(opened_on + timedelta(days=window["primary_days"]))
    final_review    = str(opened_on + timedelta(days=window["final_days"]))

    outcome_by_cat[driver_cat]["total"] += 1
    if outcome == "FAIL":
        outcome_by_cat[driver_cat]["fail"] += 1

    result = {
        "sku_id": sku_id, "mission_id": mission_id,
        "mission_type": mission_type, "ph_holder": ph_holder,
        "primary_driver": primary_drv, "driver_category": driver_cat,
        "nnr_at_mission_open": nnr_at_open,
        "nnr_current_30d": nnr_current,
        "nnr_improvement_pp": (
            round(float(nnr_current) - float(nnr_at_open), 2)
            if nnr_at_open is not None and nnr_current is not None else None
        ),
        "outcome_classification": outcome,
        "review_window_earliest": earliest_review,
        "review_window_primary":  primary_review,
        "review_window_final":    final_review,
        "evaluated_at": str(today),
        "governance_status": "PENDING_REVIEW",
        "rule_version_id": RULE_VERSION
    }

    requests.post(f"{API}/agent-output", json={
        "run_id": RUN_ID, "sku_id": sku_id,
        "agent": "AGENT_5", "output_data": result
    })
    print(f"  {sku_id[:35]} → {outcome} | NNR open:{nnr_at_open} now:{nnr_current}")
    processed += 1

print("\n📋 Doctrine Change Proposals:")
proposals_found = False
for cat, counts in outcome_by_cat.items():
    proposal = doctrine_proposal(counts["fail"], cat, counts["total"])
    if proposal:
        print(f"  ⚠️  {cat}: {proposal}")
        proposals_found = True
if not proposals_found:
    print("  None required — failure rates within acceptable range.")

print(f"\n✅ Agent 5 complete! Processed: {processed} missions")
