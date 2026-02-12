# pyinstaller --onefile ModbusProvider.py
import sys
import os
import time
import threading
from pymodbus.server import StartTcpServer
from pymodbus.datastore import (
    ModbusSlaveContext,
    ModbusServerContext,
    ModbusSequentialDataBlock,
)
import psycopg2

# HerartBeat
HEARTBEAT_COIL = 0          # как у тебя в PLC (смещение 0)
HEARTBEAT_TIMEOUT = 12.0    # сек (при мигании 5 сек)
PLC_ALIVE_COIL = 2          # <-- ВОТ ОН: второй coil
PLC_ALIVE_INIT = 0          # стартовое значение (0 безопаснее)

RESTART_COOLDOWN = 60.0  # секунд, чтобы не уйти в цикл рестартов

MODBUS_LOCK = threading.RLock()

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

# --- Status in Modbus HR ---
STATUS_HR_ADDR = 2   # holding register #2 (0-based)
STATUS_INIT    = 0
STATUS_OK      = 1
STATUS_DEGRADED= 2
STATUS_DB_DOWN = 3
STATUS_STUCK   = 9   # self-watchdog detected hang

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
    WHERE t.bin_id = b.id
      AND (
        t.shelf_id IS DISTINCT FROM b.shelf_id OR
        t."Bin_Sensor_status" IS DISTINCT FROM COALESCE(b."Sensor", 0) OR
        t.bin_status_id IS DISTINCT FROM CASE
                                WHEN b."Sensor" = 1 AND b.ref_item_id IS NOT NULL THEN 0
                                WHEN b."Sensor" = 0 AND b.ref_item_id IS NULL     THEN 0
                                ELSE 1
                              END OR
        t."Blynk_id" IS DISTINCT FROM CASE
                                WHEN b."Sensor" = 1 AND b.ref_item_id IS NOT NULL THEN 1
                                WHEN b."Sensor" = 0 AND b.ref_item_id IS NULL     THEN 1
                                ELSE 2
                              END
      )
    RETURNING t.bin_id, t.bin_status_id, t."Blynk_id", t."Bin_Sensor_status";
    """

    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                changed = cur.fetchall()
            conn.commit()

        # Печатаем только факт изменений
        if changed:
            # changed: [(bin_id, bin_status_id, blynk_id, sensor_status), ...]
            for (bin_id, bin_status_id, blynk_id, sensor_status) in changed:
                print(f"[LED_TASK] bin={bin_id} led={bin_status_id} blink={blynk_id} sensor={sensor_status} (op_id={op_id})")

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
    co=ModbusSequentialDataBlock(0, [0] * 2000),                  # coils
    hr=ModbusSequentialDataBlock(HR_START, [0] * HR_SIZE),        # holding registers
)
context = ModbusServerContext(slaves={UNIT: store}, single=False)


def run_server_forever():
    while True:
        try:
            print(f"[Modbus] START {HOST}:{PORT} Unit={UNIT}")
            StartTcpServer(context, address=(HOST, PORT))
        except Exception as e:
            print("[Modbus SERVER CRASH]", e)
            time.sleep(1)  # пауза и старт заново


def modbus_cycle():
    # --- Кеши чтобы писать только изменения ---
    LAST_HR = {}       # bin_id_raw -> tuple(row_data)
    LAST_SENSOR = {}   # bin_id_raw -> 0/1
    counter = 0
    conn = None
    #HeartBeat
    last_hb_raw = None
    last_hb_change = time.time()
    last_restart_try = 0.


    # --- helpers ---
    def set_status_hr(code: int):
        with MODBUS_LOCK:
            context[UNIT].setValues(3, STATUS_HR_ADDR, [int(code) & 0xFFFF])


    # начальный статус в HR2
    set_status_hr(STATUS_INIT)

     # --- Self watchdog settings ---
    MAIN_TICK_TIMEOUT = 5.0  # сек: если цикл не обновлял метку дольше -> считаем завис
    last_main_tick = time.time()

    def self_watchdog():
        nonlocal last_main_tick
        while True:
            time.sleep(1.0)
            dt = time.time() - last_main_tick
            if dt > MAIN_TICK_TIMEOUT:
                try:
                    set_status_hr(STATUS_STUCK)
                    print(f"[SELF WD] main loop stuck for {dt:.1f}s -> hard exit")
                    time.sleep(0.2)
                except Exception:
                    pass
                os._exit(2)  # внешний Watchdog поднимет чисто

    threading.Thread(target=self_watchdog, daemon=True).start()
    
    with MODBUS_LOCK:
        context[UNIT].setValues(1, PLC_ALIVE_COIL, [PLC_ALIVE_INIT])

    def db_connect():
        nonlocal conn
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=2)
        conn.autocommit = False
        print("[DB] connected")

    try:
        db_connect()
    except Exception as e:
        print("[DB ERROR] initial connect:", e)
        # можно не падать: дальше в цикле попробуем переподключиться
        conn, cur = None, None

    while True:
        counter += 1

        # Технические регистры (можно тоже писать только при изменении, но это мелочь)
        val0 = 100
        val1 = counter
        with MODBUS_LOCK:
            context[UNIT].setValues(3, 0, [val0, val1])

        sensor_debug = {}
        
        # --- гарантируем, что есть подключение ---
        if conn is None:
            try:
                db_connect()
            except Exception as e:
                print("[DB ERROR] reconnect:", e)
                time.sleep(1)
                continue

        try:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '2000ms';")  # 2s на запрос
                cur.execute("SET lock_timeout = '1000ms';")       # 1s на ожидание блокировок
                cur.execute(SQL_MODBUS)
                rows = cur.fetchall()

                rows = rows[:MAX_ROWS]

                # --- обновляем Sensor + пишем в Modbus только изменения ---
                updates = []  # [(sensor_val, bin_id_raw), ...]

                with conn.cursor() as cur_upd:
                    for r in rows:
                        bin_id_raw = r[1]
                        if bin_id_raw is None:
                            continue
                        if bin_id_raw < 1 or bin_id_raw > MAX_BIN_ID:
                            continue

                        row_index = bin_id_raw - 1
                        start_addr = BASE_ADDR + row_index * ROW_WIDTH

                        bin_id = _to_int16(bin_id_raw)
                        led_color = _to_int16(r[2] if r[2] is not None else 0)
                        blink = _to_int16(r[5] if r[5] is not None else 0)

                        # 3 регистра на ячейку
                        row_data = (led_color, blink, bin_id)

                        # --- HR: пишем только если изменилось ---
                        if LAST_HR.get(bin_id_raw) != row_data:
                            with MODBUS_LOCK:
                                context[UNIT].setValues(3, start_addr, list(row_data))
                            LAST_HR[bin_id_raw] = row_data
                            # print(f"[HR] BIN={bin_id_raw} addr={start_addr} data={row_data}")

                        # --- coils -> sensor ---
                        coil_addr = COIL_BASE + (bin_id_raw - 1)
                        with MODBUS_LOCK:
                            sensor_raw = context[UNIT].getValues(1, coil_addr, 1)[0]

                        sensor_val = 1 if sensor_raw else 0
                        sensor_debug[bin_id_raw] = (sensor_raw, sensor_val)

                        # --- DB: пишем Sensor только если изменился ---
                        if LAST_SENSOR.get(bin_id_raw) != sensor_val:
                            LAST_SENSOR[bin_id_raw] = sensor_val
                            updates.append((sensor_val, bin_id_raw))
                            # print(f"[SENSOR] BIN={bin_id_raw} coil={coil_addr} RAW={sensor_raw} -> {sensor_val}")

                        # DEBUG msu_mes (по желанию)
                        # msu_mes_int = _to_int16(msu_mes)
                        # print(f"[DBG] BIN={bin_id_raw} HR+6={msu_mes_int}")

                    if updates:
                        cur_upd.executemany(SQL_UPDATE_SENSOR, updates)
                        conn.commit()
                        print(f"[DB] updated Sensors: {len(updates)}")
                    else:
                        # без commit тоже норм, но можно и не делать ничего
                        pass

        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            print("[DB ERROR] lost connection:", e)
            try: conn.close()
            except Exception: pass
            conn = None
            time.sleep(0.5)
            continue

        except Exception as e:
            print("[DB ERROR] query:", e)
            try:
                conn.rollback()
            except Exception:
                try: conn.close()
                except Exception: pass
                conn = None


        # Печать массива сенсоров (как было)
        bits = []
        for bid in range(1, MAX_BIN_ID + 1):
            if bid in sensor_debug:
                bits.append(str(sensor_debug[bid][1]))
            else:
                # если PLC не писал coil или строка не пришла из led_task
                bits.append(str(LAST_SENSOR.get(bid, 0)))
        #print(f"[SENSORS] [{' '.join(bits)}]")

        # Обновляем IH_led_task (лучше тоже сделать "только изменения" через WHERE IS DISTINCT FROM, но пока оставляем)
        update_task_color_by_sensor_if_idle()

        # Тех регистры
        with MODBUS_LOCK:
            val2, val3 = context[UNIT].getValues(3, 0, 2)
        # print(f"[WRITE] R0={val0} R1={val1}   [READ] R0={val2} R1={val3}")

        # --- WATCHDOG PLC -> Python (heartbeat coil) ---
        now = time.time()
        with MODBUS_LOCK:
            hb_raw = context[UNIT].getValues(1, HEARTBEAT_COIL, 1)[0]

        if last_hb_raw is None or hb_raw != last_hb_raw:
            last_hb_raw = hb_raw
            last_hb_change = now
            print(f"[HB] coil{HEARTBEAT_COIL}={hb_raw}")

        dt = now - last_hb_change
        hb_lost = dt > HEARTBEAT_TIMEOUT
        if hb_lost:
            print(f"[HB LOST] no heartbeat change for {dt:.1f}s -> DEGRADED mode")

            # сигнал PLC что провайдер "не уверен"
            with MODBUS_LOCK:
                context[UNIT].setValues(1, PLC_ALIVE_COIL, [0])

            set_status_hr(STATUS_DEGRADED)

            # раз в cooldown делаем мягкий ресет состояния
            if now - last_restart_try > RESTART_COOLDOWN:
                last_restart_try = now
                LAST_HR.clear()
                LAST_SENSOR.clear()
                print("[SOFT RESET] caches cleared")

                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
                conn = None
        else:
            # HB есть -> говорим PLC что всё ок
            with MODBUS_LOCK:
                context[UNIT].setValues(1, PLC_ALIVE_COIL, [1])

            # если БД сейчас не подключена — отдельный статус
            if conn is None:
                set_status_hr(STATUS_DB_DOWN)
            else:
                set_status_hr(STATUS_OK)



        # --- main loop tick for self-watchdog ---
        last_main_tick = time.time()

        time.sleep(0.3)


if __name__ == "__main__":
    # Запускаем Modbus-сервер в отдельном потоке
    threading.Thread(target=run_server_forever, daemon=False).start()

    # Простой тест вызова (однократный)
    res_check = check_last_operation_is_idle()
    print("check:", res_check)
    # Основной цикл
    modbus_cycle()