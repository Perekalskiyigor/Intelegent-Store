import time
import threading
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext, ModbusSequentialDataBlock

HOST = "0.0.0.0"
PORT = 1502
UNIT = 2

# --- Инициализация хранилища ---
store = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0]*100))
context = ModbusServerContext(slaves={UNIT: store}, single=False)

# --- Поток Modbus-сервера ---
def run_server():
    print(f"[Modbus] SLAVE запущен на {HOST}:{PORT} (Unit={UNIT})")
    StartTcpServer(context, address=(HOST, PORT))

# --- Главный цикл: пишет 0,1 и читает 2,3 ---
def modbus_cycle():
    counter = 0
    while True:
        counter += 1
        val0 = 100                # фиксированное значение
        val1 = counter            # счётчик, каждую секунду растёт

        # Пишем в регистры 0 и 1
        context[UNIT].setValues(3, 0, [val0, val1])

        # Читаем регистры 2 и 3 (которые может писать ПЛК)
        read_vals = context[UNIT].getValues(3, 2, 2)
        val2, val3 = read_vals[0], read_vals[1]

        print(f"[WRITE] R0={val0} R1={val1}   [READ] R2={val2} R3={val3}")
        time.sleep(1)

# --- Запуск ---
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    modbus_cycle()
