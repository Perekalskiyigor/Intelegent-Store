# pyinstaller --onefile ModbusProvider.py

import time
import threading
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext, ModbusSequentialDataBlock
import psycopg2
from psycopg2.extras import DictCursor

# Конфигурация хоста мадбас
HOST = "0.0.0.0"
PORT = 1502
UNIT = 2

ID_TASK=0


# Конфигурация базы данных
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432
}


#######################################START - Запрос на последнюю операци###############################
def check_last_operation_is_idle():
    """
    Автономная функция: сама открывает соединение по DB_CONFIG.
    SELECT ... FROM public."IH_Operation" ORDER BY id DESC LIMIT 1

    Возвращает кортеж:
        (True,  op_id, workstation_id)  — если последняя операция есть, status=='IDLE' и finished_at IS NULL
        (False, op_id, workstation_id)  — если операция есть, но не соответствует условию
        (False, None, None)              — если записей нет или произошла ошибка
    """
    SQL = """
    SELECT id, status, operator, started_at, finished_at, expires_at, workstation_id, op_type
    FROM public."IH_Operation"
    ORDER BY id DESC
    LIMIT 1;
    """

    try:
        import psycopg2
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


#######################################STOP - Запрос на последнюю операци###############################




#######################################START - Обновление таблицы диодов###############################
# Вверху модуля (если ещё нет)
_last_seen_op_id = None


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

def update_led_task_if_needed():
    """
    Если последняя операция в IH_Operation имеет статус IDLE и не закрыта,
    то для КАЖДОЙ строки из IH_bin:
      - обновляем запись в IH_led_task, где bin_id = IH_bin.id
      - если такой записи нет — вставляем новую.

    Маппинг:
      IH_bin.id         -> IH_led_task.bin_id
      IH_bin.shelf_id   -> IH_led_task.shelf_id
      IH_bin.mode_id    -> IH_led_task.bin_status_id
      IH_bin.mode_blynk -> IH_led_task."Blynk_id"
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

    # Операция IDLE, но мы её уже обрабатывали
    if _last_seen_op_id == op_id:
        print(f"[OP] Операция {op_id} уже обработана ранее. Пропускаем.")
        return False, op_id

    # Новая IDLE-операция -> подтягиваем бины и обновляем IH_led_task
    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(SQL_BINS_ALL)
                bins = cur.fetchall()

            if not bins:
                print("[OP] В IH_bin нет строк, обновлять нечего.")
                _last_seen_op_id = op_id
                return False, op_id

            with conn.cursor() as cur2:
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

                    # UPDATE по bin_id
                    update_sql = """
                    UPDATE public."IH_led_task"
                    SET
                        shelf_id      = %s,
                        bin_status_id = %s,
                        "Blynk_id"    = %s
                    WHERE bin_id = %s;
                    """
                    cur2.execute(
                        update_sql,
                        (
                            shelf_id,
                            mode_id,       # -> bin_status_id
                            mode_blynk,    # -> Blynk_id
                            bin_id,
                        ),
                    )

                    # Если строки не было — вставляем
                    if cur2.rowcount == 0:
                        insert_sql = """
                        INSERT INTO public."IH_led_task"
                            (bin_id,
                             shelf_id,
                             bin_status_id,
                             "Blynk_id")
                        VALUES (%s, %s, %s, %s);
                        """
                        cur2.execute(
                            insert_sql,
                            (
                                bin_id,
                                shelf_id,
                                mode_id,
                                mode_blynk,
                            ),
                        )

        _last_seen_op_id = op_id
        print(f"[OP] IH_led_task обновлена для операции {op_id} (processed {len(bins)} bins).")
        return True, op_id

    except Exception as e:
        print("[DB ERROR] update_led_task_if_needed:", e)
        return False, op_id



#######################################STOP - Обновление таблицы диодов###############################


# Запрос к бд на выборку данных
SQL = """
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
HR_SIZE  = 1000            # Дадим большой запас, чтобы не ловить 131/2 из-за выхода за границы
ROW_WIDTH = 10             # 10 регистров на строку
BASE_ADDR = 10             # с 10-го адреса кладём строки (0-based)
MAX_ROWS  = (HR_SIZE - BASE_ADDR) // ROW_WIDTH

# Конвертация значения для мадбаса
def _to_int16(v):
    try:
        return int(v) & 0xFFFF
    except Exception:
        return 0




###################### --- Хранилище Modbus ---#############################################
store = ModbusSlaveContext(
    hr=ModbusSequentialDataBlock(HR_START, [0] * HR_SIZE)
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

        try:
            # Опрос БД
            with psycopg2.connect(**DB_CONFIG) as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL)
                    rows = cur.fetchall()

            # Ограничим количеством ячеек, которое можем поместить
            rows = rows[:MAX_ROWS]

            # Очистим рабочую зону (все блоки с 10-го регистра и до конца)
            context[UNIT].setValues(3, BASE_ADDR, [0] * (HR_SIZE - BASE_ADDR))

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

                # работаем только с ячейками 1..10
                if bin_id_raw < 1 or bin_id_raw > 11:
                    continue

                # Адрес блока для КОНКРЕТНОЙ ячейки:
                # bin_id=1  -> 10..19
                # bin_id=2  -> 20..29
                # ...
                row_index  = bin_id_raw - 1
                start_addr = BASE_ADDR + row_index * ROW_WIDTH  # BASE_ADDR=10, ROW_WIDTH=10

                bin_id    = _to_int16(bin_id_raw)
                led_color = _to_int16(r[2] if r[2] is not None else 0)  # bin_status_id
                blink     = _to_int16(r[5] if r[5] is not None else 0)  # Blynk_id
                shelf_id  = _to_int16(r[4] if r[4] is not None else 0)

                # Схема (10 регистров на ячейку):
                # +0 BIN_ID
                # +1 LED_COLOR (bin_status_id)
                # +2 BLINK ("Blynk_id")
                # +3 SHELF_ID
                # +4..+9 — резерв
                row_data = [
                    led_color,
                    blink,
                    bin_id,
                ]

                # Записываем данные ячейки в её блок
                context[UNIT].setValues(3, start_addr, row_data)

                # DEBUG: вывод адресов и данных
                print(
                    f"[WRITE] bin_id={bin_id}  "
                    f"addr={start_addr}-{start_addr+len(row_data)-1}  "
                    f"data={row_data}"
                )

                # MSU_mes читаем из +6 той же ячейки (если ПЛК туда пишет)
                msu_mes = context[UNIT].getValues(3, start_addr + 6, 1)[0]

                print(
                    f"[INFO] BIN={bin_id} LED={led_color} BLINK={blink} MSU_mes={msu_mes}"
                )
        except Exception as e:
            print("[DB ERROR]", e)

        # Отладка тех. регистров
        val2, val3 = context[UNIT].getValues(3, 0, 2)
        print(f"[WRITE] R0={val0} R1={val1}   [READ] R0={val2} R1={val3}")

        time.sleep(3)

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    # простой тест вызова (однократный)
    res_check = check_last_operation_is_idle()
    print("check:", res_check)
    res2 = update_led_task_if_needed()
    print(res2)
    modbus_cycle()

    # # попытка обновления (если нужно)
    # updated, opid = update_led_task_if_needed()
    # print("update_called:", updated, "opid:", opid)
    # modbus_cycle()