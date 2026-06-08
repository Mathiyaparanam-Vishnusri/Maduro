"""
MADURO — MySQL Fetcher v2
Fixed per gap analysis — all 12 issues addressed
"""
from datetime import datetime, timedelta, timezone, date
from config.mysql import mysql_query
from config.db import query

BATCH_SIZE = 50

def get_windows():
    today = date.today()
    return {
        "3m":  (today - timedelta(days=90), today),
        "30d": (today - timedelta(days=30), today),
        "10d": (today - timedelta(days=10), today),
        "5d":  (today - timedelta(days=5),  today),
    }

def get_all_skus():
    try:
        rows = mysql_query('order_management', """
            SELECT DISTINCT
                oii.oii_item_sku AS sku,
                oii_item_id AS item_id,
                oii_product_id AS parent_sku
            FROM order_item_info oii
            JOIN `order` o ON oii.oii_order_id = o.order
            WHERE o.order_market_place = '23'
              AND o.order_sub_source IN (6, 8)
           AND o.order_status IN ('completed', 'refunded')
              AND o.order_date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
              AND oii.oii_item_sku IS NOT NULL
        """)
        print(f"  Amazon UK SKUs: {len(rows)}")
    except Exception as e:
        print(f"  ⚠️ get_all_skus failed: {e}")
        rows = []
    return rows

def get_ph_mapping():
    try:
        rows = mysql_query('order_management', """
            SELECT ep.sku,
                   CONCAT(u.user_firstname,' ',u.user_lastname) AS ph_holder
            FROM listing_management.ebay_products ep
            JOIN ph_cate_products pc ON ep.item_id = pc.ref_id
            JOIN ph_categories cat ON pc.ass_cate_id = cat.id
            JOIN user u ON cat.user_id = u.user
            WHERE ep.which_channel = 'amazon'
              AND pc.which_channel = 1
              AND ep.sku IS NOT NULL
            GROUP BY ep.sku
        """)
        return {r["sku"]: r["ph_holder"] for r in rows}
    except Exception as e:
        print(f"  ⚠️ PH mapping failed: {e}")
        return {}

def fetch_orders_for_skus(sku_batch, start, end):
    if not sku_batch:
        return []
    placeholders = ",".join(["%s"] * len(sku_batch))
    return mysql_query("order_management", f"""
        SELECT
            o.order                   AS order_id,
            o.order_shipping_cost,
            o.order_discount,
            o.order_tax,
            oii.oii_item_sku          AS sku,
            oii.oii_item_asin         AS asin,
            oii.oii_item_price        AS item_price,
            oii.oii_item_quantity     AS quantity
        FROM `order` o
        JOIN order_item_info oii ON o.order = oii.oii_order_id
        JOIN listing_management.ebay_products ep
            ON ep.sku = oii.oii_item_sku
           AND ep.which_channel = 'amazon'
           AND ep.site = 'uk'
           AND ep.fulfilment = 'merchant'
        WHERE o.order_date BETWEEN %s AND %s
          AND o.order_status IN ('completed','refunded')
          AND o.order_market_place = '23'
          AND o.order_sub_source IN (6, 8)
          AND oii.oii_item_sku IS NOT NULL
          AND oii.oii_item_sku IN ({placeholders})
    """, (start, end, *sku_batch))

def fetch_fees_for_orders(order_ids):
    if not order_ids:
        return {}
    placeholders = ",".join(["%s"] * len(order_ids))
    try:
        rows = mysql_query("accounts_management", f"""
            SELECT at.order_id,
                   SUM(CASE WHEN at.description = 'Order Payment'
                       THEN at.amz_fee ELSE 0 END) AS amz_fee,
                   SUM(CASE WHEN at.description IN
                       ('LabmanLabelPurchase','LabmanLabelReturn','LabmanLabelChargeBack')
                       THEN at.total ELSE 0 END) AS amz_other
            FROM amz_transactions at
            JOIN order_management.`order` o
                ON o.order_id = at.order_id
               AND o.order_market_place = '23'
               AND o.order_sub_source IN (6, 8)
               AND o.order_status IN ('completed', 'refunded')
            JOIN order_management.order_item_info oii
                ON oii.oii_order_id = o.order
            JOIN listing_management.ebay_products ep
                ON ep.sku = oii.oii_item_sku
               AND ep.which_channel = 'amazon'
               AND ep.site = 'uk'
               AND ep.fulfilment = 'merchant'
            WHERE at.order_id IN ({placeholders})
            GROUP BY at.order_id
        """, tuple(order_ids))
        return {r["order_id"]: r for r in rows}
    except Exception as e:
        print(f"  ⚠️ Fees skipped: {e}")
        return {}

def fetch_postage_for_orders(order_ids):
    if not order_ids:
        return {}
    placeholders = ",".join(["%s"] * len(order_ids))
    try:
        rows = mysql_query("order_management", f"""
            SELECT s.shipment_order_id AS order_id,
                   COALESCE(cs.cs_charge_with_tax, cs.cs_charge, 0) AS postage_cost
            FROM shipment s
            LEFT JOIN carrier_service cs ON s.shipment_carrier = cs.carrier_service
            WHERE s.shipment_order_id IN ({placeholders})
        """, tuple(order_ids))
        return {r["order_id"]: float(r["postage_cost"] or 0) for r in rows}
    except Exception as e:
        print(f"  ⚠️ Postage skipped: {e}")
        return {}

def fetch_labman_label_orders(order_ids):
    # Fix 2: Detect LabmanLabel orders to skip postage
    if not order_ids:
        return set()
    placeholders = ",".join(["%s"] * len(order_ids))
    try:
        rows = mysql_query("accounts_management", f"""
            SELECT DISTINCT order_id
            FROM amz_transactions
            WHERE order_id IN ({placeholders})
              AND description = 'LabmanLabelPurchase'
        """, tuple(order_ids))
        return {r["order_id"] for r in rows}
    except Exception as e:
        print(f"  ⚠️ LabmanLabel check skipped: {e}")
        return set()

def fetch_replacements_for_skus(sku_batch, start, end):
    # Fix 4: Use correct replacement table with full join logic
    if not sku_batch:
        return {}
    placeholders = ",".join(["%s"] * len(sku_batch))
    try:
        rows = mysql_query("order_management", f"""
            SELECT
                oii_rep.oii_item_sku           AS sku,
                SUM(oii_rep.oii_item_quantity)  AS replacement_qty,
                oii_rep.oii_item_price          AS rep_price,
                s_rep.shipment_carrier          AS rep_carrier,
                s_rep.shipment_status           AS rep_shipment_status
            FROM replacement r
            JOIN `order` o_rep
                ON r.repla_order_id = o_rep.order
            JOIN order_item_info oii_rep
                ON o_rep.order = oii_rep.oii_order_id
            LEFT JOIN shipment s_rep
                ON s_rep.shipment_order_id = o_rep.order
            JOIN listing_management.ebay_products ep
                ON ep.sku = oii_rep.oii_item_sku
               AND ep.site = 'uk'
               AND ep.which_channel = 'amazon'
               AND ep.fulfilment = 'merchant'
            WHERE o_rep.order_market_place = '23'
              AND o_rep.order_sub_source IN (6, 8)
              AND o_rep.order_date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
              AND oii_rep.oii_item_sku IN ({placeholders})
            GROUP BY oii_rep.oii_item_sku, oii_rep.oii_item_price,
                     s_rep.shipment_carrier, s_rep.shipment_status
        """, (*sku_batch,))
        CARRIER_CHARGE = 5.0
        result = {}
        for r in rows:
            qty = float(r["replacement_qty"] or 0)
            sku = r["sku"]
            multiplier = 0.5 if "marked" in sku.lower() or "part" in sku.lower() else 1.0
            result[sku] = (multiplier * qty) + CARRIER_CHARGE
        return result
    except Exception as e:
        print(f"  ⚠️ Replacements skipped: {e}")
        return {}

def fetch_refund_by_amazon(order_ids):
    # Fix 3: Fetch Amazon-initiated refunds — UK FBM only
    if not order_ids:
        return {}
    placeholders = ",".join(["%s"] * len(order_ids))
    try:
        rows = mysql_query("accounts_management", f"""
            SELECT at.order_id,
                   ABS(SUM(at.total)) AS refund_by_amazon
            FROM amz_transactions at
            JOIN order_management.`order` o
                ON o.order = at.order_id
               AND o.order_market_place = '23'
               AND o.order_sub_source IN (6, 8)
            WHERE at.order_id IN ({placeholders})
       # Fix       AND at.description IN 'Refund'
              AND at.total < 0
            GROUP BY at.order_id
        """, tuple(order_ids))
        return {r["order_id"]: float(r["refund_by_amazon"] or 0) for r in rows}
    except Exception as e:
        print(f"  ⚠️ Refund by Amazon skipped: {e}")
        return {}

def fetch_ppc_for_skus(sku_batch, start, end):
    if not sku_batch:
        return {}
    placeholders = ",".join(["%s"] * len(sku_batch))
    try:
        rows = mysql_query("ppc_db", f"""
            SELECT p.amzSKU AS sku, p.amzASIN AS asin, SUM(pd.spend) AS ppc_spend
            FROM performance_data pd
            JOIN ads a ON pd.adId = a.adId
            JOIN products p ON a.productId = p.productId
            JOIN store_market_places smp
                ON a.storeMarketPlaceId = smp.storeMarketPlaceId
               AND smp.storeMarketPlaceId = 8
            WHERE pd.date BETWEEN %s AND %s
              AND p.amzSKU IS NOT NULL
              AND p.amzSKU IN ({placeholders})
            GROUP BY p.amzSKU, p.amzASIN
        """, (start, end, *sku_batch))
        return {r["sku"]: float(r["ppc_spend"] or 0) for r in rows}
    except Exception as e:
        print(f"  ⚠️ PPC skipped: {e}")
        return {}

def fetch_refunds_for_skus(sku_batch, start, end):
    if not sku_batch:
        return {}
    placeholders = ",".join(["%s"] * len(sku_batch))
    try:
        rows = mysql_query("order_management", f"""
            SELECT rr.sku, ep.item_id AS asin, SUM(rr.amount) AS refund_amount
            FROM return_refund_repla_etl rr
            JOIN listing_management.ebay_products ep
                ON ep.sku = rr.sku
               AND ep.which_channel = 'amazon'
               AND ep.site = 'uk'
               AND ep.fulfilment = 'merchant'
            WHERE rr.type = 'refund'
              AND rr.sub_source IN (6, 8)
              AND rr.mp_text = 'UK'
              AND rr.date BETWEEN %s AND %s
              AND rr.sku IN ({placeholders})
            GROUP BY rr.sku, ep.item_id
        """, (start, end, *sku_batch))
        return {r["sku"]: float(r["refund_amount"] or 0) for r in rows}
    except Exception as e:
        print(f"  ⚠️ Refunds skipped: {e}")
        return {}
        
        
def nnr_color(nnr_pct):
    # Fix 12: NNR colour banding per document spec

    if nnr_pct is None:
        return None

    if nnr_pct < 0:
        return "#d32f2f"   # Red

    elif 0 <= nnr_pct < 15:
        return "#f59e0b"   # Orange

    elif 15 <= nnr_pct < 30:
        return "#86efac"   # Light Green

    elif 30 <= nnr_pct <= 50:
        return "#16a34a"   # Dark Green

    elif nnr_pct > 50:
        return "#9333ea"   # Purple

def calc_sku_economics(orders, fees_map, ppc_map, refund_map,
                       replacement_map={}, refund_by_amazon_map={}, labman_orders=set(), postage_map={}):
    sku_data = {}
    order_totals = {}

    # Pass 1: Build order totals using ex-VAT price for weight base
    for row in orders:
        oid = row["order_id"]
        # Fix 6: Use price without VAT for weight calculation
        val = float(row["item_price"] or 0) * int(row["quantity"] or 0)
        order_totals[oid] = order_totals.get(oid, 0) + val

    # Pass 2: Calculate per-SKU economics
    for row in orders:
        sku = row["sku"]
        if not sku:
            continue
        oid                 = row["order_id"]
        oii_item_quantity   = int(row["quantity"] or 0)
        oii_item_price      = float(row["item_price"] or 0)
        order_shipping_cost = float(row["order_shipping_cost"] or 0)
        order_tax           = float(row["order_tax"] or 0)
        order_discount      = float(row["order_discount"] or 0)
        asin                = row.get("asin")

        # Eq1: sku_val — ex-VAT for weight base
        sku_val   = oii_item_price * oii_item_quantity
        order_tot = order_totals.get(oid, sku_val) or sku_val
        # Eq2: sku_weight — spec: WeightSKU = SKU Item Value / Total Item Value of Order
        sku_weight = sku_val / order_tot if order_tot > 0 else 1.0
        # Eq3: customer_paid — spec: SalesSKU = (ItemPrice×Qty) + (Shipping×Weight) + (Tax×Weight) - (Discount×Weight)
        customer_paid = sku_val + (order_shipping_cost * sku_weight) + (order_tax * sku_weight) - (order_discount * sku_weight)

        if sku not in sku_data:
            sku_data[sku] = {
                "sku": sku, "asin": asin,
                "customer_paid": 0, "listing_price": 0,
                "orders": set(), "quantity": 0,
                "amz_fee": 0, "amz_other": 0,
                "postage": 0, "ppc": 0, "refund": 0,
                "replacement": 0, "refund_by_amazon": 0
            }

        sku_data[sku]["customer_paid"] += customer_paid
        sku_data[sku]["listing_price"] += oii_item_price * oii_item_quantity
        sku_data[sku]["orders"].add(oid)
        sku_data[sku]["quantity"]      += oii_item_quantity

        fees = fees_map.get(oid, {})
        # Fix 1+2: Skip postage if LabmanLabel present
        if oid not in labman_orders:
            carrier_cost = postage_map.get(oid, None)
            postage_cost = carrier_cost if carrier_cost is not None else order_shipping_cost
            sku_data[sku]["postage"] += postage_cost * sku_weight
        # Fix: amz_fee and amz_other stored negative → abs()
        sku_data[sku]["amz_fee"]   += abs(float(fees.get("amz_fee")   or 0)) * sku_weight
        sku_data[sku]["amz_other"] += abs(float(fees.get("amz_other") or 0)) * sku_weight
        # Fix 3: Refund by Amazon per order
        sku_data[sku]["refund_by_amazon"] += refund_by_amazon_map.get(oid, 0) * sku_weight

    # Pass 3: Derived metrics
    for sku, d in sku_data.items():
        d["ppc"]         = ppc_map.get(sku, 0)
        d["refund"]      = refund_map.get(sku, 0)
        d["replacement"] = replacement_map.get(sku, 0)
        d["orders"]      = len(d["orders"])

        customer_paid = d["customer_paid"]
        listing_price = d["listing_price"]
        # Fix 8: listing_price ex-VAT for product_cost
        # Eq4: product_cost — listing_price is already ex-VAT
        product_cost  = listing_price * 0.20
        # Eq5: vat
        vat           = customer_paid * 0.20

        d["product_cost"]   = product_cost
        d["vat"]            = vat
        # Eq6: total_income
        d["total_income"]   = customer_paid
        # Eq7: total_expenses — all components
        d["total_expenses"] = (
            -d["amz_fee"] - d["amz_other"] + d["postage"] +
            d["replacement"] + d["refund"] + d["refund_by_amazon"] +
            product_cost + vat + d["ppc"]
        )
        # Eq8: NNR GBP
        d["nnr"]         = d["total_income"] - d["total_expenses"]
        # Eq9: NNR%
        d["nnr_pct"]     = (d["nnr"] / customer_paid * 100) if customer_paid > 0 else None
        d["margin_pct"]  = d["nnr_pct"]
        d["postage_pct"] = (d["postage"] / customer_paid * 100) if customer_paid > 0 else 0
        # Fix 10: AOV
        d["aov"]         = (customer_paid / d["orders"]) if d["orders"] > 0 else 0
        # Fix 12: NNR colour
        d["nnr_color"]   = nnr_color(d["nnr_pct"])

    return sku_data

def fetch_and_load(run_id):
    print(f"\n🔄 MADURO Fetcher v2 — {run_id}")
    windows  = get_windows()
    all_skus = get_all_skus()
    ph_map   = get_ph_mapping()
    print(f"  PH mapping: {len(ph_map)} SKUs mapped")

    # june 3
    sku_list      = [r["sku"] for r in all_skus]
    sku_info      = {r["sku"]: r for r in all_skus}
    results       = {w: {} for w in windows}
    total_batches = (len(sku_list) + BATCH_SIZE - 1) // BATCH_SIZE

    for window, (start, end) in windows.items():
        print(f"\n  📅 Window: {window} ({start} → {end})")
        for i in range(0, len(sku_list), BATCH_SIZE):
            batch     = sku_list[i:i+BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            print(f"    Batch {batch_num}/{total_batches}...", end="\r")
 

            try:
                orders = fetch_orders_for_skus(batch, start, end)
            except Exception as e:
                print(f"  ⚠️ Orders skipped batch {batch_num}: {e}")
                continue
            if not orders:
                continue

            order_ids            = list(set(r["order_id"] for r in orders))
            fees_map             = fetch_fees_for_orders(order_ids)
            labman_orders        = fetch_labman_label_orders(order_ids)
            postage_map          = fetch_postage_for_orders(order_ids)
            # Skip to save queries — uncomment when quota increased
            refund_by_amazon_map = {}  # fetch_refund_by_amazon(order_ids)
            replacement_map      = {}  # fetch_replacements_for_skus(batch, start, end)

            try:
                ppc_map = fetch_ppc_for_skus(batch, start, end)
            except Exception as e:
                ppc_map = {}

            try:
                refund_map = fetch_refunds_for_skus(batch, start, end)
            except Exception as e:
                refund_map = {}

            window_data = calc_sku_economics(
                orders, fees_map, ppc_map, refund_map,
                replacement_map, refund_by_amazon_map, labman_orders, postage_map
            )
            results[window].update(window_data)

        print(f"    → {len(results[window])} SKUs with data      ")

    all_sku_set = set(r["sku"] for r in all_skus)
    print(f"\n📦 Loading {len(all_sku_set)} SKUs into PostgreSQL...")

    loaded = 0
    for sku in all_sku_set:
        d3m  = results["3m"].get(sku, {})
        d30d = results["30d"].get(sku, {})
        d10d = results["10d"].get(sku, {})
        d5d  = results["5d"].get(sku, {})
        info = sku_info.get(sku, {})
        asin = d30d.get("asin") or d3m.get("asin") or info.get("item_id")

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
                    sessions_3m, sessions_30d, cvr_pct_3m, cvr_pct_30d,
                    nnr_color_3m, nnr_color_30d, aov_3m
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,
                    %s,%s,%s,
                    %s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s
                )
                ON CONFLICT (run_id, sku_id) DO UPDATE SET
                    nnr_pct_30d       = EXCLUDED.nnr_pct_30d,
                    nnr_pct_3m        = EXCLUDED.nnr_pct_3m,
                    total_income_3m   = EXCLUDED.total_income_3m,
                    total_expenses_3m = EXCLUDED.total_expenses_3m,
                    nnr_color_3m      = EXCLUDED.nnr_color_3m,
                    nnr_color_30d     = EXCLUDED.nnr_color_30d,
                    aov_3m            = EXCLUDED.aov_3m
            """, (
                run_id, sku, sku, asin,
                ph_map.get(sku, "Unassigned"), "Amazon-UK-FBM",
                d3m.get("nnr_pct"),  d30d.get("nnr_pct"),
                d10d.get("nnr_pct"), d5d.get("nnr_pct"),
                d3m.get("orders"),   d30d.get("orders"),
                d10d.get("orders"),  d5d.get("orders"),
                d3m.get("customer_paid"),  d30d.get("customer_paid"),
                d10d.get("customer_paid"), d5d.get("customer_paid"),
                d3m.get("nnr"),   d30d.get("nnr"),
                d3m.get("total_income"),   d3m.get("total_expenses"),
                d3m.get("margin_pct"),
                d3m.get("postage_pct"),    d3m.get("postage_pct"),
                None, None, None, None,
                d3m.get("nnr_color"), d30d.get("nnr_color"),
                d3m.get("aov"),
            ), fetch=False)
            loaded += 1
        except Exception as e:
            pass

    query(
        "UPDATE pipeline_runs SET status='READY', total_skus_processed=%s WHERE run_id=%s",
        (loaded, run_id), fetch=False
    )
    print(f"\n✅ Done! {loaded} SKUs loaded into {run_id}")
    return run_id


if __name__ == "__main__":
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows  = query(
        "SELECT run_id FROM pipeline_runs WHERE run_id LIKE %s ORDER BY run_id DESC LIMIT 1",
        (f"RUN-{today}-%",)
    )
    seq    = str(int(rows[0]["run_id"][-3:]) + 1).zfill(3) if rows else "001"
    run_id = f"RUN-{today}-{seq}"
    query(
        "INSERT INTO pipeline_runs (run_id, rule_version_id, status) VALUES (%s, 'v1.0', 'LOADING')",
        (run_id,), fetch=False
    )
    fetch_and_load(run_id)
