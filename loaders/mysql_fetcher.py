"""
MADURO — MySQL Data Fetcher
Pulls SKU economics from multiple MySQL DBs,
calculates NNR% for 3M/30D/10D/5D windows,
loads into PostgreSQL raw_input_data table.

Usage:
    python loaders/mysql_fetcher.py
"""
from datetime import datetime, timedelta, timezone
from config.mysql import mysql_query
from config.db import query
import traceback

# ─────────────────────────────────────────────
# DATE WINDOWS (rolling from today)
# ─────────────────────────────────────────────
def get_windows():
    today = datetime.now(timezone.utc).date()
    return {
        "3m":  (today - timedelta(days=90), today),
        "30d": (today - timedelta(days=30), today),
        "10d": (today - timedelta(days=10), today),
        "5d":  (today - timedelta(days=5),  today),
    }

# ─────────────────────────────────────────────
# STEP 1: Get Amazon FBM SKU list
# ─────────────────────────────────────────────
def get_sku_list():
    from datetime import date, timedelta
    from datetime import date, timedelta
    two_years_ago = date.today() - timedelta(days=730)
    sku_rows = mysql_query("order_management", """
        SELECT DISTINCT oii.oii_item_sku AS sku
        FROM order_item_info oii
        JOIN `order` o ON oii.oii_order_id = o.order_id
        WHERE o.order_market_place = '23'
          AND o.order_date >= %s
          AND o.order_status IN ('completed','refunded')
          AND oii.oii_item_sku IS NOT NULL
    """, (two_years_ago,))
    active_skus = [r["sku"] for r in sku_rows]

    # Step 2: Get product details for these SKUs
    rows = []
    for sku in active_skus:
        ep = mysql_query("listing_management", """
            SELECT sku, parent_sku, mapped_sku, item_id, fulfilment
            FROM ebay_products
            WHERE sku = %s
              AND which_channel = 'amazon'
              AND fulfilment = 'merchant'
              AND is_deleted = 0
            LIMIT 1
        """, (sku,))
        if ep:
            rows.append(ep[0])
        else:
            rows.append({"sku": sku, "parent_sku": None,
                        "mapped_sku": None, "item_id": None, "fulfilment": "merchant"})
    print(f"  Found {len(rows)} FBM SKUs with orders in last 6 months")
    return {r["sku"]: r for r in rows}

# ─────────────────────────────────────────────
# STEP 2: Fetch orders for a date window
# ─────────────────────────────────────────────
def fetch_orders(start, end):
    return mysql_query("order_management", """
        SELECT
            o.order_id,
            o.order_date,
            o.order_shipping_cost,
            o.order_discount,
            o.order_tax,
            oii.oii_item_sku         AS sku,
            oii.oii_item_asin        AS asin,
            oii.oii_item_price       AS item_price,
            oii.oii_item_quantity    AS quantity
        FROM `order` o
        JOIN order_item_info oii ON o.order_id = oii.oii_order_id
        WHERE o.order_date BETWEEN %s AND %s
          AND o.order_status IN ('completed', 'refunded')
          AND o.order_market_place = '23' 
    """, (start, end))

# ─────────────────────────────────────────────
# STEP 3: Fetch Amazon fees
# ─────────────────────────────────────────────
def fetch_amz_fees(start, end):
    return mysql_query("accounts_management", """
        SELECT
            order_id,
            SUM(amz_fee)  AS amz_fee,
            SUM(other)    AS labman_purchase,
            0             AS labman_return,
            0             AS labman_chargeback
        FROM amz_transactions
        WHERE date BETWEEN %s AND %s
          AND market_place = 23
        GROUP BY order_id
    """, (start, end))

# ─────────────────────────────────────────────
# STEP 4: Fetch PPC spend
# ─────────────────────────────────────────────
def fetch_ppc(start, end):
    return mysql_query("ppc", """
        SELECT
            p.amzSKU      AS sku,
            SUM(pd.spend) AS ppc_spend
        FROM performance_data pd
        JOIN ads a     ON pd.adId = a.adId
        JOIN products p ON a.productId = p.productId
        WHERE pd.date BETWEEN %s AND %s
          AND p.amzSKU IS NOT NULL
          AND a.storeMarketPlaceId IN (
              SELECT smp.storeMarketPlaceId 
              FROM store_market_places_dev smp
              JOIN seller_stores ss ON smp.sellerStoreId = ss.sellerStoreId
              WHERE ss.regionId = 2
          )
        GROUP BY p.amzSKU
    """, (start, end))

# ─────────────────────────────────────────────
# STEP 5: Fetch refunds
# ─────────────────────────────────────────────
def fetch_refunds(start, end):
    return mysql_query("message_app", """
        SELECT
            sku,
            SUM(refunded_amount) AS refund_amount
        FROM amazon_returns
        WHERE request_date BETWEEN %s AND %s
          AND fulfilment = 'merchant'
        GROUP BY sku
    """, (start, end))

# ─────────────────────────────────────────────
# STEP 6: Fetch replacements
# ─────────────────────────────────────────────
def fetch_replacements(start, end):
    return mysql_query("order_management", """
        SELECT
            o.order_id,
            oii.oii_item_sku        AS sku,
            oii.oii_item_quantity   AS quantity,
            '5.0'                   AS carrier_charge
        FROM `order` o
        JOIN order_item_info oii ON o.order_id = oii.oii_order_id
        WHERE o.order_sub_source = 8
          AND o.order_date BETWEEN %s AND %s
    """, (start, end))

# ─────────────────────────────────────────────
# STEP 7: Fetch postage (carrier rates)
# ─────────────────────────────────────────────
def fetch_postage(start, end):
    return mysql_query("order_management", """
        SELECT
            s.shipment_order_id  AS order_id,
            COALESCE(cs.cs_charge, 0) AS postage_cost
        FROM shipment s
        JOIN `order` o ON s.shipment_order_id = o.order_id
        LEFT JOIN carrier_service cs ON s.shipment_carrier = cs.carrier_service
        WHERE o.order_date BETWEEN %s AND %s
          AND o.order_market_place = '23' 
    """, (start, end))

# ─────────────────────────────────────────────
# CALCULATOR: Build per-SKU economics for a window
# ─────────────────────────────────────────────
def calc_window(orders, fees_map, ppc_map, refund_map, replacement_map, postage_map, sessions_map={}):
    sku_data = {}

    # Build order-level totals for weighted allocation
    order_totals = {}
    for row in orders:
        oid = row["order_id"]
        val = float(row["item_price"] or 0) * int(row["quantity"] or 0)
        order_totals[oid] = order_totals.get(oid, 0) + val

    for row in orders:
        sku   = row["sku"]
        if not sku:
            continue
        oid   = row["order_id"]
        qty   = int(row["quantity"] or 0)
        price = float(row["item_price"] or 0)
        ship  = float(row["order_shipping_cost"] or 0)
        tax   = float(row["order_tax"] or 0)
        disc  = float(row["order_discount"] or 0)
        asin  = row.get("asin")

        # Weight for multi-SKU order allocation
        sku_val    = price * qty
        order_tot  = order_totals.get(oid, sku_val) or sku_val
        weight     = sku_val / order_tot if order_tot > 0 else 1.0

        # Customer Paid (weighted)
        customer_paid = sku_val + (ship * weight) + (tax * weight) - (disc * weight)

        # Listing price (with VAT)
        listing_price = price * qty

        if sku not in sku_data:
            sess = sessions_map.get(sku, {})
            sku_data[sku] = {
                "sku": sku, "asin": asin,
                "customer_paid": 0, "listing_price": 0,
                "orders": set(), "quantity": 0,
                "amz_fee": 0, "amz_other": 0,
                "postage": 0, "ppc": 0,
                "refund": 0, "replacement": 0,
                "sessions": float(sess.get("sessions") or 0),
                "cvr_pct": float(sess.get("cvr_pct") or 0) * 100,
            }

        sku_data[sku]["customer_paid"]  += customer_paid
        sku_data[sku]["listing_price"]  += listing_price
        sku_data[sku]["orders"].add(oid)
        sku_data[sku]["quantity"]       += qty

        # Postage allocation
        postage = postage_map.get(oid, 0)
        fees    = fees_map.get(oid, {})
        # Skip postage if LabmanLabelPurchase_fee exists
        if not fees.get("labman_purchase"):
            sku_data[sku]["postage"] += postage * weight

        # Amazon fees (weighted)
        sku_data[sku]["amz_fee"]   += float(fees.get("amz_fee") or 0) * weight
        sku_data[sku]["amz_other"] += (
            float(fees.get("labman_purchase") or 0) +
            float(fees.get("labman_return") or 0) +
            float(fees.get("labman_chargeback") or 0)
        ) * weight

    # Merge PPC, refunds, replacements
    for sku, d in sku_data.items():
        d["ppc"]         = float(ppc_map.get(sku, {}).get("ppc_spend") or 0)
        d["refund"]      = float(refund_map.get(sku, {}).get("refund_amount") or 0)
        d["replacement"] = calc_replacement(sku, replacement_map)
        d["orders"]      = len(d["orders"])

        # Derived fields
        cp               = d["customer_paid"]
        lp               = d["listing_price"]
        product_cost     = lp * 0.20
        vat              = cp * 0.20

        d["product_cost"]   = product_cost
        d["vat"]            = vat
        d["total_income"]   = cp
        d["total_expenses"] = (
            d["amz_fee"] + d["amz_other"] + d["postage"] +
            d["replacement"] + d["refund"] + product_cost + vat + d["ppc"]
        )
        d["nnr"]     = d["total_income"] - d["total_expenses"]
        d["nnr_pct"] = (d["nnr"] / cp * 100) if cp > 0 else None
        d["margin_pct"] = d["nnr_pct"]

    return sku_data

def calc_replacement(sku, replacement_map):
    rows = replacement_map.get(sku, [])
    total = 0
    for r in rows:
        qty     = int(r.get("quantity") or 0)
        carrier = float(r.get("carrier_charge") or 5.0)  # default carrier charge
        if "marked part" in str(sku).lower():
            total += (0.5 * qty) + carrier
        else:
            total += (1.0 * qty) + carrier
    return total

# ─────────────────────────────────────────────
# MAIN FETCHER
# ─────────────────────────────────────────────
def fetch_sessions(start, end):
    return mysql_query("ppc", """
        SELECT
            ep.sku,
            SUM(cp.clickCount)      AS sessions,
            AVG(cp.conversionRate)  AS cvr_pct
        FROM amz_catalog_performance_data cp
        JOIN listing_management.ebay_products ep
            ON cp.asin = ep.item_id
        WHERE cp.startDate BETWEEN %s AND %s
          AND cp.market_place_id = 23
          AND ep.which_channel = 'amazon'
          AND ep.fulfilment = 'merchant'
          AND ep.sku IS NOT NULL
        GROUP BY ep.sku
    """, (start, end))


def fetch_ph_mapping():
    return mysql_query("order_management", """
        SELECT
            ep.sku,
            ep.item_id AS asin,
            CONCAT(u.user_firstname, ' ', u.user_lastname) AS ph_holder,
            cat.category_name
        FROM listing_management.ebay_products ep
        JOIN ph_cate_products pc ON ep.item_id = pc.ref_id
        JOIN ph_categories cat ON pc.ass_cate_id = cat.id
        JOIN user u ON cat.user_id = u.user
        WHERE ep.which_channel = 'amazon'
          AND ep.fulfilment = 'merchant'
          AND pc.which_channel = 1
          AND ep.sku IS NOT NULL
        GROUP BY ep.sku
    """)

def fetch_and_load(run_id):
    print("\n🔄 Starting MySQL data fetch...")
    windows  = get_windows()
    sku_list = get_sku_list()
    print("  Fetching PH mapping...")
    ph_rows = fetch_ph_mapping()
    ph_map = {r["sku"]: r["ph_holder"] for r in ph_rows}
    print(f"  PH mapping: {len(ph_map)} SKUs mapped")

    # Fetch all windows
    results = {}
    for window, (start, end) in windows.items():
        print(f"  📅 Fetching window: {window} ({start} → {end})")

        orders       = fetch_orders(start, end)
        fees_raw     = fetch_amz_fees(start, end)
        ppc_raw      = fetch_ppc(start, end)
        refund_raw   = fetch_refunds(start, end)
        replace_raw  = fetch_replacements(start, end)
        postage_raw  = fetch_postage(start, end)
        sessions_raw = fetch_sessions(start, end)

        # Build lookup maps
        fees_map     = {r["order_id"]: r for r in fees_raw}
        ppc_map      = {r["sku"]: r for r in ppc_raw}
        refund_map   = {r["sku"]: r for r in refund_raw}
        postage_map  = {r["order_id"]: float(r.get("postage_cost") or 0) for r in postage_raw}
        sessions_map = {r["sku"]: r for r in sessions_raw}

        # Group replacements by sku
        replacement_map = {}
        for r in replace_raw:
            s = r["sku"]
            replacement_map.setdefault(s, []).append(r)

        results[window] = calc_window(
            orders, fees_map, ppc_map,
            refund_map, replacement_map, postage_map, sessions_map
        )
        print(f"     → {len(results[window])} SKUs calculated")

    # ─────────────────────────────────────────
    # Merge all windows → one row per SKU
    # ─────────────────────────────────────────
    all_skus = set(sku_list.keys())
    for w in results.values():
        all_skus.update(w.keys())

    print(f"\n📦 Loading {len(all_skus)} SKUs into PostgreSQL...")

    loaded = 0
    for sku in all_skus:
        d3m  = results["3m"].get(sku, {})
        d30d = results["30d"].get(sku, {})
        d10d = results["10d"].get(sku, {})
        d5d  = results["5d"].get(sku, {})

        ep   = sku_list.get(sku, {})
        asin = d30d.get("asin") or d3m.get("asin") or ep.get("item_id")

        try:
            query("""
                INSERT INTO raw_input_data (
                    run_id, sku_id, sku_name, asin, ph_holder, account,
                    nnr_pct_3m, nnr_pct_30d, nnr_pct_10d, nnr_pct_5d,
                    orders_3m, orders_30d, orders_10d, orders_5d,
                    revenue_3m, revenue_30d, revenue_10d, revenue_5d,
                    nnr_gbp_3m, nnr_gbp_30d,
                    total_income_3m, total_expenses_3m, margin_pct_3m,
                    postage_pct_income_3m, postage_pct_income,
                sessions_3m, sessions_30d, cvr_pct_3m, cvr_pct_30d
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,
                    %s,%s,%s,
                    %s,%s,
                    %s,%s,%s,%s
                )
                ON CONFLICT (run_id, sku_id) DO UPDATE SET
                    nnr_pct_30d = EXCLUDED.nnr_pct_30d,
                    nnr_pct_3m  = EXCLUDED.nnr_pct_3m
            """, (
                run_id, sku, sku, asin, ph_map.get(sku, "Unassigned"), "Amazon-UK-FBM",
                d3m.get("nnr_pct") if d3m else None,
                d30d.get("nnr_pct") if d30d else None,
                d10d.get("nnr_pct") if d10d else None,
                d5d.get("nnr_pct") if d5d else None,
                d3m.get("orders") if d3m else None,
                d30d.get("orders") if d30d else None,
                d10d.get("orders") if d10d else None,
                d5d.get("orders") if d5d else None,
                d3m.get("customer_paid") if d3m else None,
                d30d.get("customer_paid") if d30d else None,
                d10d.get("customer_paid") if d10d else None,
                d5d.get("customer_paid") if d5d else None,
                d3m.get("nnr") if d3m else None,
                d30d.get("nnr") if d30d else None,
                d3m.get("total_income") if d3m else None,
                d3m.get("total_expenses") if d3m else None,
                d3m.get("margin_pct") if d3m else None,
                (d3m.get("postage", 0) / d3m.get("customer_paid", 1) * 100) if d3m and d3m.get("customer_paid") else None,
                (d3m.get("postage", 0) / d3m.get("customer_paid", 1) * 100) if d3m and d3m.get("customer_paid") else None,
                d3m.get("sessions") if d3m else None,
                d30d.get("sessions") if d30d else None,
                d3m.get("cvr_pct") if d3m else None,
                d30d.get("cvr_pct") if d30d else None,
            ), fetch=False)
            loaded += 1
        except Exception as e:
            print(f"  ⚠️  SKU {sku} failed: {e}")

    # Update run
    query(
        "UPDATE pipeline_runs SET status='READY', total_skus_processed=%s WHERE run_id=%s",
        (loaded, run_id), fetch=False
    )

    print(f"\n✅ Done! {loaded} SKUs loaded into run {run_id}")
    return run_id


if __name__ == "__main__":
    from config.db import query as pg_query
    from datetime import datetime, timezone

    # Generate run ID
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows  = pg_query(
        "SELECT run_id FROM pipeline_runs WHERE run_id LIKE %s ORDER BY run_id DESC LIMIT 1",
        (f"RUN-{today}-%",)
    )
    seq    = str(int(rows[0]["run_id"][-3:]) + 1).zfill(3) if rows else "001"
    run_id = f"RUN-{today}-{seq}"

    pg_query(
        "INSERT INTO pipeline_runs (run_id, rule_version_id, status) VALUES (%s, 'v1.0', 'LOADING')",
        (run_id,), fetch=False
    )

    fetch_and_load(run_id)

def fetch_catalog_performance(start, end):
    return mysql_query("ppc", """
        SELECT
            asin,
            SUM(clickCount)     AS sessions,
            SUM(purchaseCount)  AS orders,
            AVG(conversionRate) AS cvr_pct
        FROM amz_catalog_performance_data
        WHERE startDate BETWEEN %s AND %s
          AND market_place_id = 23
          AND asin IS NOT NULL
        GROUP BY asin
    """, (start, end))


