# Размещение катушки
import time
import psycopg2
from psycopg2.extras import DictCursor
import scaner


# === Глобальные переменные ===

Insert = 1   # флаг режима "Размещение" (1 - активен, 0 - выключен)
current_barcode = None  # сюда сохраним считанный штрихкод299633



# --- Конфигурация БД ---
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432
}


#################################################################################################
# Открываем операцию в public.. За одно фиксируем текущее состояние диодов в таске
def init_led_task_from_bin_mode() -> dict:
    try:
        with psycopg2.connect(**DB_CONFIG) as conn, conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                '''295750
                299629
                265644
                295750
                
                UPDATE public."IH_led_task" AS 

                SET bin_status_id = b.mode_id
                FROM public."IH_bin" AS b
                WHERE t.bin_id = b.id
                RETURNING 
                    t.id,
                    t.bin_id,
                    t.bin_status_id,
                    t."Bin_Sensor_status",
                    t.shelf_id,Тш\оПБТп
                    Тш\оПБТп

                    t."Blynk_id",
                    b.mode_id,
                    b.ref_item_id,
                    b.bin_size;
                '''
            )
            rows = cur.fetchall()
            updated = len(rows)

        return {
            "ok": True,
            "updated": updated,
            "rows": [dict(r) for r in rows],
            "message": (
                f"Инициализация подсветки из IH_bin завершена. "
                f"bin_status_id скопирован из mode_id. "
                f"Обновлено строк IH_led_task: {updated}."
            ),
        }

    except Exception as e:
        return {
            "ok": False,
            "updated": 0,
            "rows": [],
            "message": f"DB error при инициализации из IH_bin: {e}",
        }
#################################################################################################



#####################################START Операция размещения бронируем таблицу сиганлов
# Закрываем опарцию последнюю
# Создаём новую операцию PLACEMENT с пустым временем закрытия
def open_placement_operation(operator: str, workstation_id: str) -> dict:
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 1. Берём последнюю операцию
            cur.execute("""
                SELECT id, finished_at
                FROM public."IH_Operation"
                ORDER BY id DESC
                LIMIT 1;
            """)
            row = cur.fetchone()

            # 2. Если последняя операция не закрыта — закрываем её
            if row is not None and row["finished_at"] is None:
                last_id = row["id"]
                print(f"[DB] Закрываем незавершённую операцию id={last_id}")
                cur.execute("""
                    UPDATE public."IH_Operation"
                    SET finished_at = NOW()
                    WHERE id = %s;
                """, (last_id,))

            # 3. Создаём новую операцию PLACEMENT
            print("[DB] Открываем новую операцию PLACEMENT")
            cur.execute("""
                INSERT INTO public."IH_Operation"
                    (op_type, status, operator, workstation_id, started_at, finished_at)
                VALUES
                    (%s, %s, %s, %s, NOW(), NULL)
                RETURNING id;
            """, ("PLACEMENT", "IN_PROGRESS", operator, workstation_id))

            new_id = cur.fetchone()[0]

        conn.commit()
        msg = f"Открыта новая операция PLACEMENT, id={new_id}"
        print("[DB]", msg)
        return {
            "ok": True,
            "op_id": new_id,
            "message": msg,
        }

    except Exception as e:
        if conn is not None:
            conn.rollback()
        msg = f"Ошибка при открытии операции PLACEMENT: {e}"
        print("[ERROR]", msg)
        return {
            "ok": False,
            "op_id": None,
            "message": msg,
        }
    finally:
        if conn is not None:
            conn.close()

#####################################STOP Операция размещения бронируем таблицу сиганлов
# { "ok": bool, "op_id": int | None, "message": str }




##############################################Закрытие операции размещения

"""
    Закрывает операцию размещения в таблице IH_Operation:
      - ставит status = new_status (по умолчанию 'DONE')
      - проставляет finished_at = NOW()

    Важно:
      id, operator, started_at, workstation_id, op_type, expires_at — не трогаем.

    Возвращает:
        {
            "ok": True/False,
            "op_id": int | None,
            "row": dict | None,
            "message": str
        }
    """
def close_placement_operation(op_id: int, new_status: str = "DONE") -> dict:
    
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    '''
                    UPDATE public."IH_Operation"
                    SET 
                        status      = %s,
                        finished_at = NOW()
                    WHERE id = %s
                    RETURNING 
                        id,
                        op_type,
                        status,
                        operator,
                        workstation_id,
                        started_at,
                        finished_at,
                        expires_at;
                    ''',
                    (new_status, op_id)
                )
                row = cur.fetchone()

        if not row:
            msg = f"Операция id={op_id} не найдена или уже закрыта."
            print("[WARN]", msg)
            return {
                "ok": False,
                "op_id": op_id,
                "row": None,
                "message": msg,
            }

        row_dict = dict(row)
        msg = f"Операция id={op_id} успешно закрыта, status={row_dict['status']}."
        print("[DB]", msg)
        return {
            "ok": True,
            "op_id": op_id,
            "row": row_dict,
            "message": msg,
        }

    except Exception as e:
        msg = f"Ошибка при закрытии операции id={op_id}: {e}"
        print("[ERROR]", msg)
        return {
            "ok": False,
            "op_id": op_id,
            "row": None,
            "message": msg,
        }
    finally:
        if conn is not None:
            conn.close()

#############################################################################




#####################################START Операция сканирования получения кода товара
"""
Начало размещения

Оператор на рабочем месте (АРМ) выбирает в интерфейсе пункт «Размещение».

Затем сканирует штрих-код катушки.
"""

def placement_step_1():
    """
    Первый этап сценария 'Размещение':
    Ждём, пока сканер не вернёт штрихкод. Функция НЕ выходит,
    пока код не будет считан.
    """
    global Insert, current_barcode

    print("=== Этап 1: Размещение катушки ===")

    # Проверяем активность режима
    if Insert != 1:
        print("[INFO] Режим 'Размещение' не активен. Завершение функции.")
        return {"ok": False, "message": "Режим размещения не активен"}

    scaner.start()
    print("Сканируйте катушку...")

    try:
        barcode = None
        # ЦИКЛ, пока не получим нормальную строку
        while not barcode:
            barcode = scaner.wait_next(timeout=None)  # ждём БЕСКОНЕЧНО
            # если по какой-то причине вернулось None — цикл просто продолжится
    finally:
        scaner.stop()

    current_barcode = barcode
    print(f"[OK] Считан штрихкод: {current_barcode}")

    return {
        "ok": True,
        "barcode": current_barcode,
        "message": "Штрихкод успешно считан"
    }

#####################################STOP Операция сканирования получения кода товара
"""
{
    "ok": True,
    "barcode": "T123-ABC-99",
    "message": "Штрихкод успешно считан"
}

"""



#####################################START Операция проверки есть ли катушка в базе
"""

Этап 2. Проверка катушки в базе

Если информация по катушке есть в системе — процесс продолжается.

Если информации нет — оператор должен:

открыть базу с информацией по катушкам;

проверить, есть ли текущая катушка в учёте;

при необходимости нажать «Прервать размещение текущей катушки».
"""

def check_barcode_in_db():
    """
    Этап 2: Проверка катушки в базе данных.
    Проверяет, есть ли считанный штрихкод (current_barcode) в таблице IH_ref_items.
    Возвращает True, если найден, иначе False.
    """
    global current_barcode

    if not current_barcode:
        print("[ERROR] Нет считанного штрихкода! Сначала выполните этап 1.")
        return {"ok": False, "exists": False, "message": "Штрихкод не задан"}

    query = """
        SELECT ext_id, name, id, bar_code
        FROM public."IH_ref_items"
        WHERE bar_code = %s;
    """

    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(query, (current_barcode,))
                result = cur.fetchone()

                if result:
                    print(f"[OK] Катушка найдена: {dict(result)}")
                    return {"ok": True, "exists": True, "data": dict(result)}
                else:
                    print("[INFO] Катушка с таким штрихкодом не найдена.")
                    return {"ok": True, "exists": False, "data": None}

    except Exception as e:
        print(f"[DB ERROR] {e}")
        return {"ok": False, "exists": False, "message": str(e)}
    
#####################################STOP Операция проверки есть ли катушка в базе
"""
{
    "ok": True,
    "exists": True,
    "data": {
        "ext_id": "er34-yy",
        "name": "Resistor 10K",
        "id": 1,
        "bar_code": "ABC123"
    }
}

не найдена

{
    "ok": True,
    "exists": False,
    "data": None
}
"""


#####################################START Операция подстветки тех ячеек котрые доступнны для размещения
"""
Этап 3. Подсветка подходящих ячеек

Система анализирует, в какие ячейки может быть помещена катушка.

На всех подходящих ячейках загорается белый LED.
Это значит: туда разрешено ставить.
"""

def get_available_bin_ids_for_barcode():
    """
    Этап 3. Подсветка подходящих ячеек

    По глобальному current_barcode:
      1) находим размер товара (Siz.size AS sizgood),
      2) отдаём список id ячеек из IH_bin, где bin_size совпадает и ref_item_id IS NULL,
      3) обновляем индикацию:
         - IH_bin_signal   (режим мигания для статуса 2),
         - IH_led_task     (bin_status_id = 2 для найденных bin_id),
         - IH_bin_led_status (color_id = белый, mode_id = 2 для этих bin_id).

    Возвращает dict:
        {
            "ok": True/False,
            "item_size": str | None,
            "bin_ids": [int, ...],
            "count": int,
            "updated_led_tasks": int,
            "updated_led_status": int,
            "rows": [ ... ],           # строки из SELECT по IH_led_task + IH_bin_signal
            "bin_led_status": [ ... ], # строки из IH_bin_led_status после обновления
            "message": str,
        }
    """
    global current_barcode

    if not current_barcode:
        return {
            "ok": False,
            "item_size": None,
            "bin_ids": [],
            "count": 0,
            "updated_led_tasks": 0,
            "updated_led_status": 0,
            "rows": [],
            "bin_led_status": [],
            "message": "Нет штрих-кода",
        }

    # SQL-запросы
    q_size = """
        SELECT Siz.size::REAL AS sizgood
        FROM public."IH_ref_items" AS Items
        LEFT JOIN public."IH_ref_size" AS Siz ON Items.id = Siz.item_id
        WHERE btrim(Items.bar_code) = btrim(%s)
        LIMIT 1;
    """

    q_bins = """    
            SELECT id
        FROM public."IH_bin"
        WHERE ref_item_id IS NULL
        AND ABS(bin_size - %s) < 0.001
        ORDER BY shelf_id, address, position_no;

    """


    #  color_id=2 — это "белый" для подсветки подходящих ячеек
    COLOR_ID_WHITE = 2
    MODE_ID_BLINK  = 2   # режим мигания/индикации

    try:
        with psycopg2.connect(**DB_CONFIG) as conn, conn.cursor(cursor_factory=DictCursor) as cur:
            # 1) Размер товара по штрих-коду
            cur.execute(q_size, (current_barcode,))
            row = cur.fetchone()

            if not row or row["sizgood"] is None:
                return {
                    "ok": True,
                    "item_size": None,
                    "bin_ids": [],
                    "count": 0,
                    "updated_led_tasks": 0,
                    "updated_led_status": 0,
                    "rows": [],
                    "bin_led_status": [],
                    "message": "Размер товара не найден",
                }

            item_size = row["sizgood"]

            # 2) Свободные ячейки с таким размером
            cur.execute(q_bins, (item_size,))
            bin_ids = [r["id"] for r in cur.fetchall()]
            count_bins = len(bin_ids)

            if not bin_ids:
                return {
                    "ok": True,
                    "item_size": item_size,
                    "bin_ids": [],
                    "count": 0,
                    "updated_led_tasks": 0,
                    "updated_led_status": 0,
                    "rows": [],
                    "bin_led_status": [],
                    "message": "Подходящих свободных ячеек нет",
                }

            # 🔸 3.1. Обновим режим мигания для статуса '2' в справочнике IH_bin_signal (если нужно)
            cur.execute(
                'UPDATE public."IH_bin_signal" '
                'SET "modeBlynk" = %s '
                'WHERE id = %s;',
                (MODE_ID_BLINK, COLOR_ID_WHITE)  # здесь id=2 — запись статуса/цвета
            )

            # 🔸 3.2. Переведём задачи по этим bin_id в статус 2 (например, "подсветить")
            cur.execute(
                'UPDATE public."IH_led_task" AS t '
                'SET bin_status_id = %s '
                'WHERE t.bin_id = ANY(%s) '
                'RETURNING t.id, t.bin_id;',
                (COLOR_ID_WHITE, bin_ids)
            )
            updated_led_rows = cur.fetchall()
            updated_led_tasks = len(updated_led_rows)

            # 🔸 3.3. Обновим таблицу IH_bin_led_status по этим bin_id:
            #         color_id = 2 (белый), mode_id = 2 (мигает), updated_at = NOW()
            cur.execute(
                '''
                UPDATE public."IH_bin_led_status" AS s
                SET 
                    color_id   = %s,
                    mode_id    = %s,
                    updated_at = NOW()
                WHERE s.bin_id = ANY(%s)
                RETURNING s.bin_id, s.color_id, s.context_id, s.until_ts, s.mode_id, s.updated_at;
                ''',
                (COLOR_ID_WHITE, MODE_ID_BLINK, bin_ids)
            )
            bin_led_status_rows = cur.fetchall()
            updated_led_status = len(bin_led_status_rows)

            # 🔸 3.4. Отдадим данные для МСУ/Модбас — только по этим bin_id
            cur.execute(
                '''
                SELECT 
                    b.id, 
                    b.bin_id, 
                    b.bin_status_id, 
                    b."Bin_Sensor_status",
                    s.id        AS bin_status_id_ref,
                    s."ledColor", 
                    s."modeBlynk"
                FROM public."IH_led_task" AS b
                LEFT JOIN public."IH_bin_signal" AS s
                    ON b.bin_status_id = s.id
                WHERE b.bin_id = ANY(%s)
                ORDER BY b.bin_id;
                ''',
                (bin_ids,)
            )
            rows = cur.fetchall()

        return {
            "ok": True,
            "item_size": item_size,
            "bin_ids": bin_ids,
            "count": count_bins,
            "updated_led_tasks": updated_led_tasks,
            "updated_led_status": updated_led_status,
            "rows": [dict(r) for r in rows],
            "bin_led_status": [dict(r) for r in bin_led_status_rows],
            "message": f"Найдено подходящих свободных ячеек: {count_bins}, обновлено задач: {updated_led_tasks}, статусов подсветки: {updated_led_status}",
        }

    except Exception as e:
        return {
            "ok": False,
            "item_size": None,
            "bin_ids": [],
            "count": 0,
            "updated_led_tasks": 0,
            "updated_led_status": 0,
            "rows": [],
            "bin_led_status": [],
            "message": f"DB error: {e}",
        }

#####################################STOP Операция подстветки тех ячеек котрые доступнны для размещения




#####################################START  ыбрать ячейку по Sensor и включить зелёный мигающий
# Константы (проверь ID по своей справочной таблице IH_bin_signal):
COLOR_ID_WHITE = 2   # белый (для доступных ячеек)
COLOR_ID_GREEN = 3   # зелёный (для выбранной/размещённой)
BLINK_OFF = 1        # горит постоянно
BLINK_ON  = 2        # мигает

def placement_step_choose_bin_by_sensor_and_blink_green(
    available_bins_result: dict,
    barcode_info: dict,
    poll_interval: float = 0.2,
) -> dict:
    """
    1) Из списка bin_ids ждём, пока ровно одна ячейка станет Sensor=1 и ref_item_id IS NULL
    2) Включаем зелёный мигающий на выбранной ячейке (IH_led_task)
    3) Возвращаем chosen_bin_id и item_id (но ничего в IH_bin НЕ записываем)
    """
    if not available_bins_result or not available_bins_result.get("ok"):
        return {"ok": False, "message": "Нет валидного результата поиска свободных ячеек"}

    bin_ids = available_bins_result.get("bin_ids") or []
    if not bin_ids:
        return {"ok": False, "message": "Список подходящих ячеек пуст"}

    if (
        not barcode_info
        or not barcode_info.get("ok")
        or not barcode_info.get("exists")
        or not barcode_info.get("data")
    ):
        return {"ok": False, "message": "Товар по штрихкоду не найден (check_barcode_in_db)"}

    item_id = int(barcode_info["data"]["id"])

    chosen_bin_id = None
    conn = None

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        print("Ожидаем Sensor=1 на одной из ячеек:", bin_ids)

        with conn.cursor(cursor_factory=DictCursor) as cur:
            while True:
                cur.execute(
                    '''
                    SELECT id, "Sensor", ref_item_id
                    FROM public."IH_bin"
                    WHERE id = ANY(%s);
                    ''',
                    (bin_ids,)
                )
                rows = cur.fetchall()

                candidates = [
                    r for r in rows
                    if r["Sensor"] == 1 and r["ref_item_id"] is None
                ]

                if len(candidates) == 1:
                    chosen_bin_id = int(candidates[0]["id"])
                    print(f"[INFO] Выбрана ячейка по Sensor: bin_id={chosen_bin_id}")
                    break

                if len(candidates) > 1:
                    conn.rollback()
                    return {
                        "ok": False,
                        "message": "Несколько ячеек с Sensor=1 одновременно. Нужен оператор.",
                        "item_id": item_id,
                        "bin_id": None,
                    }

                time.sleep(poll_interval)

            # Включаем зелёный мигающий на выбранной
            cur.execute(
                '''
                UPDATE public."IH_led_task" AS t
                SET 
                    bin_status_id = %s,   -- зелёный
                    "Blynk_id"    = %s    -- мигает
                WHERE t.bin_id = %s
                RETURNING 
                    t.id,
                    t.bin_id,
                    t.bin_status_id,
                    t."Bin_Sensor_status",
                    t.shelf_id,
                    t."Blynk_id";
                ''',
                (COLOR_ID_GREEN, BLINK_ON, chosen_bin_id)
            )
            row_led = cur.fetchone()
            conn.commit()

        return {
            "ok": True,
            "bin_id": chosen_bin_id,
            "item_id": item_id,
            "row_led_task": dict(row_led) if row_led else None,
            "message": f"Ячейка выбрана (bin_id={chosen_bin_id}), зелёный мигающий включён.",
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"ok": False, "message": f"DB error в выборе ячейки по Sensor: {e}"}
    finally:
        if conn:
            conn.close()
#####################################STOP  ыбрать ячейку по Sensor и включить зелёный мигающий


#####################################START получить количество (из АПИ)
from Provider1C import get_cmpp_carrier, upsert_cmpp_to_db 

def placement_step_get_quantity_api_or_user(
    carrier_no: str,
    item_id: int,
    ask_user_if_api_failed: bool = True,
    timeout_sec: int = 180,
) -> dict:
    """
    Приоритет:
      1) пытаемся взять qty_units из API по carrier_no
         + делаем upsert в БД (как у тебя уже сделано)
      2) если API не дал qty_units — опционально спрашиваем пользователя
    Возвращает:
      { ok, qty, source, payload?, message }
    """
    # 1) API
    try:
        payload = get_cmpp_carrier(carrier_no)
        qty_units = payload.get("qty_units", None)

        # upsert в БД (чтобы справочники/катушка обновились)
        try:
            with psycopg2.connect(**DB_CONFIG) as conn:
                upsert_res = upsert_cmpp_to_db(payload, conn)
        except Exception as e:
            upsert_res = {"status": "db_error", "error": str(e)}

        # qty из API валидный?
        if qty_units is not None:
            try:
                qty = float(qty_units)
                if qty > 0:
                    return {
                        "ok": True,
                        "qty": qty,
                        "source": "api",
                        "payload": payload,
                        "upsert": upsert_res,
                        "message": f"Количество взято из API: {qty}",
                    }
            except Exception:
                pass

        # если API ответил, но qty пустой/0
        api_msg = f"API ответил, но qty_units некорректен: {qty_units}"
        if not ask_user_if_api_failed:
            return {"ok": True, "qty": None, "source": "api_empty", "message": api_msg, "payload": payload, "upsert": upsert_res}

        # fallback: спросить пользователя
        user_res = placement_step_get_quantity_for_item(item_id=item_id, ask_user=True, timeout_sec=timeout_sec)
        user_res["source"] = "user_after_api_empty"
        user_res["payload"] = payload
        user_res["upsert"] = upsert_res
        return user_res

    except Exception as e:
        # API упал/не доступен
        api_msg = f"API error: {e}"
        if not ask_user_if_api_failed:
            return {"ok": True, "qty": None, "source": "api_error", "message": api_msg}

        # fallback: спросить пользователя
        user_res = placement_step_get_quantity_for_item(item_id=item_id, ask_user=True, timeout_sec=timeout_sec)
        user_res["source"] = "user_after_api_error"
        user_res["api_error"] = str(e)
        return user_res

#####################################STOP получить количество (из АПИ)



#####################################START Нормализация R283448 -> 283448
import re

def normalize_carrier_scan(code: str) -> str:
    """
    'R283448' -> '283448'
    ' r 283448 ' -> '283448'
    Если пришло уже '296002' -> '296002'
    """
    if code is None:
        return ""
    s = str(code).strip()

    # убрать пробелы внутри, если сканер так шлёт
    s = re.sub(r"\s+", "", s)

    # убрать ведущую R/r
    if s[:1].upper() == "R":
        s = s[1:]

    # оставить только цифры (на всякий случай)
    s = re.sub(r"\D", "", s)
    return s
#####################################STOP Нормализация R283448 -> 283448



#####################################START получить количество (из БД или спросить пользователя)
def placement_step_get_quantity_for_item(
    item_id: int,
    ask_user: bool = True,
    timeout_sec: int = 180,  # 3 минуты
) -> dict:
    """
    Берём qwantity из IH_ref_items.
    Если пусто — спрашиваем пользователя.
    Если в течение timeout_sec ничего не введено — возвращаем timeout.
    """

    import time
    import msvcrt  # Windows-only

    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                '''
                SELECT ext_id, name, id, bar_code, manufactor, qwantity
                FROM public."IH_ref_items"
                WHERE id = %s
                LIMIT 1;
                ''',
                (item_id,)
            )
            row = cur.fetchone()

        if not row:
            return {"ok": False, "qty": None, "message": f"Товар item_id={item_id} не найден"}

        rowd = dict(row)
        db_qty = rowd.get("qwantity")

        # если в БД уже есть количество
        try:
            if db_qty is not None:
                qty = float(db_qty)
                if qty > 0:
                    return {
                        "ok": True,
                        "qty": qty,
                        "source": "db",
                        "item": rowd,
                        "message": f"Количество взято из БД: {qty}",
                    }
        except Exception:
            pass

        if not ask_user:
            return {
                "ok": True,
                "qty": None,
                "source": "none",
                "item": rowd,
                "message": "qwantity пусто, ввод выключен",
            }

        # ---- Ввод с таймаутом ----
        print(f"[INPUT] Для катушки '{rowd.get('name')}' (bar_code={rowd.get('bar_code')}) количество не задано.")
        print(f"Введите количество (таймаут {timeout_sec} сек). Пусто = отмена: ", end="", flush=True)

        buf = ""
        t0 = time.time()

        while True:
            # если нажали клавишу
            if msvcrt.kbhit():
                ch = msvcrt.getwch()

                # Enter
                if ch in ("\r", "\n"):
                    print("")
                    break

                # Backspace
                if ch == "\b":
                    if buf:
                        buf = buf[:-1]
                        print("\b \b", end="", flush=True)
                    continue

                # Ctrl+C
                if ch == "\x03":
                    raise KeyboardInterrupt

                buf += ch
                print(ch, end="", flush=True)

            # проверяем таймаут
            if time.time() - t0 >= timeout_sec:
                print("")
                return {
                    "ok": True,
                    "qty": None,
                    "source": "timeout",
                    "item": rowd,
                    "message": f"Таймаут ввода {timeout_sec} сек",
                }

            time.sleep(0.05)

        s = buf.strip()

        if not s:
            return {
                "ok": True,
                "qty": None,
                "source": "user_cancel",
                "item": rowd,
                "message": "Пользователь не ввёл количество",
            }

        try:
            user_qty = float(s.replace(",", "."))
        except Exception:
            return {
                "ok": False,
                "qty": None,
                "source": "user_bad",
                "item": rowd,
                "message": f"Некорректный ввод: {s}",
            }

        if user_qty <= 0:
            return {
                "ok": False,
                "qty": None,
                "source": "user_bad",
                "item": rowd,
                "message": "Количество должно быть > 0",
            }

        return {
            "ok": True,
            "qty": user_qty,
            "source": "user",
            "item": rowd,
            "message": f"Количество введено: {user_qty}",
        }

    except KeyboardInterrupt:
        return {
            "ok": True,
            "qty": None,
            "source": "interrupt",
            "message": "Ввод прерван оператором",
        }
    except Exception as e:
        return {"ok": False, "qty": None, "message": f"DB error: {e}"}
    finally:
        if conn:
            conn.close()

#####################################STOP  получить количество (из БД или спросить пользователя)

#####################################STOP  подождать перед коммитом 3 секунды
def placement_step_precommit_blink_wait(
    chosen_bin_id: int,
    wait_sec: float = 3.0,
    require_sensor_still_on: bool = True,
    poll_interval: float = 0.2,
) -> dict:
    """
    Перед коммитом выдерживаем wait_sec секунд.
    Опционально контролируем, что Sensor всё это время остаётся 1.
    """
    t0 = time.time()
    conn = None
    try:
        if not require_sensor_still_on:
            time.sleep(wait_sec)
            return {"ok": True, "message": f"Выдержали {wait_sec} сек перед коммитом"}

        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True

        while True:
            if time.time() - t0 >= wait_sec:
                break

            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    'SELECT "Sensor" FROM public."IH_bin" WHERE id = %s;',
                    (chosen_bin_id,)
                )
                r = cur.fetchone()
                if not r:
                    return {"ok": False, "message": "Ячейка не найдена при precommit wait"}
                if r["Sensor"] != 1:
                    return {"ok": False, "message": "Sensor стал 0 до коммита (катушку убрали)"}

            time.sleep(poll_interval)

        return {"ok": True, "message": f"Sensor был 1, выдержали {wait_sec} сек перед коммитом"}

    except Exception as e:
        return {"ok": False, "message": f"DB error в precommit wait: {e}"}
    finally:
        if conn:
            conn.close()


#####################################START подождать перед коммитом 3 секунды


#####################################START зафиксировать размещение в bin + сохранить в operation + выключить мигание
def placement_step_commit_to_bin_with_qty(
    op_id: int,
    chosen_bin_id: int,
    item_id: int,
    qty: float,
) -> dict:
    """
    Фиксация:
      - проверяем, что Sensor=1 и ref_item_id IS NULL
      - UPDATE IH_bin: ref_item_id=item_id, qwantity=qty
      - IH_led_task: Blynk_id = BLINK_OFF (зелёный постоянный)
      - IH_Operation: chosen_bin_id, chosen_item_id, input_qty
    """
    if qty is None:
        return {"ok": False, "message": "qty не задан"}

    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 1) перепроверка состояния ячейки
            cur.execute(
                '''
                SELECT id, "Sensor", ref_item_id
                FROM public."IH_bin"
                WHERE id = %s;
                ''',
                (chosen_bin_id,)
            )
            row_chk = cur.fetchone()
            if not row_chk:
                conn.rollback()
                return {"ok": False, "message": f"Ячейка bin_id={chosen_bin_id} не найдена"}

            if row_chk["Sensor"] != 1:
                conn.rollback()
                return {"ok": False, "message": f"Sensor=0 (катушка не стоит) для bin_id={chosen_bin_id}"}

            if row_chk["ref_item_id"] is not None:
                conn.rollback()
                return {"ok": False, "message": f"Ячейка уже занята (ref_item_id != NULL) bin_id={chosen_bin_id}"}

            # 2) пишем в bin ref_item_id + qwantity
            cur.execute(
                '''
                UPDATE public."IH_bin" AS b
                SET 
                    ref_item_id = %s,
                    qwantity    = %s
                WHERE b.id = %s
                  AND b.ref_item_id IS NULL
                RETURNING
                    shelf_id, address, position_no, id, mode_id, ref_item_id, mode_blynk,
                    "Sensor", qwantity, "ErrorSensor", bin_size, "Inventarization",
                    "UserInventarization", "DataInventarization";
                ''',
                (item_id, qty, chosen_bin_id)
            )
            row_bin = cur.fetchone()
            if not row_bin:
                conn.rollback()
                return {"ok": False, "message": "Не удалось обновить IH_bin (возможно, заняли параллельно)"}

            # 3) выключаем мигание (зелёный остаётся)
            cur.execute(
                '''
                UPDATE public."IH_led_task" AS t
                SET "Blynk_id" = %s
                WHERE t.bin_id = %s
                RETURNING 
                    t.id, t.bin_id, t.bin_status_id, t."Bin_Sensor_status", t.shelf_id, t."Blynk_id";
                ''',
                (BLINK_OFF, chosen_bin_id)
            )
            row_led = cur.fetchone()

            # 4) фиксируем в операции (для истории)
            cur.execute(
                '''
                UPDATE public."IH_Operation"
                SET 
                    chosen_bin_id  = %s,
                    chosen_item_id = %s,
                    input_qty      = %s
                WHERE id = %s
                RETURNING id, status, operator, started_at, finished_at, expires_at,
                          workstation_id, op_type, input_qty, chosen_bin_id, chosen_item_id;
                ''',
                (chosen_bin_id, item_id, qty, op_id)
            )
            row_op = cur.fetchone()

        conn.commit()
        return {
            "ok": True,
            "row_bin": dict(row_bin),
            "row_led_task": dict(row_led) if row_led else None,
            "row_operation": dict(row_op) if row_op else None,
            "message": f"Размещение зафиксировано: bin_id={chosen_bin_id}, item_id={item_id}, qty={qty}",
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"ok": False, "message": f"DB error при фиксации размещения: {e}"}
    finally:
        if conn:
            conn.close()
#####################################STOP  зафиксировать размещение в bin + сохранить в operation + выключить мигание

#####################################START Открывает операцию IDLE (op_type='IDLE', status='IDLE')
def open_idle_operation(operator: str, workstation_id: str) -> dict:
    """
    Открывает операцию IDLE (op_type='IDLE', status='IDLE')
    с finished_at = NULL.

    Важно:
      - Если последняя операция НЕ IDLE и НЕ закрыта → закрываем её.
      - Если последняя операция — IDLE и она уже открыта → НИЧЕГО НЕ ДЕЛАЕМ.
        (IDLE должен висеть открытым)
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:

            # Берём последнюю операцию
            cur.execute("""
                SELECT id, op_type, finished_at
                FROM public."IH_Operation"
                ORDER BY id DESC
                LIMIT 1;
            """)
            row = cur.fetchone()

            if row is not None:
                last_id = row["id"]
                last_type = row["op_type"]
                last_finished = row["finished_at"]

                # Если последняя операция — IDLE и она открыта → ничего не делаем
                if last_type == "IDLE" and last_finished is None:
                    msg = f"Операция IDLE уже активна (id={last_id}). Новую не создаём."
                    print("[DB]", msg)
                    return {
                        "ok": True,
                        "op_id": last_id,
                        "message": msg,
                    }

                # Если последняя не IDLE и открыта → закрываем
                if last_type != "IDLE" and last_finished is None:
                    print(f"[DB] Закрываем предыдущую незавершённую операцию id={last_id}")
                    cur.execute(
                        '''
                        UPDATE public."IH_Operation"
                        SET finished_at = NOW()
                        WHERE id = %s;
                        ''',
                        (last_id,)
                    )

            # Создаём новую IDLE
            print("[DB] Открываем новую операцию IDLE")
            cur.execute(
                '''
                INSERT INTO public."IH_Operation"
                    (op_type, status, operator, workstation_id, started_at, finished_at)
                VALUES
                    ('IDLE', 'IDLE', %s, %s, NOW(), NULL)
                RETURNING id;
                ''',
                (operator, workstation_id)
            )
            new_id = cur.fetchone()[0]

        conn.commit()
        msg = f"Открыта новая операция IDLE, id={new_id}"
        print("[DB]", msg)

        return {
            "ok": True,
            "op_id": new_id,
            "message": msg,
        }

    except Exception as e:
        if conn:
            conn.rollback()
        msg = f"Ошибка при открытии IDLE: {e}"
        print("[ERROR]", msg)

        return {
            "ok": False,
            "op_id": None,
            "message": msg,
        }

    finally:
        if conn:
            conn.close()
#####################################STOP Открывает операцию IDLE (op_type='IDLE', status='IDLE')



# --- Пример вызова ---
if __name__ == "__main__":

    operator = "ivanov"
    workstation_id = "WS-01"

    # 0. Инициализируем IH_led_task из IH_bin.mode_id
    init_result = init_led_task_from_bin_mode()
    print("[INIT_LED_TASK]", init_result)

    # 1. Открываем операцию размещения PLACEMENT
    placement_res = open_placement_operation(
        operator=operator,
        workstation_id=workstation_id
    )
    print("[OPEN_PLACEMENT]", placement_res)

    if not placement_res.get("ok"):
        print("[FATAL] Не удалось открыть операцию размещения. Выходим.")

        # на всякий случай попробуем открыть IDLE, чтобы система не осталась без операции
        idle_res = open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE_AFTER_FAIL]", idle_res)
        raise SystemExit(1)

    op_id = placement_res["op_id"]
    print(f"[INFO] Операция размещения открыта, id={op_id}")

    # 2. Сканирование катушки
    step1 = placement_step_1()
    print("[STEP1_SCAN]", step1)

    if not step1.get("ok"):
        print("[WARN] Сканирование не удалось, закрываем PLACEMENT как CANCELLED.")
        close_res = close_placement_operation(op_id, new_status="CANCELLED")
        print("[CLOSE_PLACEMENT]", close_res)

        idle_res = open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE]", idle_res)
        raise SystemExit(0)

    # 3. Проверка катушки в базе
    step2 = check_barcode_in_db()
    print("[STEP2_CHECK_DB]", step2)

    if not (step2.get("ok") and step2.get("exists")):
        print("[WARN] Товар по штрихкоду не найден, закрываем PLACEMENT как NO_ITEM.")
        close_res = close_placement_operation(op_id, new_status="NO_ITEM")
        print("[CLOSE_PLACEMENT]", close_res)

        idle_res = open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE]", idle_res)
        raise SystemExit(0)

    # 4. Подсветка доступных ячеек белым
    bins_result = get_available_bin_ids_for_barcode()
    print("[STEP3_GET_BINS]", bins_result)

    if not (bins_result.get("ok") and bins_result.get("bin_ids")):
        print("[WARN] Нет доступных ячеек, закрываем PLACEMENT как NO_BINS.")
        close_res = close_placement_operation(op_id, new_status="NO_BINS")
        print("[CLOSE_PLACEMENT]", close_res)

        idle_res = open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE]", idle_res)
        raise SystemExit(0)

    # 5. Ожидание Sensor и размещение катушки
    chosen = placement_step_choose_bin_by_sensor_and_blink_green(bins_result, step2)
    print("[STEP4_CHOOSE_BIN]", chosen)

    if not chosen.get("ok"):
        close_res = close_placement_operation(op_id, new_status="NOT_PLACED")
        print("[CLOSE_PLACEMENT]", close_res)
        idle_res = open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE]", idle_res)
        raise SystemExit(0)

    chosen_bin_id = chosen["bin_id"]
    item_id = chosen["item_id"]

    # 6) Получение количества (из БД или ввод)
    carrier_no = current_barcode  # если сканируешь именно номер катушки (296002)
    qty_res = placement_step_get_quantity_api_or_user(
        carrier_no=str(carrier_no),
        item_id=item_id,
        ask_user_if_api_failed=True,
        timeout_sec=180,
    )
    print("[STEP5_GET_QTY]", qty_res)

    qty = qty_res.get("qty")
    if not qty_res.get("ok") or qty is None:
        close_res = close_placement_operation(op_id, new_status="NO_QTY")
        print("[CLOSE_PLACEMENT]", close_res)
        idle_res = open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE]", idle_res)
        raise SystemExit(0)

        # ✅ 7) Перед коммитом поморгаем 3 секунды (зелёный мигающий уже включён)
        pre = placement_step_precommit_blink_wait(
            chosen_bin_id=chosen_bin_id,
            wait_sec=3.0,
            require_sensor_still_on=True,
        )
        print("[STEP5_5_PRECOMMIT_WAIT]", pre)

        if not pre.get("ok"):
            # если катушку убрали или что-то не так — выходим
            close_res = close_placement_operation(op_id, new_status="NOT_CONFIRMED")
            print("[CLOSE_PLACEMENT]", close_res)
            idle_res = open_idle_operation(operator=operator, workstation_id=workstation_id)
            print("[OPEN_IDLE]", idle_res)
            raise SystemExit(0)

    # 8) Коммит
    commit = placement_step_commit_to_bin_with_qty(
        op_id=op_id,
        chosen_bin_id=chosen_bin_id,
        item_id=item_id,
        qty=qty,
    )
    print("[STEP6_COMMIT]", commit)
    idle_res = open_idle_operation(operator=operator, workstation_id=workstation_id)
    print("[OPEN_IDLE]", idle_res)

    
    
    
    # На этом всё. Никакого автоматического PLACEMENT.
    # Если нужно разместить — вызываем run_placement_flow(...)
    # из кнопки АРМ или отдельного скрипта.




    # bins = check_barcode_in_db()
    # print(bins)

    # result2 = get_available_bin_ids_for_barcode()
    # print(result2)




    # resp = place_item_into_bin(result2, chosen_bin_id=4)
    # print(resp)
    