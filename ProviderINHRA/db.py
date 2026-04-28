# db.py
import sqlite3
import time
from typing import Optional, Any, Dict

class Database:
    def __init__(self, path: str = "ih.db") -> None:
        self.path = path
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_pragmas()
        self._init_schema()

    def _init_pragmas(self) -> None:
        # WAL: параллельное чтение при записи
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.execute("PRAGMA busy_timeout=3000;")  # 3s ожидания, если база занята

    def _init_schema(self) -> None:
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS sensor_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            bin_no INTEGER NOT NULL,
            value INTEGER NOT NULL,          -- 0/1
            quality TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sensor_history_ts ON sensor_history(ts);
        CREATE INDEX IF NOT EXISTS idx_sensor_history_bin_ts ON sensor_history(bin_no, ts);

        CREATE TABLE IF NOT EXISTS led_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            bin_no INTEGER NOT NULL,
            color INTEGER NOT NULL,
            mode INTEGER NOT NULL,
            status TEXT NOT NULL,            -- OK/ERROR
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_led_history_ts ON led_history(ts);
        """)
        self._conn.commit()

    # ------------- запись истории -------------
    def log_sensor(self, bin_no: int, value: bool, quality: str, ts: Optional[float] = None) -> None:
        if ts is None:
            ts = time.time()
        self._conn.execute(
            "INSERT INTO sensor_history(ts, bin_no, value, quality) VALUES(?,?,?,?)",
            (ts, int(bin_no), 1 if value else 0, str(quality)),
        )
        self._conn.commit()

    def log_led(self, bin_no: int, color: int, mode: int, status: str, error: Optional[str] = None, ts: Optional[float] = None) -> None:
        if ts is None:
            ts = time.time()
        self._conn.execute(
            "INSERT INTO led_history(ts, bin_no, color, mode, status, error) VALUES(?,?,?,?,?,?)",
            (ts, int(bin_no), int(color), int(mode), str(status), error),
        )
        self._conn.commit()

    # ------------- чтение (по желанию) -------------
    def get_last_sensor_events(self, limit: int = 100):
        cur = self._conn.execute(
            "SELECT ts, bin_no, value, quality FROM sensor_history ORDER BY ts DESC LIMIT ?",
            (int(limit),),
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()