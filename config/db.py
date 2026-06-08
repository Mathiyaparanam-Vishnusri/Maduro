import psycopg2
from psycopg2.extras import RealDictCursor
from config.settings import DB_CONFIG

def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def query(sql, params=None, fetch=True):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        if fetch:
            return [dict(r) for r in cur.fetchall()]
        conn.commit()
        return None
    finally:
        conn.close()
