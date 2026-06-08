import requests

API = "http://127.0.0.1:8088"

run    = requests.get(f"{API}/runs/latest").json()
RUN_ID = run["run_id"]
print(f"Run: {RUN_ID}")

rules = requests.get(f"{API}/rules").json()
skus  = requests.get(f"{API}/runs/{RUN_ID}/skus").json()["skus"]
print(f"SKUs: {len(skus)}")

ORD_3M_MIN      = int(rules["a0_orders_3m_min"])
ORD_30D_MIN     = int(rules["a0_orders_30d_min"])
ORD_10D_MIN     = int(rules.get("a0_orders_10d_min", 3))
ORD_5D_MIN      = int(rules.get("a0_orders_5d_min",  1))
DEDUCT_3M       = int(rules["a0_deduct_3m"])
DEDUCT_30D      = int(rules["a0_deduct_30d"])
DEDUCT_10D      = int(rules.get("a0_deduct_10d", 5))
DEDUCT_5D       = int(rules.get("a0_deduct_5d",  5))
DEDUCT_PER_NULL = int(rules["a0_deduct_per_null"])
OUTLIER_PCT     = float(rules.get("a0_outlier_postage_pct", 100))
FREEZE_MIN      = int(rules.get("a0_global_freeze_min", 20))
FREEZE_PCT      = float(rules.get("a0_global_freeze_pct", 0.20))
RULE_VERSION    = rules.get("rule_version", "v1.0")

NULL_FIELDS = [
    "nnr_pct_3m", "nnr_pct_30d", "nnr_pct_10d",
    "orders_3m", "orders_30d",
    "revenue_3m", "revenue_30d",
    "total_income_3m", "total_expenses_3m"
]

total_skus       = len(skus)
freeze_threshold = max(FREEZE_MIN, round(total_skus * FREEZE_PCT))
fail_count       = 0
results          = []

for sku in skus:
    sid    = sku["sku_id"]
    score  = 100
    issues = []

    order_checks = [
        ("orders_3m",  ORD_3M_MIN,  DEDUCT_3M),
        ("orders_30d", ORD_30D_MIN, DEDUCT_30D),
        ("orders_10d", ORD_10D_MIN, DEDUCT_10D),
        ("orders_5d",  ORD_5D_MIN,  DEDUCT_5D),
    ]
    min_orders_gate_3m  = True
    min_orders_gate_30d = True

    for field, min_val, deduct in order_checks:
        val = sku.get(field)
        if val is None or float(val) < min_val:
            score -= deduct
            issues.append(f"{field}<{min_val}(-{deduct})")
            if field == "orders_3m":  min_orders_gate_3m  = False
            if field == "orders_30d": min_orders_gate_30d = False

    null_field_count = sum(1 for f in NULL_FIELDS if sku.get(f) is None)
    if null_field_count > 0:
        deduct_n = null_field_count * DEDUCT_PER_NULL
        score   -= deduct_n
        issues.append(f"nulls:{null_field_count}(-{deduct_n})")

    postage_pct  = float(sku.get("postage_pct_income_3m") or 0)
    outlier_flag = postage_pct > OUTLIER_PCT
    if outlier_flag:
        score = 0
        issues.append(f"postage_outlier:{postage_pct:.1f}%")

    rev3m = sku.get("revenue_3m")
    ord3m = sku.get("orders_3m")
    if (rev3m is not None and float(rev3m) == 0
            and ord3m is not None and float(ord3m) > 0):
        score = 0
        issues.append("revenue_zero_with_orders")

    score = max(0, score)

    if score >= 71:   data_sufficiency_category = "Rich"
    elif score >= 40: data_sufficiency_category = "Adequate"
    else:             data_sufficiency_category = "Thin"

    if score >= 40:
        agent0_decision   = "PASS"
        data_quality_flag = "OK"
    elif score >= 32:
        agent0_decision   = "WARN"
        data_quality_flag = "WARN"
    else:
        agent0_decision   = "FAIL"
        data_quality_flag = "FAIL"
        fail_count += 1

    results.append({
        "sku": sku,
        "output": {
            "sku_id":                    sid,
            "data_quality_flag":         data_quality_flag,
            "data_sufficiency_score":    score,
            "data_sufficiency_category": data_sufficiency_category,
            "min_orders_gate_3m":        min_orders_gate_3m,
            "min_orders_gate_30d":       min_orders_gate_30d,
            "outlier_flag":              outlier_flag,
            "null_field_count":          null_field_count,
            "systemic_issue_flag":       False,
            "agent0_decision":           agent0_decision,
            "issues_summary":            " | ".join(issues) if issues else "No issues",
            "rule_version_id":           RULE_VERSION
        }
    })

systemic_issue = fail_count >= freeze_threshold
print(f"Global Freeze: {fail_count} FAILs / threshold {freeze_threshold} → {'FROZEN' if systemic_issue else 'OK'}")

for r in results:
    out = r["output"]
    out["systemic_issue_flag"] = systemic_issue
    if systemic_issue:
        out["agent0_decision"]   = "FAIL"
        out["data_quality_flag"] = "FAIL"

    requests.post(f"{API}/agent-output", json={
        "run_id": RUN_ID, "sku_id": r["sku"]["sku_id"],
        "agent": "AGENT_0", "output_data": out
    })
    print(f"  {r['sku']['sku_id'][:35]} → {out['agent0_decision']} "
          f"(score:{out['data_sufficiency_score']}) "
          f"outlier:{out['outlier_flag']} systemic:{out['systemic_issue_flag']}")

print(f"\n✅ Agent 0 complete! FAILs:{fail_count} | Threshold:{freeze_threshold} | Systemic:{systemic_issue}")
