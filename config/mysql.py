import pymysql
import os
from dotenv import load_dotenv
load_dotenv()

MYSQL_BASE = {
    "host":     os.getenv("MYSQL_HOST", ""),
    "port":            int(os.getenv("MYSQL_PORT", 3307)),
    "user":     os.getenv("MYSQL_USER", ""),
    "password": os.getenv("MYSQL_PASS", ""),
    "charset":         "utf8mb4",
    "cursorclass":     pymysql.cursors.DictCursor,
    "connect_timeout": 30,
    "read_timeout":    300,
    "write_timeout":   120,
}

DATABASES = {
    "order_management":    "order_management",
    "accounts_management": "acounts_management",
    "ppc":                 "ppc_db",
    "ppc_db":              "ppc_db",
    "message_app":         "message_app",
    "listing_management":  "listing_management",
}

def get_mysql(db_name):
    return pymysql.connect(**MYSQL_BASE, database=DATABASES[db_name])

def mysql_query(db_name, sql, params=None):
    conn = get_mysql(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()
