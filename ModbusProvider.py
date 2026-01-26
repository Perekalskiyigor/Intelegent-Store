# pyinstaller --onefile ModbusProvider.py
import os
import sys
import hashlib
import time
import threading
from pymodbus.server import StartTcpServer
from pymodbus.datastore import (
    ModbusSlaveContext,
    ModbusServerContext,
    ModbusSequentialDataBlock,
)
import psycopg2

MODBUS_LOCK = threading.RLock()

prev_sensor = {}  # bin_id -> 0/1


# Конфигурация хоста мадбас
HOST = "0.0.0.0"
PORT = 1502
UNIT = 2

WATCHDOG_STALE_SEC = 15.0     # сколько секунд допускаем без изменений сенсоров
WATCHDOG_LOG_EVERY = 2.0      # как часто печатать строку сенсоров

last_coil_write_ts = time.time()

ID_TASK = 0

# Конфигурация базы данных
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432,
}

class WatchdogCoilBlock(ModbusSequentialDataBlock):
    def setValues(self, address, values):
        global last_coil_write_ts
        last_coil_write_ts = time.time()
        return super().setValues(address, values)


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
def update_task_color_by_sensor_if_idle():
    """
    Пока последняя операция IDLE и не закрыта — обновляем режимы диодов в IH_led_task
    по данным из IH_bin (основная таблица).

    Связь: IH_led_task.bin_id = IH_bin.id

    Логика:
      - если IH_bin."Sensor" = 1 AND IH_bin.ref_item_id IS NOT NULL:
            IH_led_task.bin_status_id = 0
            IH_led_task."Blynk_id"    = 1
      - иначе:
            IH_led_task.bin_status_id = 1
            IH_led_task."Blynk_id"    = 2

    Плюс всегда обновляем:
      - IH_led_task.shelf_id = IH_bin.shelf_id
      - IH_led_task."Bin_Sensor_status" = IH_bin."Sensor"
    """
    is_idle, op_id, workstation_id = check_last_operation_is_idle()
    if op_id is None or not is_idle:
        return False, op_id

    sql = """
    UPDATE public."IH_led_task" t
SET
    shelf_id            = b.shelf_id,
    "Bin_Sensor_status" = COALESCE(b."Sensor", 0),
    bin_status_id       = CASE
                            WHEN b."Sensor" = 1 AND b.ref_item_id IS NOT NULL THEN 0
                            WHEN b."Sensor" = 0 AND b.ref_item_id IS NULL     THEN 0
                            ELSE 1
                          END,
    "Blynk_id"          = CASE
                            WHEN b."Sensor" = 1 AND b.ref_item_id IS NOT NULL THEN 1
                            WHEN b."Sensor" = 0 AND b.ref_item_id IS NULL     THEN 1
                            ELSE 2
                          END
FROM public."IH_bin" b
WHERE t.bin_id = b.id;
    """

    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                updated = cur.rowcount
            conn.commit()

        print(f"[LED] op_id={op_id} updated_rows={updated}")
        return True, op_id

    except Exception as e:
        print("[DB ERROR] update_task_color_by_sensor_if_idle:", e)
        return False, op_id

####################################### STOP - Обновление таблицы диодов ###############################

# функцию, которая обновляет LED только по списку bin_id (и только если IDLE)
def update_led_tasks_only_changed(conn, changed_bins: list[int]) -> bool:
    """
    Обновляем IH_led_task только для bin_id из changed_bins.
    Делается ТОЛЬКО если последняя операция IDLE и не закрыта.
    """
    if not changed_bins:
        return False

    # 1) Проверяем IDLE (в этом же соединении!)
    sql_last = """
    SELECT status, finished_at
    FROM public."IH_Operation"
    ORDER BY id DESC
    LIMIT 1;
    """
    with conn.cursor() as cur:
        cur.execute(sql_last)
        row = cur.fetchone()

        if not row:
            return False

        status, finished_at = row[0], row[1]
        if status != "IDLE" or finished_at is not None:
            return False

        # 2) Защита от блокировок (чтобы не ждать секунды)
        cur.execute("SET LOCAL lock_timeout = '200ms';")
        cur.execute("SET LOCAL statement_timeout = '400ms';")

        # 3) Обновляем только нужные строки
        cur.execute(SQL_UPDATE_LED_BY_BINS, (changed_bins,))

    return True




# Добавь SQL для обновления только нужных bin_id
SQL_UPDATE_LED_BY_BINS = """
UPDATE public."IH_led_task" t
SET
    shelf_id            = b.shelf_id,
    "Bin_Sensor_status" = COALESCE(b."Sensor", 0),
    bin_status_id       = CASE
                            WHEN b."Sensor" = 1 AND b.ref_item_id IS NOT NULL THEN 0
                            WHEN b."Sensor" = 0 AND b.ref_item_id IS NULL     THEN 0
                            ELSE 1
                          END,
    "Blynk_id"          = CASE
                            WHEN b."Sensor" = 1 AND b.ref_item_id IS NOT NULL THEN 1
                            WHEN b."Sensor" = 0 AND b.ref_item_id IS NULL     THEN 1
                            ELSE 2
                          END
FROM public."IH_bin" b
WHERE t.bin_id = b.id
  AND t.bin_id = ANY(%s);
"""

SQL_REF_ITEMS = """
SELECT id, ref_item_id
FROM public."IH_bin"
WHERE id BETWEEN 1 AND %s
ORDER BY id;
"""

# --- Конфигурация адресного пространства ---
HR_START = 0
HR_SIZE = 1000            # Запас по холдингам
ROW_WIDTH = 10            # 10 регистров на строку
BASE_ADDR = 10            # с 10-го адреса кладём строки (0-based)
MAX_BIN_ID = 21           # работа только с ячейками 1..10
MAX_ROWS = (HR_SIZE - BASE_ADDR) // ROW_WIDTH  # теоретический максимум по размеру HR
COIL_BASE = 1000  # coil 1000 -> bin 1, 1001 -> bin 2, и т.д.


# Конвертация значения для Modbus
def _to_int16(v):
    try:
        return int(v) & 0xFFFF
    except Exception:
        return 0


###################### --- Хранилище Modbus ---#############################################

SQL_UPDATE_SENSOR = """
UPDATE public."IH_bin"
SET "Sensor" = %s
WHERE id = %s;
"""

store = ModbusSlaveContext(
    co=WatchdogCoilBlock(0, [0] * 2000),                  # coils
    hr=ModbusSequentialDataBlock(HR_START, [0] * HR_SIZE),        # holding registers
)
context = ModbusServerContext(slaves={UNIT: store}, single=False)


def run_server():
    print(f"[Modbus] SLAVE на {HOST}:{PORT} (Unit={UNIT}), HR[0..{HR_SIZE-1}]")
    StartTcpServer(context, address=(HOST, PORT))


def modbus_cycle():
    counter = 0
    last_bits_str = None
    last_change_ts = time.time()
    last_print_ts = 0.0

    # кэш ref_item_id
    ref_cache = {}          # bin_id -> ref_item_id (None/число)
    last_ref_fetch = 0.0
    REF_FETCH_EVERY = 0.3   # сек (можно 0.5)

    while True:
        counter += 1
        now = time.time()

        # Технические регистры
        with MODBUS_LOCK:
            context[UNIT].setValues(3, 0, [100, counter])

        sensor_debug = {}
        changed_bins = []

        try:
            with psycopg2.connect(**DB_CONFIG) as conn:
                # 1) Подчитываем ref_item_id редко (чтобы LED считать сразу)
                if now - last_ref_fetch >= REF_FETCH_EVERY:
                    with conn.cursor() as cur:
                        cur.execute(SQL_REF_ITEMS, (MAX_BIN_ID,))
                        ref_cache = {bid: ref for (bid, ref) in cur.fetchall()}
                    last_ref_fetch = now

                # 2) Снимаем слепок coils одним чтением (быстро)
                with MODBUS_LOCK:
                    coils_snapshot = context[UNIT].getValues(1, COIL_BASE, MAX_BIN_ID)

                # 3) Пишем HR (LED) + обновляем Sensor в БД
                with conn.cursor() as cur_upd:
                    for bin_id_raw in range(1, MAX_BIN_ID + 1):
                        start_addr = BASE_ADDR + (bin_id_raw - 1) * ROW_WIDTH

                        # --- Сенсор ---
                        sensor_raw = coils_snapshot[bin_id_raw - 1]
                        sensor_val = 1 if sensor_raw else 0
                        sensor_debug[bin_id_raw] = (sensor_raw, sensor_val)

                        # --- ref_item_id (из кэша) ---
                        ref_item_id = ref_cache.get(bin_id_raw)

                        # --- Быстрый расчёт "OK/ERROR" как в твоём SQL ---
                        ok = ((sensor_val == 1 and ref_item_id is not None) or
                              (sensor_val == 0 and ref_item_id is None))

                        # ВАЖНО: сопоставь с твоим ПЛК:
                        # bin_status_id (LED_COLOR): 0=зелёный (OK), 1=красный (ERROR)
                        # Blynk_id (BLINK): 1=постоянно, 2=мигает
                        led_color = 0 if ok else 1
                        blink = 1 if ok else 2

                        row_data = [_to_int16(led_color), _to_int16(blink), _to_int16(bin_id_raw)]

                        # ✅ пишем HR быстро (короткий lock)
                        with MODBUS_LOCK:
                            context[UNIT].setValues(3, start_addr, row_data)

                        # ✅ Sensor в БД пишем всегда
                        cur_upd.execute(SQL_UPDATE_SENSOR, (sensor_val, bin_id_raw))

                # 4) changed_bins (по сенсорам)
                for bid in range(1, MAX_BIN_ID + 1):
                    new_val = sensor_debug.get(bid, (0, 0))[1]
                    old_val = prev_sensor.get(bid)
                    if old_val is None or old_val != new_val:
                        changed_bins.append(bid)
                    prev_sensor[bid] = new_val

                # 5) Обновляем IH_led_task только если IDLE и только changed_bins
                if changed_bins:
                    try:
                        updated = update_led_tasks_only_changed(conn, changed_bins)
                        if updated:
                            print(f"[LED_TASK_DB] changed_bins={changed_bins}")
                    except Exception as e:
                        print("[DB ERROR] update_led_tasks_only_changed:", e)

                conn.commit()

        except Exception as e:
            print("[DB ERROR]", e)

        # Печать сенсоров
        bits_str = ''.join(str(sensor_debug.get(bid, (0, 0))[1]) for bid in range(1, MAX_BIN_ID + 1))

        if bits_str != last_bits_str:
            last_bits_str = bits_str
            last_change_ts = now

        if now - last_print_ts >= WATCHDOG_LOG_EVERY:
            age = now - last_coil_write_ts
            print(f"[SENSORS] {bits_str}  last_write={age:.1f}s  cnt={counter}")
            last_print_ts = now

        if (now - last_coil_write_ts) >= WATCHDOG_STALE_SEC:
            print(f"[WATCHDOG] no coil writes for {now-last_coil_write_ts:.1f}s -> restarting process")
            os._exit(3)

        time.sleep(0.05 if changed_bins else 0.3)



if __name__ == "__main__":
    # Запускаем Modbus-сервер в отдельном потоке
    threading.Thread(target=run_server, daemon=True).start()

    # Простой тест вызова (однократный)
    res_check = check_last_operation_is_idle()
    print("check:", res_check)
    # Основной цикл
    modbus_cycle()
