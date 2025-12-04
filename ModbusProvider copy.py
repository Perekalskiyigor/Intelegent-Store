# pyinstaller --onefile ModbusProvider.py

import time
import threading
from pymodbus.server import StartTcpServer
from pymodbus.datastore import (
    ModbusSlaveContext,
    ModbusServerContext,
    ModbusSequentialDataBlock,
)
import psycopg2

# Конфигурация хоста мадбас
HOST = "0.0.0.0"
PORT = 1502
UNIT = 2

ID_TASK = 0

# Конфигурация базы данных
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432,
}

####################################### START - Запрос на последнюю операцию ###############################
def check_last_operation_is_idle():
    """
    SELECT ... FROM public."IH_Operation" ORDER BY id DESC LIMIT 1

    Возвращает кортеж:
        (True,  op_id, workstation_id)  — последняя операция есть, status=='IDLE' и finished_at IS NULL
        (False, op_id, workstation_id)  — операция есть, но не соответствует условию
        (False, None, None)            — записей нет или ошибка
    """
    SQL = """
    SELECT id, status, operator, started_at, finished_at, expires_at, workstation_id, op_type
    FROM public."IH_Operation"
    ORDER BY id DESC
    LIMIT 1;
    """

    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(SQL)
                row = cur.fetchone()
    except Exception as e:
        print("[DB ERROR: check_last_operation_is_idle]", e)
        return False, None, None

    if not row:
        return False, None, None

    op_id = row[0]
    status = row[1]
    finished_at = row[4]
    workstation_id = row[6]

    if status == "IDLE" and finished_at is None:
        return True, op_id, workstation_id
    return False, op_id, workstation_id


####################################### STOP - Запрос на последнюю операцию ###############################


####################################### START - Обновление таблицы диодов ###############################
_last_seen_op_id = None

# Всегда обновляем поле Sensor в IH_bin по данным из Modbus
SQL_UPDATE_SENSOR = """
UPDATE public."IH_bin"
SET "Sensor" = %s
WHERE id = %s;
"""

# Для инициализации/структурного обновления IH_led_task из IH_bin
SQL_BINS_ALL = """
SELECT 
    shelf_id,
    address,
    position_no,
    id AS bin_id,
    mode_id,
    ref_item_id,
    bin_size,
    mode_blynk
FROM public."IH_bin";
"""


def ensure_led_task_structure_if_idle():
    """
    Обеспечивает, что в IH_led_task есть строки под все бины, и shelf_id актуален.
    Работает ТОЛЬКО если последняя операция IDLE и не закрыта.
    """
    global _last_seen_op_id

    try:
        is_idle, op_id, workstation_id = check_last_operation_is_idle()
    except Exception as e:
        print("[ERR] check_last_operation_is_idle failed:", e)
        return False, None

    # Нет операций вообще
    if op_id is None:
        _last_seen_op_id = None
        return False, None

    # Последняя операция не IDLE — ничего не делаем, сбрасываем флаг
    if not is_idle:
        if _last_seen_op_id is not None:
            print(f"[OP] Последняя операция {op_id} не IDLE -> _last_seen_op_id сброшен.")
        _last_seen_op_id = None
        return False, op_id

    # Операция IDLE, но мы её уже обрабатывали (структура уже создана)
    if _last_seen_op_id == op_id:
        return False, op_id

    # Новая IDLE-операция -> подтягиваем бины и обеспечиваем строки в IH_led_task
    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(SQL_BINS_ALL)
                bins = cur.fetchall()

            if not bins:
                print("[OP] В IH_bin нет строк, обновлять нечего.")
                _last_seen_op_id = op_id
                return False, op_id

            with psycopg2.connect(**DB_CONFIG) as conn2:
                with conn2.cursor() as cur2:
                    for b in bins:
                        (
                            shelf_id,
                            address,
                            position_no,
                            bin_id,
                            mode_id,
                            ref_item_id,
                            bin_size,
                            mode_blynk,
                        ) = b

                        # Обновляем/создаём строку по bin_id, но без навязывания цвета:
                        update_sql = """
                        UPDATE public."IH_led_task"
                        SET
                            shelf_id = %s
                        WHERE bin_id = %s;
                        """
                        cur2.execute(update_sql, (shelf_id, bin_id))

                        if cur2.rowcount == 0:
                            insert_sql = """
                            INSERT INTO public."IH_led_task"
                                (bin_id, shelf_id, bin_status_id, "Blynk_id")
                            VALUES (%s, %s, %s, %s);
                            """
                            cur2.execute(
                                insert_sql,
                                (bin_id, shelf_id, 0, 0),
                            )

        _last_seen_op_id = op_id
        print(f"[OP] Структура IH_led_task обеспечена для операции {op_id} (processed {len(bins)} bins).")
        return True, op_id

    except Exception as e:
        print("[DB ERROR] ensure_led_task_structure_if_idle:", e)
        return False, op_id


def update_task_color_by_sensor_if_idle():
    """
    Если последняя операция IDLE и не закрыта:

      - Sensor = 1 и ref_item_id NOT NULL -> ЗЕЛЁНЫЙ (3,1)
      - Sensor = 0 и ref_item_id NOT NULL -> КРАСНЫЙ МИГАЮЩИЙ (1,2)
      - Sensor = 0 и ref_item_id IS NULL -> БЕЛЫЙ 2 РЕЖИМ (2,2)

    Цвета пишем в IH_led_task.
    Если операция закрыта (finished_at NOT NULL или статус не IDLE) — IH_led_task НЕ трогаем.
    """
    try:
        is_idle, op_id, workstation_id = check_last_operation_is_idle()
    except Exception as e:
        print("[ERR] check_last_operation_is_idle failed in update_task_color_by_sensor_if_idle:", e)
        return False, None

    if not is_idle or op_id is None:
        # Операция не активна — полностью выходим, IH_led_task не меняем
        return False, op_id

    # 1) Зелёный: есть товар и Sensor = 1
    SQL_GREEN = """
    UPDATE public."IH_led_task" AS t
    SET 
        bin_status_id = 3,   -- зелёный
        "Blynk_id"    = 1    -- режим "не мигает" по твоей схеме
    FROM public."IH_bin" AS b
    WHERE t.bin_id = b.id
      AND b."Sensor" = 1
      AND b.ref_item_id IS NOT NULL
      AND (t.bin_status_id IS DISTINCT FROM 3 OR t."Blynk_id" IS DISTINCT FROM 1);
    """

    # 2) Красный мигающий: есть товар и Sensor = 0
    SQL_RED = """
    UPDATE public."IH_led_task" AS t
    SET 
        bin_status_id = 1,   -- красный
        "Blynk_id"    = 2    -- мигает
    FROM public."IH_bin" AS b
    WHERE t.bin_id = b.id
      AND b."Sensor" = 0
      AND b.ref_item_id IS NOT NULL
      AND (t.bin_status_id IS DISTINCT FROM 1 OR t."Blynk_id" IS DISTINCT FROM 2);
    """

    # 3) Белый 1 режим: НЕТ товара и Sensor = 0
    SQL_WHITE = """
    UPDATE public."IH_led_task" AS t
    SET 
        bin_status_id = 2,   -- белый
        "Blynk_id"    = 1    -- 1-й режим
    FROM public."IH_bin" AS b
    WHERE t.bin_id = b.id
      AND b."Sensor" = 0
      AND b.ref_item_id IS NULL
      AND (t.bin_status_id IS DISTINCT FROM 2 OR t."Blynk_id" IS DISTINCT FROM 1);
    """

    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(SQL_GREEN)
                green_rows = cur.rowcount

                cur.execute(SQL_RED)
                red_rows = cur.rowcount

                cur.execute(SQL_WHITE)
                white_rows = cur.rowcount

        print(f"[TASK SENSOR->COLOR] op_id={op_id}  GREEN={green_rows}, RED={red_rows}, WHITE={white_rows}")
        return True, op_id

    except Exception as e:
        print("[DB ERROR] update_task_color_by_sensor_if_idle:", e)
        return False, op_id


####################################### STOP - Обновление таблицы диодов ###############################


# Запрос к БД на выборку данных для Modbus:
SQL_MODBUS = """
SELECT 
    id,
    bin_id,
    bin_status_id,
    "Bin_Sensor_status",
    shelf_id,
    "Blynk_id"
FROM public."IH_led_task"
ORDER BY bin_id;
"""

# --- Конфигурация адресного пространства ---
HR_START = 0
HR_SIZE = 1000            # Запас по холдингам
ROW_WIDTH = 10            # 10 регистров на строку
BASE_ADDR = 10            # с 10-го адреса кладём строки (0-based)
MAX_BIN_ID = 10           # работа только с ячейками 1..10
MAX_ROWS = (HR_SIZE - BASE_ADDR) // ROW_WIDTH  # теоретический максимум по размеру HR
COIL_BASE = 1000  # coil 1000 -> bin 1, 1001 -> bin 2, и т.д.


# Конвертация значения для Modbus
def _to_int16(v):
    try:
        return int(v) & 0xFFFF
    except Exception:
        return 0


###################### --- Хранилище Modbus ---#############################################
store = ModbusSlaveContext(
    co=ModbusSequentialDataBlock(0, [0] * 2000),                  # coils
    hr=ModbusSequentialDataBlock(HR_START, [0] * HR_SIZE),        # holding registers
)
context = ModbusServerContext(slaves={UNIT: store}, single=False)


def run_server():
    print(f"[Modbus] SLAVE на {HOST}:{PORT} (Unit={UNIT}), HR[0..{HR_SIZE-1}]")
    StartTcpServer(context, address=(HOST, PORT))


def modbus_cycle():
    counter = 0
    while True:
        counter += 1

        # Технические регистры
        val0 = 100
        val1 = counter
        context[UNIT].setValues(3, 0, [val0, val1])

        # 1) Обеспечиваем структуру IH_led_task при активной IDLE-операции
        try:
            ensure_led_task_structure_if_idle()
        except Exception as e:
            print("[ERR] ensure_led_task_structure_if_idle in cycle:", e)

        sensor_debug = {}  # для печати массива сенсоров

        # 2) Основная работа: читаем IH_led_task, пишем в Modbus и обновляем Sensor в IH_bin
        try:
            with psycopg2.connect(**DB_CONFIG) as conn:
                # --- читаем строки для Modbus ---
                with conn.cursor() as cur:
                    cur.execute(SQL_MODBUS)
                    rows = cur.fetchall()

                rows = rows[:MAX_ROWS]

                # Очистим рабочую зону (все блоки с 10-го регистра и до конца)
                context[UNIT].setValues(3, BASE_ADDR, [0] * (HR_SIZE - BASE_ADDR))

                # --- обновляем Sensor + пишем в Modbus ---
                with conn.cursor() as cur_upd:
                    for r in rows:
                        # r:
                        # 0 - id
                        # 1 - bin_id
                        # 2 - bin_status_id
                        # 3 - Bin_Sensor_status
                        # 4 - shelf_id
                        # 5 - Blynk_id

                        bin_id_raw = r[1]
                        if bin_id_raw is None:
                            continue

                        if bin_id_raw < 1 or bin_id_raw > MAX_BIN_ID:
                            continue

                        # Адрес блока для конкретной ячейки:
                        row_index = bin_id_raw - 1
                        start_addr = BASE_ADDR + row_index * ROW_WIDTH

                        bin_id = _to_int16(bin_id_raw)
                        led_color = _to_int16(r[2] if r[2] is not None else 0)
                        blink = _to_int16(r[5] if r[5] is not None else 0)
                        shelf_id = _to_int16(r[4] if r[4] is not None else 0)

                        # Схема (10 регистров на ячейку):
                        # +0 LED_COLOR (bin_status_id)
                        # +1 BLINK ("Blynk_id")
                        # +2 BIN_ID
                        row_data = [
                            led_color,
                            blink,
                            bin_id,
                        ]

                        # Записываем данные ячейки в её блок
                        context[UNIT].setValues(3, start_addr, row_data)

                        # Читаем значение от ПЛК (если хочешь использовать HR +6 — оставляем как debug)
                        msu_mes = context[UNIT].getValues(3, start_addr + 6, 1)[0]
                        msu_mes_int = _to_int16(msu_mes)

                        # --- Читаем сенсор из COILS (функция 1), адрес 1000+ ---
                        # bin 1 -> coil 1000
                        # bin 2 -> coil 1001
                        coil_addr = COIL_BASE + (bin_id_raw - 1)

                        sensor_raw = context[UNIT].getValues(1, coil_addr, 1)[0]  # функция 1 = Coils
                        sensor_val = 1 if sensor_raw else 0

                        # Пишем в IH_bin."Sensor"
                        cur_upd.execute(
                            SQL_UPDATE_SENSOR,
                            (sensor_val, bin_id_raw)
                        )

                        sensor_debug[bin_id_raw] = (sensor_raw, sensor_val)

                        # DEBUG по ячейке
                        print(
                            f"[WRITE] bin_id={bin_id}  "
                            f"addr={start_addr}-{start_addr+len(row_data)-1}  "
                            f"data={row_data}  HR+6={msu_mes_int}"
                        )
                        print(
                            f"[INFO] BIN={bin_id} LED={led_color} BLINK={blink} "
                            f"coil={coil_addr} RAW={sensor_raw} Sensor={sensor_val}"
                        )

        except Exception as e:
            print("[DB ERROR]", e)

        # 2.1 Печатаем массив сенсоров по всем bin_id в виде [0101010000]
        bits = []
        for bid in range(1, MAX_BIN_ID + 1):
            if bid in sensor_debug:
                bits.append(str(sensor_debug[bid][1]))  # нормализованный Sensor (0/1)
            else:
                bits.append("0")  # если по какой-то причине не было данных
        print(f"[SENSORS] [{' '.join(bits)}]")

        # 3) После того как Sensor обновлён — обновляем цвета в IH_led_task ТОЛЬКО если операция IDLE и не закрыта
        update_task_color_by_sensor_if_idle()

        # Отладка тех. регистров
        val2, val3 = context[UNIT].getValues(3, 0, 2)
        print(f"[WRITE] R0={val0} R1={val1}   [READ] R0={val2} R1={val3}")

        time.sleep(1)


if __name__ == "__main__":
    # Запускаем Modbus-сервер в отдельном потоке
    threading.Thread(target=run_server, daemon=True).start()

    # Простой тест вызова (однократный)
    res_check = check_last_operation_is_idle()
    print("check:", res_check)

    # Основной цикл
    modbus_cycle()
