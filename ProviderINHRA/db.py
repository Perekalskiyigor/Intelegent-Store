# db.py
from datetime import datetime
import sqlite3
import time
from typing import Optional, Any, Dict
import threading

class Database:
    def __init__(self, path: str = "ih.db") -> None:
        self.path = path
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_pragmas()
        self._init_schema()
        self._lock = threading.RLock()

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
        
        CREATE TABLE IF NOT EXISTS log_mcu (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,

        cnt_error1 INTEGER NOT NULL,
        cnt_error2 INTEGER NOT NULL,
        cnt_error3 INTEGER NOT NULL,
        cnt_error4 INTEGER NOT NULL,
        cnt_error5 INTEGER NOT NULL,
        cnt_error6 INTEGER NOT NULL,
        cnt_error7 INTEGER NOT NULL,
        cnt_error8 INTEGER NOT NULL,

        sw_version INTEGER NOT NULL,
        hw_version INTEGER NOT NULL,
        i2c_error INTEGER NOT NULL,

        f_err1 INTEGER NOT NULL,
        f_err2 INTEGER NOT NULL,
        f_err3 INTEGER NOT NULL,
        f_err4 INTEGER NOT NULL,
        f_err5 INTEGER NOT NULL,
        f_err6 INTEGER NOT NULL,
        f_err7 INTEGER NOT NULL,
        f_err8 INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_log_mcu_created_at ON log_mcu(created_at);
        """)
        self._conn.commit()

    # ------------- запись истории -------------
    def log_sensor(self, bin_no: int, value: bool, quality: str, ts: Optional[float] = None) -> None:
        if ts is None:
            ts = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sensor_history(ts, bin_no, value, quality) VALUES(?,?,?,?)",
                (ts, int(bin_no), 1 if value else 0, str(quality)),
            )
            self._conn.commit()

    def log_led(self, bin_no: int, color: int, mode: int, status: str, error: Optional[str] = None, ts: Optional[float] = None) -> None:
        if ts is None:
            ts = time.time()
        with self._lock:
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
    
    def log_mcu_state(self, state):
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with self._lock:
            self._conn.execute("""
                INSERT INTO log_mcu(
                    created_at,

                    cnt_error1,
                    cnt_error2,
                    cnt_error3,
                    cnt_error4,
                    cnt_error5,
                    cnt_error6,
                    cnt_error7,
                    cnt_error8,

                    sw_version,
                    hw_version,
                    i2c_error,

                    f_err1,
                    f_err2,
                    f_err3,
                    f_err4,
                    f_err5,
                    f_err6,
                    f_err7,
                    f_err8
                )
                VALUES(
                    ?,

                    ?, ?, ?, ?,
                    ?, ?, ?, ?,

                    ?, ?, ?,

                    ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
            """, (
                created_at,

                state["cnt_error1"],
                state["cnt_error2"],
                state["cnt_error3"],
                state["cnt_error4"],
                state["cnt_error5"],
                state["cnt_error6"],
                state["cnt_error7"],
                state["cnt_error8"],

                state["sw_version"],
                state["hw_version"],
                state["i2c_error"],

                state["f_err1"],
                state["f_err2"],
                state["f_err3"],
                state["f_err4"],
                state["f_err5"],
                state["f_err6"],
                state["f_err7"],
                state["f_err8"],
            ))

            self._conn.commit()

    def close(self) -> None:
        self._conn.close()