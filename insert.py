# Размещение катушки
import time
import psycopg2
from psycopg2.extras import DictCursor
import scaner


# === Глобальные переменные ===

Insert = 1   # флаг режима "Размещение" (1 - активен, 0 - выключен)
current_barcode = None  # сюда сохраним считанный штрихкод


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
                '''
                UPDATE public."IH_led_task" AS t
                SET bin_status_id = b.mode_id
                FROM public."IH_bin" AS b
                WHERE t.bin_id = b.id
                RETURNING 
                    t.id,
                    t.bin_id,
                    t.bin_status_id,
                    t."Bin_Sensor_status",
                    t.shelf_id,
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
        SELECT Siz.size AS sizgood
        FROM public."IH_ref_items" AS Items
        LEFT JOIN public."IH_ref_size" AS Siz ON Items.id = Siz.item_id
        WHERE Items.bar_code = %s
        LIMIT 1;
    """

    q_bins = """
        SELECT id
        FROM public."IH_bin"
        WHERE bin_size = %s
          AND ref_item_id IS NULL
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




#####################################START  Установка катушки и чтение датчика что она установлена
# Константы (проверь ID по своей справочной таблице IH_bin_signal):
COLOR_ID_WHITE = 2   # белый (для доступных ячеек)
COLOR_ID_GREEN = 3   # зелёный (для выбранной/размещённой)
BLINK_OFF = 1        # горит постоянно
BLINK_ON  = 2        # мигает

def placement_step_wait_sensor_and_place(
    available_bins_result: dict,
    barcode_info: dict,
    poll_interval: float = 0.2,
    place_delay: float = 5.0,
) -> dict:
    """
    Логика:

      1) Есть список подходящих ячеек (bin_ids) от get_available_bin_ids_for_barcode().
      2) В цикле опрашиваем IH_bin по этим bin_ids, ищем:
             Sensor = 1 AND ref_item_id IS NULL.
         Как только нашли:
             - в IH_led_task по этой ячейке ставим зелёный мигающий
               (bin_status_id = COLOR_ID_GREEN, Blynk_id = BLINK_ON);
             - ждём place_delay секунд.
      3) После ожидания ещё раз читаем IH_bin по выбранной ячейке:
             если Sensor всё ещё 1 и ref_item_id IS NULL:
                 - выключаем мигание (Blynk_id = BLINK_OFF, цвет остаётся зелёным);
                 - записываем ref_item_id = item_id в IH_bin;
                 - возвращаем успех.
             иначе:
                 - считаем, что размещение не подтверждено;
                 - возвращаем ячейку в режим "доступна" (белый мигающий:
                   bin_status_id = COLOR_ID_WHITE, Blynk_id = BLINK_ON);
                 - продолжаем ждать следующего срабатывания Sensor.
    """

    # --- 1. Проверка входных данных ---
    if not available_bins_result or not available_bins_result.get("ok"):
        return {
            "ok": False,
            "bin_id": None,
            "item_id": None,
            "updated_bin": False,
            "updated_led": False,
            "row_bin": None,
            "row_led_task": None,
            "row_led_status": None,
            "message": "Нет валидного результата поиска свободных ячеек",
        }

    bin_ids = available_bins_result.get("bin_ids") or []
    if not bin_ids:
        return {
            "ok": False,
            "bin_id": None,
            "item_id": None,
            "updated_bin": False,
            "updated_led": False,
            "row_bin": None,
            "row_led_task": None,
            "row_led_status": None,
            "message": "Список подходящих ячеек пуст",
        }

    # Извлекаем item_id из barcode_info
    if (
        not barcode_info
        or not barcode_info.get("ok")
        or not barcode_info.get("exists")
        or not barcode_info.get("data")
    ):
        return {
            "ok": False,
            "bin_id": None,
            "item_id": None,
            "updated_bin": False,
            "updated_led": False,
            "row_bin": None,
            "row_led_task": None,
            "row_led_status": None,
            "message": "Товар по штрихкоду не найден или check_barcode_in_db() вернул ошибку",
        }

    try:
        item_data = barcode_info["data"]
        item_id = int(item_data["id"])
    except Exception:
        return {
            "ok": False,
            "bin_id": None,
            "item_id": None,
            "updated_bin": False,
            "updated_led": False,
            "row_bin": None,
            "row_led_task": None,
            "row_led_status": None,
            "message": "Не удалось извлечь id товара из результата check_barcode_in_db()",
        }

    print("Доступные для размещения ячейки (по размеру):", bin_ids)

    conn = None
    chosen_bin_id = None
    row_bin_final = None
    row_led_task_final = None

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        # Внешний цикл — будет повторяться, пока не получится успешно разместить
        while True:
            print("Ожидаем срабатывания датчика (Sensor = 1) на одной из ячеек...")

            # --- 2. Ждём выбора ячейки по Sensor ---
            with conn.cursor(cursor_factory=DictCursor) as cur:
                chosen_bin_id = None

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
                        chosen_bin_id = candidates[0]["id"]
                        print(f"[INFO] Выбрана ячейка по Sensor: bin_id = {chosen_bin_id}")
                        break
                    elif len(candidates) > 1:
                        conn.rollback()
                        return {
                            "ok": False,
                            "bin_id": None,
                            "item_id": item_id,
                            "updated_bin": False,
                            "updated_led": False,
                            "row_bin": None,
                            "row_led_task": None,
                            "row_led_status": None,
                            "message": "Обнаружено несколько ячеек с Sensor=1. Требуется вмешательство оператора.",
                        }

                    time.sleep(poll_interval)

                # --- 3. Включаем зелёный мигающий для выбранной ячейки ---
                print("[DB] Включаем зелёный мигающий для bin_id =", chosen_bin_id)

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
                row_led_blink = cur.fetchone()
                if row_led_blink:
                    print("[DEBUG] IH_led_task (зелёный мигающий):", dict(row_led_blink))
                else:
                    print("[WARN] Для bin_id нет строки в IH_led_task при включении мигания.")

                conn.commit()

            # --- 3.5. Даём время оператору разместить катушку ---
            print(f"[INFO] Зелёный мигает. Ожидаем {place_delay} секунд для физического размещения...")
            time.sleep(place_delay)

            # --- 4. Проверяем, стоит ли катушка и фиксируем размещение ---
            conn.autocommit = False
            with conn.cursor(cursor_factory=DictCursor) as cur2:
                # 4.1. Проверяем Sensor и ref_item_id для выбранной ячейки
                cur2.execute(
                    '''
                    SELECT id, "Sensor", ref_item_id
                    FROM public."IH_bin"
                    WHERE id = %s;
                    ''',
                    (chosen_bin_id,)
                )
                row_bin_check = cur2.fetchone()

                if not row_bin_check:
                    # Странно: ячейка исчезла
                    conn.rollback()
                    return {
                        "ok": False,
                        "bin_id": chosen_bin_id,
                        "item_id": item_id,
                        "updated_bin": False,
                        "updated_led": False,
                        "row_bin": None,
                        "row_led_task": None,
                        "row_led_status": None,
                        "message": "Ячейка не найдена при подтверждении размещения.",
                    }

                row_bin_check = dict(row_bin_check)
                sensor_val = row_bin_check["Sensor"]
                ref_item = row_bin_check["ref_item_id"]

                if sensor_val == 1 and ref_item is None:
                    # ✅ Катушка стоит, ячейка ещё свободна — фиксируем размещение

                    print("[DB] Подтверждаем размещение. Пишем ref_item_id и выключаем мигание.")

                    # 4.2. Пишем ref_item_id в IH_bin
                    cur2.execute(
                        '''
                        UPDATE public."IH_bin" AS b
                        SET ref_item_id = %s
                        WHERE b.id = %s
                          AND b.ref_item_id IS NULL
                        RETURNING 
                            b.id,
                            b.ref_item_id,
                            b.bin_size,
                            b.shelf_id,
                            b.address,
                            b.position_no;
                        ''',
                        (item_id, chosen_bin_id)
                    )
                    row_bin_final = cur2.fetchone()
                    if not row_bin_final:
                        conn.rollback()
                        return {
                            "ok": True,
                            "bin_id": chosen_bin_id,
                            "item_id": item_id,
                            "updated_bin": False,
                            "updated_led": False,
                            "row_bin": None,
                            "row_led_task": None,
                            "row_led_status": None,
                            "message": (
                                "Катушка стояла, но не удалось записать в IH_bin: "
                                "ячейка уже занята или не найдена."
                            ),
                        }
                    row_bin_final = dict(row_bin_final)
                    print("[DEBUG] IH_bin после записи ref_item_id:", row_bin_final)

                    # 4.3. Переводим зелёный в постоянный (только Blynk_id)
                    cur2.execute(
                        '''
                        UPDATE public."IH_led_task" AS t
                        SET "Blynk_id" = %s
                        WHERE t.bin_id = %s
                        RETURNING 
                            t.id,
                            t.bin_id,
                            t.bin_status_id,
                            t."Bin_Sensor_status",
                            t.shelf_id,
                            t."Blynk_id";
                        ''',
                        (BLINK_OFF, chosen_bin_id)
                    )
                    row_led_task_final = cur2.fetchone()
                    if row_led_task_final:
                        row_led_task_final = dict(row_led_task_final)
                        print("[DEBUG] IH_led_task (зелёный постоянный):", row_led_task_final)
                    else:
                        print("[WARN] Для bin_id нет строки в IH_led_task при отключении мигания.")

                    conn.commit()

                    return {
                        "ok": True,
                        "bin_id": chosen_bin_id,
                        "item_id": item_id,
                        "updated_bin": True,
                        "updated_led": True,
                        "row_bin": row_bin_final,
                        "row_led_task": row_led_task_final,
                        "row_led_status": None,
                        "message": (
                            f"Катушка (item_id={item_id}) размещена в ячейке {chosen_bin_id} "
                            f"по сигналу Sensor. ref_item_id записан, зелёный постоянный."
                        ),
                    }
                else:
                    # ❌ Катушка ушла (Sensor=0) или ячейка уже занята — откатываемся
                    print(
                        "[INFO] Размещение не подтверждено (Sensor !=1 или ячейка занята). "
                        "Возвращаем ячейку в режим 'доступна' и продолжаем ожидание."
                    )

                    # Вернём ячейку в режим "доступна" — белый мигающий
                    cur2.execute(
                        '''
                        UPDATE public."IH_led_task" AS t
                        SET 
                            bin_status_id = %s,   -- белый
                            "Blynk_id"    = %s    -- мигает
                        WHERE t.bin_id = %s;
                        ''',
                        (COLOR_ID_WHITE, BLINK_ON, chosen_bin_id)
                    )

                    conn.commit()
                    # и возвращаемся в внешний while True — ждём следующего срабатывания Sensor

    except KeyboardInterrupt:
        return {
            "ok": False,
            "bin_id": chosen_bin_id,
            "item_id": item_id,
            "updated_bin": False,
            "updated_led": False,
            "row_bin": None,
            "row_led_task": None,
            "row_led_status": None,
            "message": "Ожидание выбора ячейки по Sensor прервано оператором (KeyboardInterrupt).",
        }
    except Exception as e:
        if conn is not None:
            conn.rollback()
        return {
            "ok": False,
            "bin_id": chosen_bin_id,
            "item_id": item_id,
            "updated_bin": False,
            "updated_led": False,
            "row_bin": None,
            "row_led_task": None,
            "row_led_status": None,
            "message": f"DB error при выборе ячейки по Sensor и размещении: {e}",
        }
    finally:
        if conn is not None:
            conn.close()

#####################################STOP  Установка катушки и чтение датчика что она установлена





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
    final_result = placement_step_wait_sensor_and_place(bins_result, step2)
    print("[STEP4_PLACE_BY_SENSOR]", final_result)

    if final_result.get("ok") and final_result.get("updated_bin"):
        print("[INFO] Размещение подтверждено, закрываем PLACEMENT как DONE.")
        close_res = close_placement_operation(op_id, new_status="DONE")
        print("[CLOSE_PLACEMENT]", close_res)

        print("[INFO] Открываем IDLE с пустым finished_at.")
        idle_res = open_idle_operation(operator=operator, workstation_id=workstation_id)
        print("[OPEN_IDLE]", idle_res)
    else:
        print("[WARN] Катушка не была размещена, закрываем PLACEMENT как NOT_PLACED.")
        close_res = close_placement_operation(op_id, new_status="NOT_PLACED")
        print("[CLOSE_PLACEMENT]", close_res)

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
    