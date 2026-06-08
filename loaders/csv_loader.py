"""
MADURO — CSV Loader
Usage: python loaders/csv_loader.py --file your_data.csv --run_id RUN-2026-04-24-001
"""
import pandas as pd
import argparse
from datetime import datetime, timezone
from config.db import query

COLUMN_MAP = {
    "SKU_ID": "sku_id", "SKU_Name": "sku_name", "ASIN": "asin",
    "PH_Holder": "ph_holder", "Account": "account",
    "NNR%_3M": "nnr_pct_3m", "NNR%_30D": "nnr_pct_30d",
    "NNR%_10D": "nnr_pct_10d", "NNR%_5D": "nnr_pct_5d",
    "Orders_3M": "orders_3m", "Orders_30D": "orders_30d",
    "Orders_10D": "orders_10d", "Orders_5D": "orders_5d",
    "Revenue_3M": "revenue_3m", "Revenue_30D": "revenue_30d",
    "Revenue_10D": "revenue_10d", "Revenue_5D": "revenue_5d",
    "NNR_£_3M": "nnr_gbp_3m", "NNR_£_30D": "nnr_gbp_30d",
    "Sessions_3M": "sessions_3m", "Sessions_30D": "sessions_30d",
    "CVR%_30D": "cvr_pct_30d", "PPC_Spend_30D": "ppc_spend_30d",
    "PPC_Sales_30D": "ppc_sales_30d", "ACoS%_30D": "acos_pct_30d",
    "Return%_30D": "return_pct_30d",
    "Postage%_Income_3M": "postage_pct_income_3m",
    "BuyBox%_30D": "buybox_pct_30d",
    "TotalIncome_3M": "total_income_3m",
    "TotalExpenses_3M": "total_expenses_3m",
    "Margin%_3M": "margin_pct_3m",
    "Stock_DaysOfCover": "stock_days_cover",
    "CVR%_3M": "cvr_pct_3m", "ACoS%_3M": "acos_pct_3m",
    "Return%_3M": "return_pct_3m", "BuyBox%_3M": "buybox_pct_3m",
    "Postage%_Income": "postage_pct_income",
}

def generate_run_id():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = query(
        "SELECT run_id FROM pipeline_runs WHERE run_id LIKE %s ORDER BY run_id DESC LIMIT 1",
        (f"RUN-{today}-%",)
    )
    seq = str(int(rows[0]["run_id"][-3:]) + 1).zfill(3) if rows else "001"
    return f"RUN-{today}-{seq}"

def load_csv(filepath, run_id=None):
    df = pd.read_csv(filepath)
    df.rename(columns=COLUMN_MAP, inplace=True)

    run_id = run_id or generate_run_id()

    # Create pipeline run
    query(
        "INSERT INTO pipeline_runs (run_id, rule_version_id, status) VALUES (%s, 'v1.0', 'LOADING')",
        (run_id,), fetch=False
    )

    # Insert each SKU row
    inserted = 0
    for _, row in df.iterrows():
        cols = ["run_id"] + [c for c in COLUMN_MAP.values() if c in df.columns]
        vals = [run_id] + [row.get(c) if pd.notna(row.get(c, None)) else None for c in cols[1:]]
        placeholders = ",".join(["%s"] * len(cols))
        col_names = ",".join(cols)
        query(
            f"INSERT INTO raw_input_data ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
            vals, fetch=False
        )
        inserted += 1

    # Update run status
    query(
        "UPDATE pipeline_runs SET status='READY', total_skus_processed=%s WHERE run_id=%s",
        (inserted, run_id), fetch=False
    )

    print(f"✅ Loaded {inserted} SKUs into run {run_id}")
    return run_id

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to CSV file")
    parser.add_argument("--run_id", help="Optional run ID (auto-generated if not provided)")
    args = parser.parse_args()
    load_csv(args.file, args.run_id)
