import requests
API = "http://127.0.0.1:8088"
run = requests.get(f"{API}/runs/latest").json()
RID = run["run_id"]
missions = requests.get(f"{API}/missions/{RID}").json()["missions"]
skus = requests.get(f"{API}/runs/{RID}/skus").json()["skus"]
a1 = requests.get(f"{API}/agent-output/{RID}/AGENT_1").json()["results"]
a1_map = {r["sku_id"]: r["output_data"] for r in a1}
seen = set()
unique_missions = []
for m in missions:
    if m["sku_id"] not in seen:
        seen.add(m["sku_id"])
        unique_missions.append(m)
holds = [m for m in unique_missions if m["status"]=="HOLD"]
approved = [m for m in unique_missions if m["status"]=="APPROVE"]
ambers = [s for s,d in a1_map.items() if d.get("current_state")=="Amber"]
reds = [s for s,d in a1_map.items() if d.get("current_state")=="Red"]
healthy = sum(1 for d in a1_map.values() if d.get("current_state")=="Dark_Green")
purple  = sum(1 for d in a1_map.values() if d.get("current_state")=="Purple")
runs = requests.get(f"{API}/runs").json()
a5 = []
for r in runs[:5]:
    res = requests.get(f"{API}/agent-output/{r['run_id']}/AGENT_5").json().get("results",[])
    real = [x for x in res if x["output_data"].get("outcome") != "UNKNOWN"]
    if real:
        a5 = real
        break
seen_f = set()
fails = []
for r in a5:
    if r["output_data"].get("outcome")=="FAIL" and r["sku_id"] not in seen_f:
        seen_f.add(r["sku_id"])
        fails.append(r)
lines = []
if reds: lines.append(f"CRITICAL: {len(reds)} Red SKUs need immediate action")
if ambers: lines.append(f"WARNING: {len(ambers)} Amber - {','.join(ambers[:2])}")
if holds: lines.append(f"ON HOLD: {len(holds)} missions awaiting confirmation run")
if approved: lines.append(f"ACTION NEEDED: {len(approved)} AMBER_FIX missions approved for PHs")
if fails: lines.append(f"ESCALATE: {len(fails)} mission(s) showing no improvement - {','.join([r['sku_id'] for r in fails[:2]])}")
lines.append(f"HEALTHY: {healthy} Dark Green | {len(ambers)} Amber | {len(reds)} Red | {purple} Purple (new listings)")
lines.append("Dashboard: http://192.168.1.7:8088/ui")
open("/tmp/maduro_analysis.txt","w").write("\n".join(lines))
print("\n".join(lines))
