import time
from typing import Dict
import logging
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
logger.info(f" WORKER Инициализация сструктуры")


import requests
from config import (
    POLL_SENSORS_SEC,
    LOOP_SLEEP_SEC,
    DEFAULT_BINS_COUNT,
    ROW_WIDTH,
    BASE_ADDR,
    SENSOR_COIL_BASE,
)
from state import StateStore, QUALITY_OK, QUALITY_ERROR
from db import Database
from modbus_server import set_hr_values, get_coil_value


def push_sensor_change(bin_no: int, value: bool, quality: str = "OK") -> None:
    url = "https://1c-element-test.prosyst.ru/applications/inhra-dev/api/get_event/"

    payload = {
        "bin_no": int(bin_no),
        "value": bool(value),
        "quality": str(quality),
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=2,
            verify=False,  # временно, для тестового сервера с self-signed SSL
        )
        resp.raise_for_status()

        logger.info(
            f"WORKER [PUSH OK] bin={bin_no} value={value} status={resp.status_code}"
        )

    except Exception as e:
        logger.exception(
            f"WORKER [PUSH ERROR] bin={bin_no} value={value} error={e}"
        )


class ModbusLocalWrapper:
    @staticmethod
    def calc_led_start_addr(bin_no: int) -> int:
        if bin_no < 1:
            raise ValueError(f"Invalid bin_no={bin_no}")
        return BASE_ADDR + (bin_no - 1) * ROW_WIDTH

    def write_modbus_led(self, bin_no: int, color: int, mode: int) -> None:
        start_addr = self.calc_led_start_addr(bin_no)

        values = [
            int(mode),   # Python_in_1[0] LedMode
            int(color),  # Python_in_1[1] Color
            0,           # Python_in_1[2] MSUColor1
            0,           # Python_in_1[3] MSUColor2
            0,           # Python_in_1[4] Reserve
        ]

        set_hr_values(start_addr, values)

    def read_sensor_modbus(self, bin_no: int) -> bool:
        if bin_no < 1:
            raise ValueError(f"Invalid bin_no={bin_no}")

        coil_addr = SENSOR_COIL_BASE + (bin_no - 1)
        value = get_coil_value(coil_addr)
        return bool(value)


def modbus_worker_loop(
    store: StateStore,
    db: Database,
    modbus: ModbusLocalWrapper,
    bins_count: int = DEFAULT_BINS_COUNT,
) -> None:
    next_sensors_poll = time.time()

    while True:
        loop_start = time.time()

        dirty: Dict[int, Dict[str, int]] = store.get_dirty_leds()

        for bin_no, cmd in dirty.items():
            color = cmd["color"]
            mode = cmd["mode"]

            try:
                modbus.write_modbus_led(bin_no, color, mode)
                store.mark_led_applied(bin_no)
                db.log_led(bin_no, color, mode, status="OK")
                logger.info(f" WORKER [LED OK] Отправка ячейке bin={bin_no}  color={color} mode={mode}")
                print(f"[LED OK] bin={bin_no} color={color} mode={mode}")

            except Exception as e:
                db.log_led(bin_no, color, mode, status="ERROR", error=str(e))
                print(f"[LED ERROR] bin={bin_no} color={color} mode={mode} error={e}")
                logger.exception(f" WORKER [LED] Ошибка Отправка ячейке bin={bin_no}  color={color} mode={mode}")

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
                        print(f"отправлем результат на сервер, датчик сменил состоние")
                        logger.info(f"WORKER [SENSOR] отправлем результат на сервер, датчик сменил состоние")
                        push_sensor_change(bin_no, value, quality=QUALITY_OK)
                        print(f"[SENSOR CHANGED] bin={bin_no} value={value}")
                        logger.info(f"WORKER [SENSOR] Датчик на bin={bin_no} изменил состояние value={value}")

                except Exception as e:
                    store.update_sensor(
                        bin_no=bin_no,
                        value=False,
                        quality=QUALITY_ERROR,
                    )
                    print(f"[SENSOR ERROR] bin={bin_no} error={e}")
                    logger.exception(f"WORKER [SENSOR] Ошибка изменения остояния датчика bin={bin_no} изменил состояние")

            store.set_last_poll_ts()

        elapsed = time.time() - loop_start
        sleep_for = max(0.0, LOOP_SLEEP_SEC - elapsed)
        time.sleep(sleep_for)