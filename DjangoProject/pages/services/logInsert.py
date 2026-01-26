from typing import Optional
from datetime import datetime, timezone
import psycopg   

DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432,
}

def ih_log(
    message: str,
    operation: str,
    source: str = "script",
    user: Optional[str] = None,
    ts: Optional[datetime] = None,
    table: str = 'public."IH_LOG"',
) -> None:
    if ts is None:
        ts = datetime.now(timezone.utc)

    sql = f'''
        INSERT INTO {table}
            (created_at, operation, source, message, "user")
        VALUES (%s, %s, %s, %s, %s)
    '''

    with psycopg.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (ts, operation, source, message, user))
