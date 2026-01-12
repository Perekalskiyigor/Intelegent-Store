import time
import psycopg2
from psycopg2.extras import DictCursor
import scaner


# --- Конфигурация БД ---
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432
}




def open_control_operation(operator: str, workstation_id: str) -> dict:
    """
    1. Закрывает все незавершённые операции в IH_Operation.
    2. Открывает новую операцию типа CONTROL.
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:

            # 1. Закрываем все незавершённые операции
            print("[DB] Закрываем все незавершённые операции в IH_Operation")
            cur.execute("""
                UPDATE public."IH_Operation"
                SET 
                    finished_at = NOW(),
                    status      = 'FINISHED'
                WHERE finished_at IS NULL;
            """)
            closed_count = cur.rowcount
            print(f"[DB] Закрыто операций: {closed_count}")

            # 2. Открываем новую операцию CONTROL
            print("[DB] Открываем новую операцию CONTROL")
            cur.execute("""
                INSERT INTO public."IH_Operation"
                    (op_type,   status,        operator, workstation_id, started_at, finished_at)
                VALUES
                    (%s,        %s,            %s,       %s,            NOW(),      NULL)
                RETURNING id;
            """, ("CONTROL", "IN_PROGRESS", operator, workstation_id))

            new_id = cur.fetchone()[0]

        conn.commit()
        msg = f"Открыта новая операция CONTROL, id={new_id}, закрыто старых: {closed_count}"
        print("[DB]", msg)

        return {
            "ok": True,
            "op_id": new_id,
            "message": msg,
            "closed_operations": closed_count,
        }

    except Exception as e:
        if conn is not None:
            conn.rollback()
        msg = f"Ошибка при открытии операции CONTROL: {e}"
        print("[ERROR]", msg)
        return {
            "ok": False,
            "op_id": None,
            "message": msg,
        }

    finally:
        if conn is not None:
            conn.close()



def control_bins() -> dict:
    """
    Контроль ячеек:

      НОРМА:
        - ref_item_id IS NOT NULL и Sensor = 1
        - ref_item_id IS NULL     и Sensor = 0
        => в IH_led_task: bin_status_id = 0, Blynk_id = 0 (ничего не горит)

      ОШИБКА (несоответствие):
        - ref_item_id IS NOT NULL и Sensor = 0
        - ref_item_id IS NULL     и Sensor = 1
        => в IH_led_task: bin_status_id = 1, Blynk_id = 2 (красный мигающий)

      Возвращает список несоответствий в формате:
        "bin = X Sensor = Y Ref_item = Z"
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        mismatches = []

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Берём все ячейки + их led-задачи
            cur.execute("""
                SELECT 
                    b.id              AS bin_id,
                    b."Sensor"        AS sensor,
                    b.ref_item_id     AS ref_item_id,
                    b.shelf_id        AS shelf_id,
                    l.id              AS led_id
                FROM public."IH_bin" b
                LEFT JOIN public."IH_led_task" l
                    ON l.bin_id = b.id;
            """)
            rows = cur.fetchall()

            for row in rows:
                bin_id      = row["bin_id"]
                sensor      = row["sensor"]
                ref_item_id = row["ref_item_id"]
                led_id      = row["led_id"]

                # Если по какой-то причине нет строки в IH_led_task — просто пропустим
                if led_id is None:
                    print(f"[WARN] Нет записи в IH_led_task для bin_id={bin_id}, пропускаю")
                    continue

                # --- НОРМА ---
                is_ok = (
                    (ref_item_id is not None and sensor == 1) or
                    (ref_item_id is None     and sensor == 0)
                )

                if is_ok:
                    # Режим 0 — ничего не горит
                    cur.execute("""
                        UPDATE public."IH_led_task"
                        SET 
                            bin_status_id        = 0,
                            "Blynk_id"           = 0,
                            "Bin_Sensor_status"  = %s
                        WHERE id = %s;
                    """, (sensor, led_id))
                    continue

                # --- НЕСООТВЕТСТВИЕ ---
                mismatches.append(
                    f"bin = {bin_id} Sensor = {sensor} Ref_item = {ref_item_id}"
                )

                # Красный мигающий
                cur.execute("""
                    UPDATE public."IH_led_task"
                    SET 
                        bin_status_id        = 1,
                        "Blynk_id"           = 2,
                        "Bin_Sensor_status"  = %s
                    WHERE id = %s;
                """, (sensor, led_id))

        conn.commit()

        return {
            "ok": True,
            "mismatches_count": len(mismatches),
            "mismatches": mismatches,
        }

    except Exception as e:
        if conn is not None:
            conn.rollback()
        msg = f"Ошибка при контроле ячеек: {e}"
        print("[ERROR]", msg)
        return {
            "ok": False,
            "message": msg,
        }
    finally:
        if conn is not None:
            conn.close()


def free_bin(bin_id: int) -> dict:
    """
    Освободить ячейку:
      - В IH_bin: обнуляем ref_item_id.
      - В IH_led_task: ставим режим bin_status_id = 0, Blynk_id = 1.
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 1. Обнуляем ref_item_id в IH_bin
            cur.execute("""
                UPDATE public."IH_bin"
                SET ref_item_id = NULL
                WHERE id = %s
                RETURNING id;
            """, (bin_id,))
            bin_row = cur.fetchone()

            if bin_row is None:
                conn.rollback()
                msg = f"Ячейка с id={bin_id} не найдена в IH_bin"
                print("[WARN]", msg)
                return {"ok": False, "message": msg}

            # 2. Обновляем режим в IH_led_task: status=0, Blynk=1
            cur.execute("""
                UPDATE public."IH_led_task"
                SET 
                    bin_status_id = 0,
                    "Blynk_id"    = 1
                WHERE bin_id = %s;
            """, (bin_id,))
            led_updated = cur.rowcount

        conn.commit()

        msg = f"Ячейка {bin_id} освобождена, обновлено записей в IH_led_task: {led_updated}"
        print("[DB]", msg)
        return {
            "ok": True,
            "bin_id": bin_id,
            "led_rows_updated": led_updated,
            "message": msg,
        }

    except Exception as e:
        if conn is not None:
            conn.rollback()
        msg = f"Ошибка при освобождении ячейки {bin_id}: {e}"
        print("[ERROR]", msg)
        return {"ok": False, "message": msg}

    finally:
        if conn is not None:
            conn.close()







open_control_operation("user", "rty")


control_bins()

# Освобождение ячейки передать номер
free_bin(2)