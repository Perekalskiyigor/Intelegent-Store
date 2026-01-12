import time
from typing import Dict, List, Any
import psycopg2
from psycopg2.extras import DictCursor
import parserXLS

# --- Конфигурация БД ---
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432
}

####################1. Открываем операцию инвентаризации
def open_invent_operation(operator: str, workstation_id: str) -> dict:
    """
    1. Закрывает все незавершённые операции в IH_Operation (finished_at IS NULL).
    2. Открывает новую операцию типа INVENTAR (изъятие).
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

            # 2. Открываем новую операцию PICK (изъятие)
            print("[DB] Открываем новую операцию INVENTAR (изъятие)")
            cur.execute("""
                INSERT INTO public."IH_Operation"
                    (op_type,   status,        operator, workstation_id, started_at, finished_at)
                VALUES
                    (%s,        %s,            %s,       %s,            NOW(),      NULL)
                RETURNING id;
            """, ("INVENTAR", "IN_PROGRESS", operator, workstation_id))

            new_id = cur.fetchone()[0]

        conn.commit()
        msg = f"Открыта новая операция INVENTAR, id={new_id}, закрыто старых: {closed_count}"
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
        msg = f"Ошибка при открытии операции PICK: {e}"
        print("[ERROR]", msg)
        return {
            "ok": False,
            "op_id": None,
            "message": msg,
        }
    finally:
        if conn is not None:
            conn.close()

####################


##################### СТАРТ сессию инвентаризации в таблице IH_inventar_session

def start_inventar_session(operator_id: int) -> int:
    """
    Создаёт сессию инвентаризации.
    Возвращает ID сессии.
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public."IH_inventar_session"
                    (created_at, operator_id, status)
                VALUES
                    (NOW(), %s, 'ACTIVE')
                RETURNING id;
                """,
                (operator_id,)
            )

            session_id = cur.fetchone()[0]
            conn.commit()
            return session_id

    except Exception as e:
        if conn:
            conn.rollback()
        raise RuntimeError(f"Ошибка создания сессии инвентаризации: {e}")

    finally:
        if conn:
            conn.close()

############СТОП Сохраняем все катушки стелажа################################



############СТАРТ Копирование данных ячеек в таблицу сесии авторизции ################################
import psycopg2
from psycopg2.extras import DictCursor


def fill_inventar_items_from_bins(session_id: int) -> dict:
    """
    Копирует позиции из IH_bin в IH_inventar_item для заданной сессии.

    Берём только те ячейки, где:
      - ref_item_id IS NOT NULL
      - "ErrorSensor" = false

    Вставляем в IH_inventar_item:
      - session_id = переданный session_id
      - ref_item_id = IH_bin.ref_item_id
      - bin_id      = IH_bin.id
      - is_done     = false

    Возвращает: ok, inserted_count
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Вставка пачкой через INSERT ... SELECT
            cur.execute(
                """
                INSERT INTO public."IH_inventar_item"
                    (session_id, ref_item_id, bin_id, is_done)
                SELECT
                    %s AS session_id,
                    b.ref_item_id,
                    b.id AS bin_id,
                    false AS is_done
                FROM public."IH_bin" b
                WHERE b.ref_item_id IS NOT NULL
                  AND COALESCE(b."ErrorSensor", false) = false;
                """,
                (session_id,)
            )

            inserted = cur.rowcount
            conn.commit()

            return {"ok": True, "session_id": session_id, "inserted_count": inserted}

    except Exception as e:
        if conn:
            conn.rollback()
        return {"ok": False, "error": str(e)}

    finally:
        if conn:
            conn.close()

############СТОП Копирование данных ячеек в таблицу сесии авторизции################################



############СТАРТ Подсвечиваем красным все найденные ячейки ################################

def highlight_inventar_bins_red(session_id: int) -> dict:
    """
    Подсвечивает все ячейки, участвующие в инвентаризации,
    красным цветом без мигания.

    bin_status_id = 1 (красный)
    Blynk_id = 1
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                """
                UPDATE public."IH_led_task" t
                SET bin_status_id = 1,
                    "Blynk_id" = 1
                FROM public."IH_inventar_item" i
                WHERE i.session_id = %s
                  AND i.bin_id = t.bin_id;
                """,
                (session_id,)
            )

            updated = cur.rowcount
            conn.commit()

            return {
                "ok": True,
                "session_id": session_id,
                "highlighted_bins": updated
            }

    except Exception as e:
        if conn:
            conn.rollback()
        return {
            "ok": False,
            "error": str(e),
            "session_id": session_id
        }

    finally:
        if conn:
            conn.close()



############СТОП Подсвечиваем красным все найденные ячейки################################


############СТАРТ Читсим БИН еси вынули катушку################################
import time
import psycopg2
from psycopg2.extras import DictCursor


def inventar_wait_remove_and_clear_leds(
    session_id: int,
    poll_interval: float = 0.5,
    max_wait_seconds: float = 600.0,
) -> dict:
    """
    Инвентаризация (упрощённый этап):

    - Берём bin_id из IH_inventar_item по session_id
    - В цикле проверяем IH_bin."Sensor"
    - Если Sensor = 0:
        * IH_bin.ref_item_id = NULL
        * В IH_led_task гасим красный (bin_status_id=0, Blynk_id=0)
    - is_done НЕ трогаем
    - Выходим, когда для всех bin Sensor = 0
    """
    conn = None
    start_ts = time.time()

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # список bin для сессии
            cur.execute(
                """
                SELECT bin_id
                FROM public."IH_inventar_item"
                WHERE session_id = %s
                ORDER BY bin_id;
                """,
                (session_id,),
            )
            rows = cur.fetchall()
            bin_ids = [r["bin_id"] for r in rows if r["bin_id"] is not None]

            if not bin_ids:
                conn.commit()
                return {
                    "ok": True,
                    "session_id": session_id,
                    "message": "Нет ячеек в инвентаризации",
                }

        total = len(bin_ids)

        while True:
            if time.time() - start_ts > max_wait_seconds:
                return {
                    "ok": False,
                    "session_id": session_id,
                    "error": "timeout",
                }

            with conn.cursor(cursor_factory=DictCursor) as cur:
                # какие ячейки уже вынули
                cur.execute(
                    """
                    SELECT b.id AS bin_id
                    FROM public."IH_bin" b
                    WHERE b.id = ANY(%s)
                      AND COALESCE(b."Sensor", 0) = 0;
                    """,
                    (bin_ids,),
                )
                ready_bins = [r["bin_id"] for r in cur.fetchall()]

                if ready_bins:
                    # чистим ref_item_id
                    cur.execute(
                        """
                        UPDATE public."IH_bin"
                        SET ref_item_id = NULL
                        WHERE id = ANY(%s);
                        """,
                        (ready_bins,),
                    )

                    # гасим красный
                    cur.execute(
                        """
                        UPDATE public."IH_led_task"
                        SET bin_status_id = 0,
                            "Blynk_id" = 0
                        WHERE bin_id = ANY(%s);
                        """,
                        (ready_bins,),
                    )

                    conn.commit()

                # проверяем, все ли Sensor = 0
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM public."IH_bin"
                    WHERE id = ANY(%s)
                      AND COALESCE("Sensor", 0) <> 0;
                    """,
                    (bin_ids,),
                )
                not_done = int(cur.fetchone()["cnt"])

                if not_done == 0:
                    conn.commit()
                    return {
                        "ok": True,
                        "session_id": session_id,
                        "total_bins": total,
                        "message": "Все ячейки освобождены",
                    }

            time.sleep(poll_interval)

    except Exception as e:
        if conn:
            conn.rollback()
        return {
            "ok": False,
            "session_id": session_id,
            "error": str(e),
        }

    finally:
        if conn:
            conn.close()


############СТОП Читсим БИН еси вынули катушку################################



############СТАРТ Прсотавляем в таблицы ячеек статусы начала инвентаризации################################

############СТОП Сохраняем все катушки стелажа################################




############СТАРТ Прсотавляем в таблицы ячеек статусы начала инвентаризации################################

############СТОП Сохраняем все катушки стелажа################################


# --- Пример вызова ---
if __name__ == "__main__":

    operator = 2
    workstation_id = "WS-01"

    open_invent_operation(operator=operator, workstation_id=workstation_id)
    


    session_id = start_inventar_session(operator_id=3)  # вернул int id
    res = fill_inventar_items_from_bins(session_id)

    if res["ok"]:
        print(f"[INVENTAR] Заполнили позиции: session_id={res['session_id']} inserted={res['inserted_count']}")
    else:
        print("[ERROR]", res["error"])

    highlight_inventar_bins_red(session_id)


    res = inventar_wait_remove_and_clear_leds(session_id)

    if res["ok"]:
        print("[INVENTAR] Все ячейки освобождены")
    else:
        print("[ERROR]", res)