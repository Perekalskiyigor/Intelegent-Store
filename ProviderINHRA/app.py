import threading
import logging
from logger_config import setup_logging

setup_logging()

logger = logging.getLogger(__name__)


# Обертка запуска потокв для логера
def run_thread(name, target, *args):
    try:
        logger.info(f"APP [THREAD START] {name}")
        target(*args)
    except Exception as e:
        logger.exception(f"APP [THREAD CRASH] {name} error={e}")

from config import (
    DEFAULT_BINS_COUNT,
    FLASK_HOST,
    FLASK_PORT,
    FLASK_DEBUG,
)
from state import StateStore
from worker import modbus_worker_loop, ModbusLocalWrapper
from api import create_app
from db import Database
from modbus_server import run_modbus_server



if __name__ == "__main__":
    logger.info("=== STARTING INHRA SYSTEM ===")
    
    try:
        db = Database("ih.db")
        logger.info("APP Database initialized")
    except Exception as e:
        logger.exception(f"APP [DB ERROR] error={e}")
        raise

    store = StateStore(bins_count=DEFAULT_BINS_COUNT)

    modbus = ModbusLocalWrapper()

    modbus_thread = threading.Thread(
        target=run_thread,
        args=("MODBUS_SERVER", run_modbus_server),
        daemon=True,
        )
    modbus_thread.start()
    logger.info("APP Modbus server thread started")

    worker_thread = threading.Thread(
        target=run_thread,
        args=("MODBUS_WORKER", modbus_worker_loop, store, db, modbus, DEFAULT_BINS_COUNT),
        daemon=True,
    )
    worker_thread.start()

    logger.info("APP Worker thread started")

    logger.info(f"APP Starting Flask API on {FLASK_HOST}:{FLASK_PORT}")
    try:
        app = create_app(store)
        app.run(
            host=FLASK_HOST,
            port=FLASK_PORT,
            debug=FLASK_DEBUG,
            use_reloader=False,
        )
    except Exception as e:
        logger.exception(f"APP [FLASK CRASH] error={e}")