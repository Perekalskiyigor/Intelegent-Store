import psycopg2
from psycopg2.extras import DictCursor

DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432
}

def create_operation(op_type: str,
                     status: str,
                     operator: str,
                     workstation_id: str,
                     expires_minutes: int | None = None,
                     policy: str = "REFUSE") -> dict:
    """
    Создаёт новую операцию по новому принципу.

    policy:
      - "REFUSE"     -> если есть незакрытая операция для (operator, workstation_id), вернуть отказ
      - "RESUME"     -> если есть незакрытая, вернуть её id без создания новой
      - "AUTO_CLOSE" -> если есть незакрытая, закрыть её (status='CANCELLED') и открыть новую

    Возвращает: { ok: bool, op_id: int|None, message: str }
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 1) Ищем незакрытую (finished_at IS NULL)
            cur.execute("""
                SELECT id, status, started_at
                FROM public."IH_Operation"
                WHERE operator = %s
                  AND workstation_id = %s
                  AND finished_at IS NULL
                ORDER BY started_at DESC
                LIMIT 1
                FOR UPDATE
            """, (operator, workstation_id))
            open_row = cur.fetchone()

            if open_row:
                if policy == "REFUSE":
                    conn.rollback()
                    return {
                        "ok": False,
                        "op_id": int(open_row["id"]),
                        "message": f"Отказ: незакрытая операция id={open_row['id']} (status={open_row['status']})."
                    }
                elif policy == "RESUME":
                    conn.commit()
                    return {
                        "ok": True,
                        "op_id": int(open_row["id"]),
                        "message": f"Продолжаем незакрытую операцию id={open_row['id']}."
                    }
                elif policy == "AUTO_CLOSE":
                    # Закрываем прежнюю как CANCELLED (можешь заменить на EXPIRED)
                    cur.execute("""
                        UPDATE public."IH_Operation"
                        SET status = 'CANCELLED',
                            finished_at = NOW()
                        WHERE id = %s
                    """, (int(open_row["id"]),))
                else:
                    conn.rollback()
                    return {"ok": False, "op_id": None, "message": f"Неизвестная policy: {policy}"}

            # 2) Открываем новую (нет открытой, или мы её только что закрыли)
            if expires_minutes is not None:
                cur.execute("""
                    INSERT INTO public."IH_Operation"
                        (op_type, status, operator, workstation_id, started_at, expires_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW() + (%s || ' minutes')::interval)
                    RETURNING id
                """, (op_type, status, operator, workstation_id, expires_minutes))
            else:
                cur.execute("""
                    INSERT INTO public."IH_Operation"
                        (op_type, status, operator, workstation_id, started_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    RETURNING id
                """, (op_type, status, operator, workstation_id))

            new_id = cur.fetchone()[0]
            conn.commit()
            return {"ok": True, "op_id": int(new_id), "message": "Новая операция создана."}

    except Exception as e:
        if conn:
            conn.rollback()
        return {"ok": False, "op_id": None, "message": f"Ошибка БД: {e}"}
    finally:
        if conn:
            conn.close()


# === Пример использования ===
if __name__ == "__main__":
    # 1) Строго: не пускать, если есть незакрытая
    res = create_operation("PICK", "IN_PROGRESS", "gosha", "ARM-1", policy="REFUSE")
    print(res)

    # 2) Возобновить незакрытую
    res = create_operation("PICK", "IN_PROGRESS", "gosha", "ARM-1", policy="RESUME")
    print(res)

    # 3) Закрыть незакрытую и открыть новую
    res = create_operation("PUTAWAY", "IN_PROGRESS", "gosha", "ARM-1", expires_minutes=60, policy="AUTO_CLOSE")
    print(res)

