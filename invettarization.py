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
def inventar_wait_remove_and_clear_leds(
    session_id: int,
    user_id: int,                      # ⬅ пользователь
    poll_interval: float = 0.5,
    max_wait_seconds: float = 600.0,
) -> dict:
    """
    Инвентаризация (этап подтверждения изъятия):

    - Берём bin_id из IH_inventar_item по session_id
    - В цикле проверяем IH_bin."Sensor"
    - Если Sensor = 0:
        * IH_bin.ref_item_id = NULL
        * IH_bin."Inventarization" = FALSE
        * IH_bin."UserInventarization" = user_id
        * IH_bin."DataInventarization" = NOW()
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
                # ячейки, где катушка вынута
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
                    # обновляем BIN
                    cur.execute(
                        """
                        UPDATE public."IH_bin"
                        SET ref_item_id = NULL,
                            "Inventarization" = FALSE,
                            "UserInventarization" = %s,
                            "DataInventarization" = NOW()
                        WHERE id = ANY(%s);
                        """,
                        (user_id, ready_bins),
                    )

                    # гасим красный индикатор
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

                # проверяем, все ли обработаны
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



############СТАРТ Переходим в режим размещения ################################

import insert

############СТОП Переходим в режим размещения ################################




############СТАРТ Производим сравнение размещенных катушек с бывшими ################################
def reconcile_inventar_with_current_bins(session_id: int) -> dict:
    """
    Сверка "что сейчас размещено" с "что было в истории" (IH_inventar_item):

    1) Берём текущее состояние склада: все b.id (bin_id), b.ref_item_id (катушка),
       где ref_item_id IS NOT NULL и ErrorSensor=false.
    2) Если ref_item_id уже есть в IH_inventar_item для session_id -> ставим is_done=TRUE.
    3) Если ref_item_id нет в IH_inventar_item для session_id -> вставляем новую строку (is_done=FALSE).

    Возвращает: сколько отмечено как done и сколько добавлено как new.
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 1) Текущие катушки в складе (после размещений)
            cur.execute(
                """
                SELECT b.id AS bin_id, b.ref_item_id
                FROM public."IH_bin" b
                WHERE b.ref_item_id IS NOT NULL
                  AND COALESCE(b."ErrorSensor", false) = false;
                """
            )
            current = cur.fetchall()  # [{bin_id, ref_item_id}, ...]

            marked_done = 0
            inserted_new = 0

            for row in current:
                bin_id = row["bin_id"]
                ref_item_id = row["ref_item_id"]

                # 2) Есть ли такая катушка в истории этой сессии?
                cur.execute(
                    """
                    SELECT id, is_done
                    FROM public."IH_inventar_item"
                    WHERE session_id = %s
                      AND ref_item_id = %s
                    ORDER BY id
                    LIMIT 1;
                    """,
                    (session_id, ref_item_id),
                )
                found = cur.fetchone()

                if found:
                    # отмечаем как найденную (ок)
                    if not bool(found["is_done"]):
                        cur.execute(
                            """
                            UPDATE public."IH_inventar_item"
                            SET is_done = TRUE
                            WHERE id = %s;
                            """,
                            (found["id"],),
                        )
                        marked_done += 1
                else:
                    # 3) новая катушка, которой не было в истории
                    cur.execute(
                        """
                        INSERT INTO public."IH_inventar_item"
                            (session_id, ref_item_id, bin_id, is_done)
                        VALUES
                            (%s, %s, %s, FALSE);
                        """,
                        (session_id, ref_item_id, bin_id),
                    )
                    inserted_new += 1

        conn.commit()
        return {
            "ok": True,
            "session_id": session_id,
            "marked_done": marked_done,
            "inserted_new": inserted_new,
            "current_bins_checked": len(current),
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"ok": False, "session_id": session_id, "error": str(e)}

    finally:
        if conn:
            conn.close()
############СТОП Производим сравнение размещенных катушек с бывшими ################################


############СТАРТ Отчет по катушкам новые старые ################################

def inventar_report(session_id: int) -> dict:
    """
    Отчёт по сессии:
      - ok_items: is_done = TRUE (были изначально и снова размещены)
      - new_items: is_done = FALSE и катушка сейчас есть в IH_bin (значит новая для истории)
      - missing_items: is_done = FALSE и катушки сейчас нет в IH_bin (значит была в истории, но не вернулась)

    Важно: new/missing разделяем по факту наличия ref_item_id в IH_bin.
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # OK
            cur.execute(
                """
                SELECT i.id, i.ref_item_id, i.bin_id, i.is_done
                FROM public."IH_inventar_item" i
                WHERE i.session_id = %s
                  AND i.is_done = TRUE
                ORDER BY i.id;
                """,
                (session_id,),
            )
            ok_items = cur.fetchall()

            # NEW: is_done=false, но ref_item_id сейчас присутствует в IH_bin
            cur.execute(
                """
                SELECT i.id, i.ref_item_id, i.bin_id, i.is_done
                FROM public."IH_inventar_item" i
                WHERE i.session_id = %s
                  AND COALESCE(i.is_done, false) = false
                  AND EXISTS (
                      SELECT 1
                      FROM public."IH_bin" b
                      WHERE b.ref_item_id = i.ref_item_id
                        AND COALESCE(b."ErrorSensor", false) = false
                  )
                ORDER BY i.id;
                """,
                (session_id,),
            )
            new_items = cur.fetchall()

            # MISSING: is_done=false и ref_item_id сейчас нет в IH_bin
            cur.execute(
                """
                SELECT i.id, i.ref_item_id, i.bin_id, i.is_done
                FROM public."IH_inventar_item" i
                WHERE i.session_id = %s
                  AND COALESCE(i.is_done, false) = false
                  AND NOT EXISTS (
                      SELECT 1
                      FROM public."IH_bin" b
                      WHERE b.ref_item_id = i.ref_item_id
                        AND COALESCE(b."ErrorSensor", false) = false
                  )
                ORDER BY i.id;
                """,
                (session_id,),
            )
            missing_items = cur.fetchall()

        return {
            "ok": True,
            "session_id": session_id,
            "ok_count": len(ok_items),
            "new_count": len(new_items),
            "missing_count": len(missing_items),
            "ok_items": ok_items,
            "new_items": new_items,
            "missing_items": missing_items,
        }

    except Exception as e:
        return {"ok": False, "session_id": session_id, "error": str(e)}

    finally:
        if conn:
            conn.close()
############СТОП  Отчет по катушкам новые старые ################################

############СТАРТ Форматированный вывод ################################
def inventar_pretty_report_lines(session_id: int) -> dict:
    """
    Возвращает "человеческие" строки отчёта по сессии инвентаризации:

      Катушка 12345: OK / NEW / MISSING, ячейка X (текущая/историческая)

    Логика:
      - OK:      IH_inventar_item.is_done = TRUE
                + берём текущую ячейку из IH_bin (где сейчас стоит катушка)
                + историческую ячейку из IH_inventar_item.bin_id
      - NEW:     IH_inventar_item.is_done = FALSE
                и катушка ЕСТЬ в IH_bin (значит сейчас стоит, но не была в истории)
      - MISSING: IH_inventar_item.is_done = FALSE
                и катушки НЕТ в IH_bin (значит была в истории, но не вернулась)

    Примечание:
      - "текущая ячейка" берётся из IH_bin.id по ref_item_id
      - если катушка сейчас стоит в нескольких ячейках (не должно быть), покажем список
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # все строки истории по сессии
            cur.execute(
                """
                SELECT i.id, i.ref_item_id, i.bin_id AS hist_bin_id, COALESCE(i.is_done, false) AS is_done
                FROM public."IH_inventar_item" i
                WHERE i.session_id = %s
                ORDER BY i.id;
                """,
                (session_id,),
            )
            items = cur.fetchall()

            # строим map ref_item_id -> [current_bin_id, ...]
            cur.execute(
                """
                SELECT b.ref_item_id, b.id AS cur_bin_id
                FROM public."IH_bin" b
                WHERE b.ref_item_id IS NOT NULL
                  AND COALESCE(b."ErrorSensor", false) = false;
                """
            )
            current_rows = cur.fetchall()
            cur_map: Dict[int, List[int]] = {}
            for r in current_rows:
                rid = r["ref_item_id"]
                cur_map.setdefault(rid, []).append(r["cur_bin_id"])

        lines: List[str] = []
        ok_lines: List[str] = []
        new_lines: List[str] = []
        missing_lines: List[str] = []

        for it in items:
            ref_item_id = it["ref_item_id"]
            hist_bin_id = it["hist_bin_id"]
            is_done = bool(it["is_done"])

            cur_bins = cur_map.get(ref_item_id, [])

            if is_done:
                status = "OK"
                cur_part = (
                    f"текущая ячейка {cur_bins[0]}"
                    if len(cur_bins) == 1
                    else (f"текущие ячейки {cur_bins}" if len(cur_bins) > 1 else "текущая ячейка — нет")
                )
                line = f"Катушка {ref_item_id}: {status}, {cur_part} (историческая ячейка {hist_bin_id})"
                ok_lines.append(line)

            else:
                if cur_bins:
                    status = "NEW"
                    cur_part = (
                        f"текущая ячейка {cur_bins[0]}"
                        if len(cur_bins) == 1
                        else f"текущие ячейки {cur_bins}"
                    )
                    line = f"Катушка {ref_item_id}: {status}, {cur_part} (историческая ячейка {hist_bin_id})"
                    new_lines.append(line)
                else:
                    status = "MISSING"
                    line = f"Катушка {ref_item_id}: {status}, ячейка {hist_bin_id} (историческая)"
                    missing_lines.append(line)

        # итоговый порядок: OK -> NEW -> MISSING
        lines = ok_lines + new_lines + missing_lines

        return {
            "ok": True,
            "session_id": session_id,
            "total": len(lines),
            "ok_count": len(ok_lines),
            "new_count": len(new_lines),
            "missing_count": len(missing_lines),
            "lines": lines,
        }

    except Exception as e:
        return {"ok": False, "session_id": session_id, "error": str(e)}

    finally:
        if conn:
            conn.close()

############СТОП Форматированный вывод ################################


############СТАРТ  ################################

############СТОП  ################################



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


    res = inventar_wait_remove_and_clear_leds(session_id, operator)

    if res["ok"]:
        print("[INVENTAR] Все ячейки освобождены")
    else:
        print("[ERROR]", res)

    
    
    # Из модуля размещения
    # 1. Открываем операцию размещения PLACEMENT
    placement_res = insert.open_placement_operation(
        operator=operator,
        workstation_id=workstation_id
    )
    print("[OPEN_PLACEMENT]", placement_res)

    if not placement_res.get("ok"):
        print("[FATAL] Не удалось открыть операцию размещения. Выходим.")
        # на всякий случай попробуем открыть IDLE, чтобы система не осталась без операции
        idle_res = insert.open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE_AFTER_FAIL]", idle_res)
        raise SystemExit(1)

    op_id = placement_res["op_id"]
    print(f"[INFO] Операция размещения открыта, id={op_id}")

    # 2. Сканирование катушки
    step1 = insert.placement_step_1()
    print("[STEP1_SCAN]", step1)

    if not step1.get("ok"):
        print("[WARN] Сканирование не удалось, закрываем PLACEMENT как CANCELLED.")
        close_res = insert.close_placement_operation(op_id, new_status="CANCELLED")
        print("[CLOSE_PLACEMENT]", close_res)

        idle_res = insert.open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE]", idle_res)
        raise SystemExit(0)

    # 3. Проверка катушки в базе
    step2 = insert.check_barcode_in_db()
    print("[STEP2_CHECK_DB]", step2)

    if not (step2.get("ok") and step2.get("exists")):
        print("[WARN] Товар по штрихкоду не найден, закрываем PLACEMENT как NO_ITEM.")
        close_res = insert.close_placement_operation(op_id, new_status="NO_ITEM")
        print("[CLOSE_PLACEMENT]", close_res)

        idle_res = insert.open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE]", idle_res)
        raise SystemExit(0)

    # 4. Подсветка доступных ячеек белым
    bins_result = insert.get_available_bin_ids_for_barcode()
    print("[STEP3_GET_BINS]", bins_result)

    if not (bins_result.get("ok") and bins_result.get("bin_ids")):
        print("[WARN] Нет доступных ячеек, закрываем PLACEMENT как NO_BINS.")
        close_res = insert.close_placement_operation(op_id, new_status="NO_BINS")
        print("[CLOSE_PLACEMENT]", close_res)

        idle_res = insert.open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE]", idle_res)
        raise SystemExit(0)

    # 5. Ожидание Sensor и размещение катушки
    final_result = insert.placement_step_wait_sensor_and_place(bins_result, step2)
    print("[STEP4_PLACE_BY_SENSOR]", final_result)

    if final_result.get("ok") and final_result.get("updated_bin"):
        print("[INFO] Размещение подтверждено, закрываем PLACEMENT как DONE.")
        close_res = insert.close_placement_operation(op_id, new_status="DONE")
        print("[CLOSE_PLACEMENT]", close_res)

        print("[INFO] Открываем IDLE с пустым finished_at.")
        idle_res = insert.open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE]", idle_res)
    else:
        print("[WARN] Катушка не была размещена, закрываем PLACEMENT как NOT_PLACED.")
        close_res = insert.close_placement_operation(op_id, new_status="NOT_PLACED")
        print("[CLOSE_PLACEMENT]", close_res)

    sync_res = reconcile_inventar_with_current_bins(session_id)
    print("[RECONCILE]", sync_res)

    rep = inventar_report(session_id)
    print("[REPORT COUNTS]", rep["ok_count"], rep["new_count"], rep["missing_count"])

    print("=== OK (вернулось) ===")
    for r in rep["ok_items"]:
        print(r)

    print("=== NEW (новые катушки) ===")
    for r in rep["new_items"]:
        print(r)

    print("=== MISSING (не вернулось) ===")
    for r in rep["missing_items"]:
        print(r)

    pretty = inventar_pretty_report_lines(session_id)
    if pretty["ok"]:
        for s in pretty["lines"]:
            print(s)
    else:
        print("[ERROR]", pretty)