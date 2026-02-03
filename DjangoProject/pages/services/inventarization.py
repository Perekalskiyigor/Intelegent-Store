# Отбор катушки
import time
import psycopg2
from psycopg2.extras import DictCursor
from pages.services import parserXLS

import time
from pages.services import logInsert
from typing import Optional


# --- Конфигурация БД ---
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432
}

"""
Модуль: selectiion.py
Назначение:
    Реализация бизнес-логики операции ОТБОРА / ИЗЪЯТИЯ (PSLECT) катушек со склада
    по заявке из Excel-файла.

Общая схема работы:
    Операция запускается по команде оператора (через веб-интерфейс Django).
    В типовом сценарии модуль выполняет полный цикл отбора:
        1) открытие операции PICK в IH_Operation;
        2) создание сессии отбора IH_pick_session;
        3) загрузка Excel и формирование списка позиций в IH_pick_item;
        4) подбор подходящих ячеек IH_bin под каждую позицию;
        5) формирование задания на подсветку выбранных ячеек через IH_led_task;
        6) ожидание фактического изъятия (контроль по датчикам Sensor);
        7) очистка ячеек в IH_bin после подтверждённого изъятия;
        8) закрытие сессии и перевод системы обратно в режим IDLE.

Источник данных:
    Входной список позиций берётся из Excel-файла (parserXLS).
    Для каждой строки Excel:
        - выполняется поиск товара в справочнике IH_ref_items по имени;
        - создаётся запись в IH_pick_item (даже если товар не найден в справочнике);
        - позиции, не найденные в справочнике, помечаются is_done=false и попадают в список not_found.

Логика подбора ячеек:
    Для каждой позиции с ref_item_id:
        - выбирается ячейка IH_bin, где ref_item_id совпадает и qwantity > qty_plan;
        - предпочтение отдаётся ячейке с минимальным остатком "сверху" (qwantity - qty_plan);
        - результат сохраняется в IH_pick_item.bin_id, qty_picked (= фактическое количество в ячейке).

Подсветка и контроль отбора:
    После назначения ячеек формируется подсветка:
        - для ячеек текущей сессии включается зелёный режим (bin_status_id=3, Blynk_id=2);
        - далее выполняется циклический опрос IH_bin.Sensor:
            * если по ячейке из сессии Sensor стал 0 → позиция считается извлечённой:
                - IH_pick_item.picked=true
                - подсветка ячейки выключается (0/0)
            * если Sensor поменялся 1→0 в "чужой" ячейке и ErrorSensor != true → включается тревога:
                - IH_led_task: bin_status_id=1, Blynk_id=2
              при возврате 0→1 тревога автоматически снимается.

Завершение операции:
    После того как все позиции сессии извлечены:
        - выполняется очистка ячеек IH_bin (ref_item_id=NULL) только для picked=true,
          и только если Sensor по ячейке = 0 (подтверждение факта изъятия);
        - сессия IH_pick_session закрывается статусом FINISHED;
        - открывается операция IDLE (op_type='IDLE', status='IDLE', finished_at=NULL),
          чтобы система вернулась в исходный режим.



Возвращаемые значения:
    Каждая публичная функция возвращает dict с флагом ok и полезной диагностикой:
        - open_pick_operation(): op_id, closed_operations
        - start_pick_session(): session_id, created_at
        - insert_pick_items_from_excel(): inserted/not_found
        - assign_bins_for_pick_session(): found/not_found
        - run_pick_session_led_and_wait(): picked_bins, alarms
        - finalize_pick_session_clear_bins(): cleared/skipped
        - close_pick_session(): status
        - open_idle_operation(): op_id

"""
operator = "ivanov"
workstation_id = "WS-01"

def run_inventarization() -> dict:
    print("GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG")
    pass

    # logInsert.ih_log("СТАРТ Операции отобора", operation="SELECTION", source="selection", user=operator)

    # logInsert.ih_log("Запуск отбора функция open_pick_operation", operation="SELECTION", source="Отбор", user=operator)
    # open_pick_operation(operator=operator, workstation_id=workstation_id)

    # # 1) стартуем сессию
    # logInsert.ih_log("Запуск отбора функция start_pick_session", operation="SELECTION", source="Отбор", user=operator)
    # result = start_pick_session(operator_id=5)
    # print(result)
    # if not result["ok"]:
    #     logInsert.ih_log(f"Ошибка функции start_pick_session Не удалось создать сессию отбора", operation="SELECTION", source="Отбор", user=operator)
    #     raise RuntimeError("Не удалось создать сессию отбора")
    
    # logInsert.ih_log(f"{result}", operation="SELECTION", source="Отбор", user=operator)

    # session_id = int(result["session_id"])
    # logInsert.ih_log(f"Создана сессия отбора с id {session_id}", operation="SELECTION", source="Отбор", user=operator)
    

    # # 2) парсим Excel под ЭТУ сессию
    # logInsert.ih_log(f"Запуск отбора функция parserXLS.load_session_from_excel Получаем даные из Excell", operation="SELECTION", source="Отбор", user=operator)
    # excel_data = parserXLS.load_session_from_excel(session_id)
    # print(excel_data)
    # logInsert.ih_log(f"Получены даные из Excell -- {excel_data}", operation="SELECTION", source="Отбор", user=operator)

    # # 3) вставляем pick_item
    # logInsert.ih_log(f"Запуск отбора функция insert_pick_items_from_excel Заполняем таблицу pick_item", operation="SELECTION", source="Отбор", user=operator)
    # res = insert_pick_items_from_excel(session_id=session_id, excel_rows=excel_data)
    # print(res)
    # logInsert.ih_log(f"Выполнено заполнение таблицы сессии отбора pick_item {res}", operation="SELECTION", source="Отбор", user=operator)

    # # 4) подбираем bin_id
    # logInsert.ih_log(f"Запуск отбора функция assign_bins_for_pick_session Назначаем ячеййкки для будущего отбора", operation="SELECTION", source="Отбор", user=operator)
    # res = assign_bins_for_pick_session(session_id=session_id)
    # print(res)
    # logInsert.ih_log(f"Выполнено назнначение ячеек отбора {res}", operation="SELECTION", source="Отбор", user=operator)

    # # 5) включаем подсветку и ждём извлечения
    # logInsert.ih_log(f"Запуск отбора функция run_pick_session_led_and_wait включаем подсветку и ждём извлечения", operation="SELECTION", source="Отбор", user=operator)
    # res = run_pick_session_led_and_wait(session_id=session_id, poll_interval=0.5, timeout_sec=600)
    # print(res)
    # logInsert.ih_log(f"Выполнено включение подсветки {res}", operation="SELECTION", source="Отбор", user=operator)

    # logInsert.ih_log(f"Запуск отбора функция finalize_pick_session_clear_bins", operation="SELECTION", source="Отбор", user=operator)
    # res = finalize_pick_session_clear_bins(session_id=session_id)
    # print(res)
    # logInsert.ih_log(f"{res}", operation="SELECTION", source="Отбор", user=operator)

    # # 6) и только теперь закрываем сессию
    # logInsert.ih_log(f"Запуск отбора функция close_pick_session закрываем сессию отбора", operation="SELECTION", source="Отбор", user=operator)
    # res = close_pick_session(session_id=session_id)
    # print(res)
    # logInsert.ih_log(f"{res}", operation="SELECTION", source="Отбор", user=operator)

    # logInsert.ih_log(f"Переход в режим IDLE", operation="SELECTION", source="Отбор", user=operator)
    # idle_res = open_idle_operation(operator=operator, workstation_id=workstation_id)
    # print("[OPEN_IDLE]", idle_res)


    
    # logInsert.ih_log("ФИНИШ Операции отбора", operation="SELECTION", source="selection", user="ivanov")
    # return {"ok": True}




####################1. Открываем операцию забора
def open_pick_operation(operator: str, workstation_id: str) -> dict:
    """
    1. Закрывает все незавершённые операции в IH_Operation (finished_at IS NULL).
    2. Открывает новую операцию типа PICK (изъятие).
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
            print("[DB] Открываем новую операцию PICK (изъятие)")
            cur.execute("""
                INSERT INTO public."IH_Operation"
                    (op_type,   status,        operator, workstation_id, started_at, finished_at)
                VALUES
                    (%s,        %s,            %s,       %s,            NOW(),      NULL)
                RETURNING id;
            """, ("PICK", "IN_PROGRESS", operator, workstation_id))

            new_id = cur.fetchone()[0]

        conn.commit()
        msg = f"Открыта новая операция PICK, id={new_id}, закрыто старых: {closed_count}"
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




#####################2. Стартуем сессию отбора в таблице по отборам IH_pick_session

def start_pick_session(operator_id: int) -> dict:
    """
    Создаёт сессию отбора.
    Статус: ACTIVE
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                """
                INSERT INTO public."IH_pick_session"
                    (created_at, operator_id, status)
                VALUES
                    (NOW(), %s, 'ACTIVE')
                RETURNING id, created_at, operator_id, status;
                """,
                (operator_id,)
            )

            session = cur.fetchone()
            conn.commit()

            return {
                "ok": True,
                "session_id": session["id"],
                "created_at": session["created_at"],
                "operator_id": session["operator_id"],
                "status": session["status"]
            }

    except Exception as e:
        if conn:
            conn.rollback()
        return {
            "ok": False,
            "error": str(e)
        }
    finally:
        if conn:
            conn.close()
####################


#####################3. Собираем товары из екселя и вносим в таблу сессии
# Сюда подается такая структуруа 1: ['KP-1608SURCK', '268409', 'Kingbright'] 2: ['0603x4-33-5%', '271517', 'Yageo']
def insert_pick_items_from_excel(session_id: int, excel_rows: dict) -> dict:
    conn = None
    inserted = []
    not_found = []

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            for row_no, row in excel_rows.items():
                name = str(row[0]).strip()
                qty_plan = int(row[1])

                # поиск товара в справочнике по имени
                cur.execute(
                    """
                    SELECT id
                    FROM public."IH_ref_items"
                    WHERE name = %s;
                    """,
                    (name,)
                )
                ref = cur.fetchone()

                if ref:
                    ref_item_id = int(ref["id"])
                    is_done = True
                else:
                    ref_item_id = None
                    is_done = False
                    not_found.append({"row": row_no, "name": name, "qty_plan": qty_plan})

                # вставка ВСЕГДА + заполняем name
                cur.execute(
                    """
                    INSERT INTO public."IH_pick_item"
                        (session_id, ref_item_id, name, qty_plan, qty_picked, is_done)
                    VALUES
                        (%s, %s, %s, %s, 0, %s)
                    RETURNING id;
                    """,
                    (session_id, ref_item_id, name, qty_plan, is_done)
                )

                pick_item_id = int(cur.fetchone()["id"])

                inserted.append({
                    "pick_item_id": pick_item_id,
                    "ref_item_id": ref_item_id,
                    "name": name,
                    "qty_plan": qty_plan,
                    "is_done": is_done
                })

            conn.commit()

            return {
                "ok": True,
                "session_id": int(session_id),
                "inserted_count": len(inserted),
                "inserted": inserted,
                "not_found_count": len(not_found),
                "not_found": not_found
            }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"ok": False, "error": str(e)}

    finally:
        if conn:
            conn.close()
####################



##################### 4. Подбор товаров из таблицы и вставка во временную таблицу с номером сессии
def assign_bins_for_pick_session(session_id: int) -> dict:
    """
    Подбирает подходящие ячейки IH_bin под позиции в IH_pick_item для session_id.
    Условие: IH_bin.ref_item_id = pick_item.ref_item_id AND IH_bin.qwantity > pick_item.qty_plan
    Выбор: минимальный (qwantity - qty_plan) (наиболее близкое сверху)
    Результат: обновляет IH_pick_item.bin_id и qty_picked (= qwantity).
    """
    conn = None
    found = []
    not_found = []

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 1) Берём все позиции сессии, где есть ref_item_id
            cur.execute(
                """
                SELECT id, ref_item_id, name, qty_plan, bin_id
                FROM public."IH_pick_item"
                WHERE session_id = %s
                  AND ref_item_id IS NOT NULL;
                """,
                (session_id,)
            )
            items = cur.fetchall()

            for item in items:
                pick_item_id = int(item["id"])
                ref_item_id = int(item["ref_item_id"])
                qty_plan = int(item["qty_plan"])
                name = item.get("name")

                # Если уже назначен bin_id — пропустим (чтобы не перетирать)
                if item["bin_id"] is not None:
                    continue

                # 2) Ищем лучшую ячейку IH_bin
                cur.execute(
                    """
                    SELECT id, shelf_id, address, position_no, qwantity
                    FROM public."IH_bin"
                    WHERE ref_item_id = %s
                      AND qwantity > %s
                    ORDER BY (qwantity - %s) ASC, qwantity ASC
                    LIMIT 1;
                    """,
                    (ref_item_id, qty_plan, qty_plan)
                )
                bin_row = cur.fetchone()

                if not bin_row:
                    not_found.append({
                        "pick_item_id": pick_item_id,
                        "ref_item_id": ref_item_id,
                        "name": name,
                        "qty_plan": qty_plan
                    })
                    continue

                bin_id = int(bin_row["id"])
                qty_in_bin = int(bin_row["qwantity"])

                # 3) Апдейтим pick_item
                cur.execute(
                    """
                    UPDATE public."IH_pick_item"
                    SET bin_id = %s,
                        qty_picked = %s
                    WHERE id = %s
                    RETURNING id;
                    """,
                    (bin_id, qty_in_bin, pick_item_id)
                )
                cur.fetchone()

                found.append({
                    "pick_item_id": pick_item_id,
                    "ref_item_id": ref_item_id,
                    "name": name,
                    "qty_plan": qty_plan,
                    "bin_id": bin_id,
                    "qty_picked": qty_in_bin,
                    "bin": {
                        "shelf_id": bin_row["shelf_id"],
                        "address": bin_row["address"],
                        "position_no": bin_row["position_no"],
                    }
                })

            conn.commit()

            return {
                "ok": True,
                "session_id": int(session_id),
                "found_count": len(found),
                "found": found,
                "not_found_count": len(not_found),
                "not_found": not_found
            }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"ok": False, "error": str(e)}

    finally:
        if conn:
            conn.close()
####################


##################### 5. Формируем задание на подстветку ячеек в таск диодов
LED_OFF_STATUS = 0
LED_OFF_BLINK  = 0

LED_GREEN_STATUS = 3
LED_GREEN_BLINK  = 2

LED_ALARM_STATUS = 1
LED_ALARM_BLINK  = 2


# Внутренняя функция апдейта вызывается для каждого диода
def _set_led(cur, bin_ids, status_id: int, blink_id: int):
    if not bin_ids:
        return
    cur.execute(
        """
        UPDATE public."IH_led_task"
        SET bin_status_id = %s,
            "Blynk_id"    = %s
        WHERE bin_id = ANY(%s::int[]);
        """,
        (status_id, blink_id, list(map(int, bin_ids)))
    )


"""
Берём из IH_pick_item все строки этой session_id, где bin_id IS NOT NULL и "picked"=false

Для этих bin_id выставляем задание в IH_led_task: зелёный bin_status_id=3, Blynk_id=2

Дальше в цикле опрашиваем IH_bin.Sensor:

если по нужной ячейке Sensor стал 0 → считаем “извлекли”:

IH_pick_item.picked = true

в IH_led_task выключаем: bin_status_id=0, Blynk_id=0

если извлекли из ячейки, которую не должны трогать, и IH_bin."ErrorSensor" != true → включаем тревогу:

IH_led_task: bin_status_id=1, Blynk_id=2 (режим 1 + моргание 2)

Ниже код. Я сделал аккуратно:

poll_interval (частота опроса)

timeout_sec (чтобы не зависнуть навсегда, можно None)
"""

def run_pick_session_led_and_wait(
    session_id: int,
    poll_interval: float = 0.5,
    timeout_sec: Optional[float] = None
) -> dict:

    """
    1) По IH_pick_item выбирает назначенные bin_id (bin_id IS NOT NULL) и picked=false
    2) Включает зелёный на этих bin_id в IH_led_task (3/2)
    3) Ждёт, пока в IH_bin.Sensor по этим bin_id станет 0:
       - IH_pick_item.picked=true
       - выключает LED (0/0) в IH_led_task
    4) Если в любой другой ячейке Sensor поменялся 1->0 и ErrorSensor != true -> включает тревогу (1/2)
    """

    conn = None
    start_ts = time.time()

    # чтобы ловить именно изменение 1->0
    prev_sensor_by_bin: dict[int, int] = {}
    alarmed_bins: set[int] = set()
    session_bins: set[int] = set()

    picked_now = []
    alarms = []

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:

            # --- 0) загрузим исходные Sensor по всем ячейкам (нужно для детекта 1->0) ---
            cur.execute(
                """
                SELECT id, COALESCE("Sensor", 0) AS sensor, COALESCE("ErrorSensor", false) AS err
                FROM public."IH_bin";
                """
            )
            for r in cur.fetchall():
                prev_sensor_by_bin[int(r["id"])] = int(r["sensor"])

            # --- 1) взять позиции текущей сессии, где есть bin_id и еще не picked ---
            cur.execute(
                """
                SELECT id AS pick_item_id, bin_id
                FROM public."IH_pick_item"
                WHERE session_id = %s
                  AND bin_id IS NOT NULL
                  AND COALESCE("picked", false) = false;
                """,
                (session_id,)
            )
            rows = cur.fetchall()
            session_bins = {int(r["bin_id"]) for r in rows if r["bin_id"] is not None}

            # если нечего отбирать — выходим
            if not session_bins:
                conn.commit()
                return {
                    "ok": True,
                    "session_id": int(session_id),
                    "message": "Нет позиций с назначенными bin_id (или уже picked=true).",
                    "picked_now": [],
                    "alarms": []
                }

            # --- 2) включить зелёный на найденных bin_id ---
            _set_led(cur, session_bins, LED_GREEN_STATUS, LED_GREEN_BLINK)
            conn.commit()

        # --- 3) цикл ожидания ---
        while True:
            if timeout_sec is not None and (time.time() - start_ts) > timeout_sec:
                return {
                    "ok": False,
                    "session_id": int(session_id),
                    "message": f"Timeout {timeout_sec}s: не все позиции извлечены.",
                    "picked_now": picked_now,
                    "alarms": alarms
                }

            time.sleep(poll_interval)

            with conn.cursor(cursor_factory=DictCursor) as cur:
                # читаем актуальные Sensor + ErrorSensor
                cur.execute(
                    """
                    SELECT id, COALESCE("Sensor", 0) AS sensor, COALESCE("ErrorSensor", false) AS err
                    FROM public."IH_bin";
                    """
                )
                bin_rows = cur.fetchall()

                # --- 3.1) детект "чужих" изъятий и авто-снятие тревоги при возврате ---
                for r in bin_rows:
                    bin_id = int(r["id"])
                    sensor = int(r["sensor"])
                    err = bool(r["err"])

                    prev = prev_sensor_by_bin.get(bin_id, 0)

                    # 1 -> 0 : неверно извлекли (чужая ячейка)
                    if prev == 1 and sensor == 0:
                        if (bin_id not in session_bins) and (err is not True):
                            _set_led(cur, [bin_id], LED_ALARM_STATUS, LED_ALARM_BLINK)
                            alarmed_bins.add(bin_id)
                            alarms.append({"bin_id": bin_id, "reason": "unauthorized_pick_1_to_0"})

                    # 0 -> 1 : вернули обратно -> снять тревогу
                    if prev == 0 and sensor == 1:
                        if bin_id in alarmed_bins:
                            _set_led(cur, [bin_id], LED_OFF_STATUS, LED_OFF_BLINK)  # режим 0, моргание 0
                            alarmed_bins.discard(bin_id)
                            alarms.append({"bin_id": bin_id, "reason": "unauthorized_return_0_to_1_alarm_cleared"})

                    prev_sensor_by_bin[bin_id] = sensor

                    # --- 3.2) обработка наших ячеек: если Sensor стал 0 -> picked=true + выключить зелёный ---
                    # какие bin уже извлекли сейчас
                    cur.execute(
                        """
                        SELECT id, COALESCE("Sensor", 0) AS sensor
                        FROM public."IH_bin"
                        WHERE id = ANY(%s::int[]);
                        """,
                        (list(session_bins),)
                    )
                    session_bin_state = {int(x["id"]): int(x["sensor"]) for x in cur.fetchall()}

                    extracted_bins = [bid for bid, s in session_bin_state.items() if s == 0]

                    if extracted_bins:
                        # помечаем picked=true для pick_item по этим bin_id
                        cur.execute(
                            """
                            UPDATE public."IH_pick_item"
                            SET "picked" = true
                            WHERE session_id = %s
                            AND bin_id = ANY(%s::int[]);
                            """,
                            (session_id, extracted_bins)
                        )

                        # выключаем свет по этим bin_id
                        _set_led(cur, extracted_bins, LED_OFF_STATUS, LED_OFF_BLINK)

                        picked_now.extend(extracted_bins)

                    # --- 3.3) проверка: всё ли picked? ---
                    cur.execute(
                        """
                        SELECT COUNT(*) AS cnt
                        FROM public."IH_pick_item"
                        WHERE session_id = %s
                        AND bin_id IS NOT NULL
                        AND COALESCE("picked", false) = false;
                        """,
                        (session_id,)
                    )
                    left_cnt = int(cur.fetchone()["cnt"])

                    conn.commit()

                    if left_cnt == 0:
                        return {
                            "ok": True,
                            "session_id": int(session_id),
                            "message": "Все позиции извлечены (picked=true).",
                            "picked_bins": sorted(set(picked_now)),
                            "alarms": alarms
                        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"ok": False, "session_id": int(session_id), "error": str(e)}

    finally:
        if conn:
            conn.close()
###############################



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


#####################################СТАРТ Операция закрытия сессии в IH_pick_session
def close_pick_session(session_id: int) -> dict:
    """
    Закрывает сессию отбора по id.
    Статус: FINISHED
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Проверим, что сессия существует и активна
            cur.execute(
                """
                SELECT id, status
                FROM public."IH_pick_session"
                WHERE id = %s
                FOR UPDATE;
                """,
                (session_id,)
            )
            session = cur.fetchone()

            if not session:
                return {"ok": False, "message": "Сессия не найдена"}

            if session["status"] != "ACTIVE":
                return {
                    "ok": False,
                    "message": f"Сессию нельзя закрыть, текущий статус: {session['status']}"
                }

            # Закрываем сессию
            cur.execute(
                """
                UPDATE public."IH_pick_session"
                SET status = 'FINISHED'
                WHERE id = %s
                RETURNING id, status;
                """,
                (session_id,)
            )

            result = cur.fetchone()
            conn.commit()

            return {
                "ok": True,
                "session_id": result["id"],
                "status": result["status"]
            }

    except Exception as e:
        if conn:
            conn.rollback()
        return {
            "ok": False,
            "error": str(e)
        }
    finally:
        if conn:
            conn.close()

#####################################СТОП Операция закрытия сессии в IH_pick_session


#####################################СТАРТ Операции очистики ячеек в главной таблице
def finalize_pick_session_clear_bins(session_id: int) -> dict:
    """
    Для session_id:
      - Берёт строки IH_pick_item, где bin_id не NULL, picked=true
      - Проверяет, что в IH_bin.Sensor по bin_id = 0
      - Тогда очищает IH_bin.ref_item_id = NULL для этой ячейки

    Возвращает список очищенных bin_id и список пропущенных (почему не очистили).
    """
    conn = None
    cleared = []
    skipped = []

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 1) Вытащим все pick_item, которые помечены picked=true и имеют bin_id
            cur.execute(
                """
                SELECT id AS pick_item_id, bin_id
                FROM public."IH_pick_item"
                WHERE session_id = %s
                  AND bin_id IS NOT NULL
                  AND COALESCE("picked", false) = true;
                """,
                (session_id,)
            )
            items = cur.fetchall()

            if not items:
                conn.commit()
                return {
                    "ok": True,
                    "session_id": int(session_id),
                    "message": "Нет строк picked=true с bin_id для очистки.",
                    "cleared": [],
                    "skipped": []
                }

            # 2) Уникальные bin_id (чтобы не дублировать очистку)
            bin_ids = sorted({int(r["bin_id"]) for r in items})

            # 3) Читаем состояние ячеек (Sensor, ref_item_id)
            cur.execute(
                """
                SELECT id AS bin_id, COALESCE("Sensor", 0) AS sensor, ref_item_id
                FROM public."IH_bin"
                WHERE id = ANY(%s::int[]);
                """,
                (bin_ids,)
            )
            bins = {int(r["bin_id"]): r for r in cur.fetchall()}

            # 4) Для каждой ячейки: если Sensor=0 => очищаем ref_item_id
            for bid in bin_ids:
                br = bins.get(bid)
                if not br:
                    skipped.append({"bin_id": bid, "reason": "bin_not_found_in_IH_bin"})
                    continue

                sensor = int(br["sensor"])
                ref_item_id = br["ref_item_id"]

                if sensor != 0:
                    skipped.append({"bin_id": bid, "reason": f"sensor_not_zero({sensor})"})
                    continue

                # уже пусто — считаем ок, но отметим отдельно
                if ref_item_id is None:
                    cleared.append({"bin_id": bid, "cleared": False, "reason": "already_empty"})
                    continue

                # очищаем ref_item_id
                cur.execute(
                    """
                    UPDATE public."IH_bin"
                    SET ref_item_id = NULL
                    WHERE id = %s;
                    """,
                    (bid,)
                )
                cleared.append({"bin_id": bid, "cleared": True})

            conn.commit()

            return {
                "ok": True,
                "session_id": int(session_id),
                "cleared_count": len([x for x in cleared if x.get("cleared") is True]),
                "cleared": cleared,
                "skipped_count": len(skipped),
                "skipped": skipped
            }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"ok": False, "session_id": int(session_id), "error": str(e)}

    finally:
        if conn:
            conn.close()
#####################################СТОП Операции очистики ячеек в главной таблице


