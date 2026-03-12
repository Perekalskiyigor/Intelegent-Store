import threading

from config import POLL_SENSORS_SEC, LOOP_SLEEP_SEC, DEFAULT_BINS_COUNT, PLC_HOST, PLC_PORT, PLC_UNIT, ROW_WIDTH, BASE_ADDR, SENSOR_COIL_BASE, FLASK_HOST,FLASK_PORT,FLASK_DEBUG
from state import StateStore
from worker import modbus_worker_loop, ModbusClientWrapper
from api import create_app
from db import Database

db = Database("ih.db")

if __name__ == "__main__":
    store = StateStore(bins_count=DEFAULT_BINS_COUNT)

    modbus = ModbusClientWrapper(
        host=PLC_HOST,
        port=PLC_PORT,
        unit=PLC_UNIT,
    )

    t = threading.Thread(
        target=modbus_worker_loop,
        args=(store, db, modbus, DEFAULT_BINS_COUNT),
        daemon=True,
    )
    t.start()

    app = create_app(store)
    app.run(
        host=FLASK_HOST,
        port=FLASK_PORT,
        debug=FLASK_DEBUG,
        use_reloader=False,
    )