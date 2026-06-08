import requests, json, os
from datetime import datetime, timezone
API = "http://127.0.0.1:8088"
# Try multiple paths for openclaw.json
import os
_cfg_paths = [
    "/home/led284/.openclaw/openclaw.json",
    "/home/led284/.openclaw-dev/openclaw.json",
    "/root/.openclaw/openclaw.json"
]
cfg = None
for _p in _cfg_paths:
    if os.path.exists(_p):
        cfg = json.loads(open(_p).read())
        break
if cfg is None:
    print("ERROR: openclaw.json not found — Slack notify skipped")
    exit(0)
TOKEN = cfg["channels"]["slack"]["botToken"]
CHANNEL = "C0B0PHATYNR"
def send_slack(blocks):
    r = requests.post("https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"channel": CHANNEL, "blocks": blocks})
    print(r.json().get("ok"), r.json().get("error",""))
def notify():
    run = requests.get(f"{API}/runs/latest").json()
    RID = run["run_id"]
    missions = requests.get(f"{API}/missions/{RID}").json()["missions"]
    # Also get approved from all runs
    all_approved = requests.get(f"{API}/missions?status=APPROVE").json()["missions"]
    # Also get approved from all runs
    all_approved = requests.get(f"{API}/missions?status=APPROVE").json()["missions"]
    skus = requests.get(f"{API}/runs/{RID}/skus").json()["skus"]
    holds = [m for m in missions if m["status"]=="HOLD"]
    reds = [m for m in missions if m["current_state"]=="Red"]
    ambers = [m for m in missions if m["current_state"]=="Amber"]
    seen_ap = set()
    approved = []
    for m in all_approved:
        if m["sku_id"] not in seen_ap:
            seen_ap.add(m["sku_id"])
            approved.append(m)
    analysis = ""
    if os.path.exists("/tmp/maduro_analysis.txt"):
        analysis = open("/tmp/maduro_analysis.txt").read().strip()
        os.remove("/tmp/maduro_analysis.txt")
    blocks = [
        {"type":"header","text":{"type":"plain_text","text":f"MADURO Daily Report - {RID}"}},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*SKUs:* {len(skus)}"},
            {"type":"mrkdwn","text":f"*Approved:* {len(approved)}"},
            {"type":"mrkdwn","text":f"*Hold:* {len(holds)}"},
            {"type":"mrkdwn","text":f"*Red:* {len(reds)}"},
            {"type":"mrkdwn","text":f"*Amber:* {len(ambers)}"},
            {"type":"mrkdwn","text":f"*Time:* {datetime.now(timezone.utc).strftime('%H:%M UTC')}"},
        ]},
        {"type":"divider"}
    ]
    if analysis:
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":f"*AI Analysis:*\n{analysis}"}})
        blocks.append({"type":"divider"})
    if approved:
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":f"*APPROVED MISSIONS ({len(approved)})*"}})
        for m in approved:
            blocks.append({"type":"section","text":{"type":"mrkdwn","text":
                f"*{m['mission_type']}* `{m['sku_id']}` | {m['current_state']} | Driver: {m.get('primary_driver','--')} | PH: {m['ph_holder']}"}})
    if holds:
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":f"*ON HOLD ({len(holds)})*"}})
        for m in holds[:5]:
            blocks.append({"type":"section","text":{"type":"mrkdwn","text":
                f"`{m['sku_id']}` {m['current_state']} | Blocked: {m.get('block_reason','--')}"}})
    blocks.append({"type":"section","text":{"type":"mrkdwn","text":"Dashboard: http://192.168.1.7:8088/ui"}})
    send_slack(blocks)
    print(f"Slack sent! Approved:{len(approved)} Hold:{len(holds)}")
notify()
