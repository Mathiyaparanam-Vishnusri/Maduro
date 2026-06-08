"""
MADURO — Database Setup Script
Run this ONCE to create all tables and seed RuleStore
Usage: python setup_db.py
"""
import psycopg2
from config.settings import DB_CONFIG

def run_sql_file(cur, filepath):
    with open(filepath, "r") as f:
        sql = f.read()
    cur.execute(sql)
    print(f"✅ Executed {filepath}")

def setup():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()

    run_sql_file(cur, "sql/001_schema.sql")
    run_sql_file(cur, "sql/002_rulestore_seed.sql")

    print("\n🎉 MADURO database setup complete!")
    print(f"   Database: {DB_CONFIG['database']}")
    print(f"   Host: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    conn.close()

if __name__ == "__main__":
    setup()
