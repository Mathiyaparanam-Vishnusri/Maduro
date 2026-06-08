import psycopg2, datetime, sys
sys.path.insert(0, '/home/led284/Downloads/maduro')
from loaders.mysql_fetcher_v2 import fetch_and_load

conn = psycopg2.connect(host='localhost', dbname='maduro', user='maduro_user', password='changeme')
cur = conn.cursor()
today = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')
cur.execute("SELECT run_id FROM pipeline_runs WHERE run_id LIKE %s ORDER BY run_id DESC LIMIT 1", ('RUN-' + today + '-%',))
row = cur.fetchone()
seq = str(int(row[0][-3:])+1).zfill(3) if row else '001'
run_id = 'RUN-' + today + '-' + seq
cur.execute("INSERT INTO pipeline_runs (run_id, rule_version_id, status) VALUES (%s, 'v1.0', 'LOADING')", (run_id,))
conn.commit()
conn.close()
print(f'New run: {run_id}')

# Try fetching from MySQL
try:
    fetch_and_load(run_id)
except Exception as e:
    print(f'Fetcher error: {e} — will use existing data')

# Check if SKUs were loaded
conn2 = psycopg2.connect(host='localhost', dbname='maduro', user='maduro_user', password='changeme')
cur2 = conn2.cursor()
cur2.execute("SELECT COUNT(*) FROM raw_input_data WHERE run_id=%s", (run_id,))
sku_count = cur2.fetchone()[0]

if sku_count == 0:
    # Auto-copy from latest READY run with data — base columns only
    print(f'No SKUs loaded — copying from previous run...')
    cur2.execute("""
        INSERT INTO raw_input_data (
            run_id, sku_id, sku_name, asin, ph_holder, account,
            nnr_pct_3m, nnr_pct_30d, nnr_pct_10d, nnr_pct_5d,
            orders_3m, orders_30d, orders_10d, orders_5d,
            revenue_3m, revenue_30d, revenue_10d, revenue_5d,
            nnr_gbp_3m, nnr_gbp_30d, total_income_3m, total_expenses_3m,
            margin_pct_3m, postage_pct_income_3m, postage_pct_income,
            sessions_3m, sessions_30d, cvr_pct_3m, cvr_pct_30d
        )
        SELECT
            %s, sku_id, sku_name, asin, ph_holder, account,
            nnr_pct_3m, nnr_pct_30d, nnr_pct_10d, nnr_pct_5d,
            orders_3m, orders_30d, orders_10d, orders_5d,
            revenue_3m, revenue_30d, revenue_10d, revenue_5d,
            nnr_gbp_3m, nnr_gbp_30d, total_income_3m, total_expenses_3m,
            margin_pct_3m, postage_pct_income_3m, postage_pct_income,
            sessions_3m, sessions_30d, cvr_pct_3m, cvr_pct_30d
        FROM raw_input_data
        WHERE run_id = (
            SELECT run_id FROM pipeline_runs
            WHERE status='READY' AND total_skus_processed > 0
            ORDER BY run_timestamp DESC LIMIT 1
        )
        ON CONFLICT DO NOTHING
    """, (run_id,))
    conn2.commit()
    cur2.execute("SELECT COUNT(*) FROM raw_input_data WHERE run_id=%s", (run_id,))
    sku_count = cur2.fetchone()[0]
    print(f'Copied {sku_count} SKUs from previous run')

cur2.execute("UPDATE pipeline_runs SET status='READY', total_skus_processed=%s WHERE run_id=%s", (sku_count, run_id))
conn2.commit()
conn2.close()
print(f'Run {run_id} marked READY with {sku_count} SKUs')
