import threading
from pymodbus.server import StartTcpServer
from pymodbus.datastore import (
    ModbusSlaveContext,
    ModbusServerContext,
    ModbusSequentialDataBlock,
)

from config import MODBUS_HOST, MODBUS_PORT, MODBUS_UNIT

MODBUS_LOCK = threading.RLock()

HR_START = 0
HR_SIZE = 1000
COIL_SIZE = 2000

store = ModbusSlaveContext(
    co=ModbusSequentialDataBlock(0, [0] * COIL_SIZE),
    hr=ModbusSequentialDataBlock(HR_START, [0] * HR_SIZE),
)

context = ModbusServerContext(slaves={MODBUS_UNIT: store}, single=False)


def run_modbus_server() -> None:
    print(f"[Modbus] START {MODBUS_HOST}:{MODBUS_PORT} unit={MODBUS_UNIT}")
    StartTcpServer(context, address=(MODBUS_HOST, MODBUS_PORT))


def set_hr_values(address: int, values: list[int]) -> None:
    with MODBUS_LOCK:
        context[MODBUS_UNIT].setValues(3, address, values)


def get_hr_values(address: int, count: int = 1) -> list[int]:
    with MODBUS_LOCK:
        return context[MODBUS_UNIT].getValues(3, address, count)


def set_coil_value(address: int, value: int) -> None:
    with MODBUS_LOCK:
        context[MODBUS_UNIT].setValues(1, address, [1 if value else 0])


def get_coil_value(address: int) -> int:
    with MODBUS_LOCK:
        return context[MODBUS_UNIT].getValues(1, address, 1)[0]