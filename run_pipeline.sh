#!/bin/bash
export PYTHONPATH=/home/led284/Downloads/maduro
cd /home/led284/Downloads/maduro

echo "--- MySQL Fetcher ---"
python3 /home/led284/Downloads/maduro/run_fetcher.py 2>&1 | grep -v "Refunds skipped"

# Get current run_id
RUN_ID=$(sudo -u postgres psql -d maduro -t -c "SELECT run_id FROM pipeline_runs WHERE status='READY' ORDER BY run_timestamp DESC LIMIT 1;" | tr -d ' ')
echo "=== MADURO Pipeline Start $(date) — Run: $RUN_ID ==="
echo "--- Fill missing NNR from previous run ---"
PREV_RUN=$(sudo -u postgres psql -d maduro -t -c "SELECT run_id FROM pipeline_runs WHERE status='READY' AND run_id != '$RUN_ID' ORDER BY run_timestamp DESC LIMIT 1;" | tr -d ' ')
sudo -u postgres psql -d maduro -c "UPDATE raw_input_data r SET nnr_pct_30d=prev.nnr_pct_30d, nnr_pct_10d=prev.nnr_pct_10d, nnr_pct_3m=prev.nnr_pct_3m, nnr_pct_5d=prev.nnr_pct_5d FROM raw_input_data prev WHERE r.run_id='$RUN_ID' AND r.nnr_pct_30d IS NULL AND r.nnr_pct_3m IS NULL AND prev.run_id='$PREV_RUN' AND prev.sku_id=r.sku_id AND prev.nnr_pct_30d IS NOT NULL;"
echo "--- NNR fill complete ---"

echo "--- Agent 0 ---"
python3 agents/run_agent0.py

echo "--- Agent 1 ---"
bash agents/run_agent1.sh

echo "--- Agent 2 ---"
python3 agents/run_agent2.py

echo "--- Agent 3 ---"
python3 agents/run_agent3.py

echo "--- Agent 4 ---"
python3 agents/run_agent4.py

echo "--- Agent 5 ---"
python3 agents/run_agent5.py

echo "=== MADURO Pipeline Complete $(date) ==="

echo "--- Clean duplicate agent outputs ---"
sudo -u postgres psql -d maduro -c "DELETE FROM agent_outputs WHERE run_id='$RUN_ID' AND id NOT IN (SELECT MAX(id) FROM agent_outputs WHERE run_id='$RUN_ID' GROUP BY sku_id, agent);"

echo "--- Clean duplicate missions ---"
sudo -u postgres psql -d maduro -c "DELETE FROM missions WHERE run_id='$RUN_ID' AND mission_id NOT IN (SELECT DISTINCT ON (sku_id) mission_id FROM missions WHERE run_id='$RUN_ID' ORDER BY sku_id, created_at DESC);"

echo "--- Fix missing deadlines ---"
sudo -u postgres psql -d maduro -c "UPDATE missions SET deadline = CASE WHEN mission_type='RED_STRIKE' THEN created_at::date + 1 WHEN mission_type='AMBER_FIX' THEN created_at::date + 3 WHEN mission_type='AMBER_WATCH' THEN created_at::date + 7 ELSE created_at::date + 3 END WHERE deadline IS NULL;"
sudo -u postgres psql -d maduro -c "UPDATE missions SET next_review_date = CASE WHEN mission_type='RED_STRIKE' THEN created_at::date + 7 WHEN mission_type='AMBER_FIX' THEN created_at::date + 14 ELSE created_at::date + 14 END WHERE next_review_date IS NULL;"

echo "--- OpenClaw Analysis ---"
PYTHONPATH=/home/led284/Downloads/maduro python3 agents/openclaw_analyze.py

echo "--- Slack Notify ---"
PYTHONPATH=/home/led284/Downloads/maduro python3 agents/slack_notify.py

echo "=== All Done $(date) ==="
