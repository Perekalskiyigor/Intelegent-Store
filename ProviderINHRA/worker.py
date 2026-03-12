import time
from typing import Dict

import requests
from config import POLL_SENSORS_SEC, LOOP_SLEEP_SEC, DEFAULT_BINS_COUNT, PLC_HOST, PLC_PORT, PLC_UNIT, ROW_WIDTH, BASE_ADDR, SENSOR_COIL_BASE
from state import StateStore, QUALITY_OK, QUALITY_ERROR
from db import Database
from pymodbus.client import ModbusTcpClient




# Функция пушер на сервер, когда датчик изменил состояние пушим на сервер
def push_sensor_change(bin_no: int, value: bool, quality: str = "OK") -> None:
    url = "http://127.0.0.1:8000/api/sensor-change"   # сюда вставишь свой URL

    payload = {
        "bin_no": int(bin_no),
        "value": bool(value),
        "quality": str(quality),
    }

    try:
        resp = requests.post(url, json=payload, timeout=2)
        resp.raise_for_status()
        print(f"[PUSH OK] bin={bin_no} value={value}")
    except Exception as e:
        print(f"[PUSH ERROR] bin={bin_no} value={value} error={e}")




class ModbusClientWrapper:
    def __init__(self, host: str, port: int = 502, unit: int = 1):
        self.host = host
        self.port = port
        self.unit = unit
        self.client = ModbusTcpClient(host=self.host, port=self.port)

    def connect(self) -> bool:
        return self.client.connect()

    def close(self) -> None:
        self.client.close()

    def ensure_connected(self) -> None:
        if not self.client.is_socket_open():
            ok = self.client.connect()
            if not ok:
                raise ConnectionError(f"Cannot connect to PLC {self.host}:{self.port}")

    @staticmethod
    def calc_led_start_addr(bin_no: int) -> int:
        """
        Для каждой ячейки выделено 10 holding registers.
        Первая ячейка начинается с адреса 10.

        bin 1 -> 10
        bin 2 -> 20
        bin 3 -> 30
        """
        if bin_no < 1:
            raise ValueError(f"Invalid bin_no={bin_no}")
        return 10 + (bin_no - 1) * 10

    # Метод пишет полученные значения в регистр по светодиодам
    def write_modbus_led(self, bin_no: int, color: int, mode: int) -> None:
        """
        Запись LED-параметров в holding registers PLC.

        Схема:
            Data[0] = color
            Data[1] = LedMode

        Адрес блока ячейки:
            start_addr = 10 + (bin_no - 1) * 10
        """
        self.ensure_connected()

        start_addr = self.calc_led_start_addr(bin_no)
        values = [int(color), int(mode)]

        rr = self.client.write_registers(
            address=start_addr,
            values=values,
            device_id=self.unit,
        )

        if rr.isError():
            raise RuntimeError(
                f"Modbus write error: bin={bin_no}, addr={start_addr}, values={values}"
            )
        
    # Метод читает датчики на катушках
    def read_sensor_modbus(self, bin_no: int) -> bool:
        """
        Чтение датчика из PLC по Modbus.
        Предполагаем, что датчики лежат в coils:
            coil_addr = SENSOR_COIL_BASE + (bin_no - 1)
        """
        if bin_no < 1:
            raise ValueError(f"Invalid bin_no={bin_no}")

        self.ensure_connected()

        coil_addr = SENSOR_COIL_BASE + (bin_no - 1)

        rr = self.client.read_coils(
            address=coil_addr,
            count=1,
            device_id=self.unit,
        )

        if rr.isError():
            raise RuntimeError(
                f"Modbus read error: bin={bin_no}, coil_addr={coil_addr}"
            )

        if not hasattr(rr, "bits") or not rr.bits:
            raise RuntimeError(
                f"Modbus read returned empty bits: bin={bin_no}, coil_addr={coil_addr}"
            )

        return bool(rr.bits[0])
        
    def write_sensor_history_to_db(bin_no: int, value: bool, ts: float) -> None:
        # TODO: sqlite вставка
        return
    


def modbus_worker_loop(
    store: StateStore,
    db: Database,
    modbus: ModbusClientWrapper,
    bins_count: int = DEFAULT_BINS_COUNT,
) -> None:
    """
    Основной воркер.

    Логика:
    1. Смотрим какие LED помечены dirty=True
    2. Пишем их в PLC через Modbus
    3. После успешной записи снимаем dirty
    4. Раз в POLL_SENSORS_SEC читаем датчики
    5. Если датчик изменился - обновляем state и пишем лог в БД
    """

    next_sensors_poll = time.time()

    while True:
        loop_start = time.time()

        # ------------------------------------------------------------
        # 1) Применяем dirty LED
        # ------------------------------------------------------------
        dirty: Dict[int, Dict[str, int]] = store.get_dirty_leds()

        for bin_no, cmd in dirty.items():
            color = cmd["color"]
            mode = cmd["mode"]

            try:
                modbus.write_modbus_led(bin_no, color, mode)
                store.mark_led_applied(bin_no)
                db.log_led(bin_no, color, mode, status="OK")
                print(f"[LED OK] bin={bin_no} color={color} mode={mode}")

            except Exception as e:
                db.log_led(bin_no, color, mode, status="ERROR", error=str(e))
                print(f"[LED ERROR] bin={bin_no} color={color} mode={mode} error={e}")

        # ------------------------------------------------------------
        # 2) Раз в секунду читаем датчики
        # ------------------------------------------------------------
        now = time.time()
        if now >= next_sensors_poll:
            next_sensors_poll = now + POLL_SENSORS_SEC

            for bin_no in range(1, bins_count + 1):
                try:
                    value = modbus.read_sensor_modbus(bin_no)

                    changed = store.update_sensor(
                        bin_no=bin_no,
                        value=value,
                        quality=QUALITY_OK,
                    )

                    if changed:
                        db.log_sensor(bin_no, value, quality=QUALITY_OK)
                        push_sensor_change(bin_no, value, quality=QUALITY_OK)
                        print(f"[SENSOR CHANGED] bin={bin_no} value={value}")

                except Exception as e:
                    store.update_sensor(
                        bin_no=bin_no,
                        value=False,
                        quality=QUALITY_ERROR,
                    )
                    print(f"[SENSOR ERROR] bin={bin_no} error={e}")

            store.set_last_poll_ts()

        # ------------------------------------------------------------
        # 3) Пауза, чтобы не грузить CPU
        # ------------------------------------------------------------
        elapsed = time.time() - loop_start
        sleep_for = max(0.0, LOOP_SLEEP_SEC - elapsed)
        time.sleep(sleep_for)



# if __name__ == "__main__":

#     from state import StateStore
#     from db import Database
#     from modbus_client import ModbusClientWrapper

#     # создаем тестовые объекты
#     store = StateStore(bins_count=5)
#     db = Database("test.db")
#     modbus = ModbusClientWrapper(host="127.0.0.1", port=502, unit=1)

#     # тестовая команда
#     print("TEST: set LED bin=1")

#     store.set_led(1, color=2, mode=1)

#     # запускаем воркер
#     modbus_worker_loop(store, db, modbus, bins_count=5)