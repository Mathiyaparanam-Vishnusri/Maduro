import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "database": os.getenv("DB_NAME", "maduro"),
    "user":     os.getenv("DB_USER", "maduro_user"),
    "password": os.getenv("DB_PASS", "changeme"),
}

RULE_VERSION = os.getenv("RULE_VERSION", "v1.0")
API_PORT     = int(os.getenv("API_PORT", 8000))
