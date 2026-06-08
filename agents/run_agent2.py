import requests

API = "http://127.0.0.1:8088"

run    = requests.get(f"{API}/runs/latest").json()
RUN_ID = run["run_id"]
print(f"Run: {RUN_ID}")

rules = requests.get(f"{API}/rules").json()
skus  = requests.get(f"{API}/runs/{RUN_ID}/skus").json()["skus"]
a1    = {r["sku_id"]: r["output_data"]
         for r in requests.get(f"{API}/agent-output/{RUN_ID}/AGENT_1").json()["results"]}
print(f"SKUs: {len(skus)}")

POSTAGE_HIGH    = float(rules["a2_postage_high"])
MARGIN_LOW      = float(rules["a2_margin_low"])
ACOS_INCREASE   = float(rules["a2_acos_increase"])
RETURN_INCREASE = float(rules["a2_return_increase"])
STOCK_LOW       = float(rules["a2_stock_low_days"])
CVR_DECLINE_PCT = float(rules["a2_cvr_decline_pct"]) / 100
BUY_BOX_DROP    = float(rules.get("a2_buy_box_drop_pct", 20))
RULE_VERSION    = rules.get("rule_version", "v1.0")

TAXONOMY = {
    "unit_margin_compression" : ("MARGIN_COST",  "Structural"),
    "fulfilment_cost_increase": ("MARGIN_COST",  "Structural"),
    "ppc_cost_inflation"      : ("MARGIN_COST",  "Structural"),
    "returns_leakage"         : ("MARGIN_COST",  "Structural"),
    "cvr_decline"             : ("CONVERSION",   "Structural"),
    "suppressed_listings"     : ("CONVERSION",   "Structural"),
    "buy_box_instability"     : ("OPERATIONAL",  "Structural"),
    "stock_depth"             : ("OPERATIONAL",  "Temporary"),
    "traffic_drop"            : ("DEMAND",        "Structural"),
}

ELIGIBLE_STATES = {"Amber", "Red"}

for sku in skus:
    sid   = sku["sku_id"]
    state = a1.get(sid, {}).get("current_state", "Light_Green")
    if state not in ELIGIBLE_STATES:
        continue

    postage  = float(sku.get("postage_pct_income_3m")  or 0)
    margin   = float(sku.get("margin_pct_3m")          or 0)
    acos30   = float(sku.get("acos_pct_30d")           or 0)
    acos3m   = float(sku.get("acos_pct_3m")            or 0)
    ret30    = float(sku.get("return_pct_30d")          or 0)
    ret3m    = float(sku.get("return_pct_3m")           or 0)
    stock    = float(sku.get("stock_days_cover")        or 999)
    cvr30    = float(sku.get("cvr_pct_30d")             or 0)
    cvr3m    = float(sku.get("cvr_pct_3m")              or 0)
    s30      = float(sku.get("sessions_30d")             or 0)
    s3m      = float(sku.get("sessions_3m")              or 0)
    bb_pct30 = float(sku.get("buy_box_pct_30d")         or 100)
    bb_pct3m = float(sku.get("buy_box_pct_3m")          or 100)

    drivers = []

    if postage > POSTAGE_HIGH:
        drivers.append(("fulfilment_cost_increase", 85))
    if margin < MARGIN_LOW and margin != 0:
        drivers.append(("unit_margin_compression", 85))
    if acos30 > 0 and acos3m > 0 and (acos30 - acos3m) >= ACOS_INCREASE:
        drivers.append(("ppc_cost_inflation", 75))
    if ret30 > 0 and ret3m > 0 and (ret30 - ret3m) >= RETURN_INCREASE:
        drivers.append(("returns_leakage", 75))
    if stock < STOCK_LOW:
        drivers.append(("stock_depth", 70))
    if bb_pct3m > 0 and bb_pct30 < bb_pct3m - BUY_BOX_DROP:
        drivers.append(("buy_box_instability", 75))
    if s30 > 10 and s3m > 0 and cvr3m > 0:
        if cvr30 < cvr3m * (1 - CVR_DECLINE_PCT):
            drivers.append(("cvr_decline", 70))
    if s3m > 10 and s30 == 0:
        drivers.append(("suppressed_listings", 80))
    elif s3m > 10 and s30 < s3m * 0.15:
        drivers.append(("suppressed_listings", 70))
    if s3m > 10 and s30 > 0 and s30 < s3m * 0.3 * (30 / 90):
        drivers.append(("traffic_drop", 70))

    def sort_key(d):
        code, conf = d
        is_temp = 1 if TAXONOMY.get(code, ("", "Structural"))[1] == "Temporary" else 0
        return (is_temp, -conf)

    drivers.sort(key=sort_key)

    if not drivers:
        primary_driver        = "unidentified"
        driver_category       = "UNKNOWN"
        driver_classification = "Mixed"
        driver_conf           = 60
        secondary_drivers     = None
    else:
        p_code, p_conf        = drivers[0]
        primary_driver        = p_code
        driver_category, driver_classification = TAXONOMY.get(p_code, ("UNKNOWN", "Mixed"))
        driver_conf           = min(p_conf + (10 if len(drivers) >= 2 else 0), 85)
        secondary_drivers     = ",".join(d[0] for d in drivers[1:]) or None

    output = {
        "sku_id":                  sid,
        "primary_driver":          primary_driver,
        "driver_category":         driver_category,
        "driver_classification":   driver_classification,
        "driver_confidence_score": driver_conf,
        "secondary_drivers":       secondary_drivers,
        "driver_notes":            f"{len(drivers)} driver(s) found",
        "rule_version_id":         RULE_VERSION
    }

    requests.post(f"{API}/agent-output", json={
        "run_id": RUN_ID, "sku_id": sid,
        "agent": "AGENT_2", "output_data": output
    })
    print(f"  {sid[:35]} → {primary_driver} ({driver_classification}) cat:{driver_category} conf:{driver_conf}")

print("\n✅ Agent 2 complete!")
