import time
import threading
import logging
from dataclasses import dataclass, asdict
from typing import Optional

from modbus_server import get_hr_values

logger = logging.getLogger(__name__)


REG_CNT_ERROR1 = 4000
REG_CNT_ERROR2 = 4002
REG_CNT_ERROR3 = 4004
REG_CNT_ERROR4 = 4006
REG_CNT_ERROR5 = 4008
REG_CNT_ERROR6 = 4010
REG_CNT_ERROR7 = 4012
REG_CNT_ERROR8 = 4014

REG_SW_VERSION = 4016
REG_HW_VERSION = 4018


REG_I2C_ERROR = 4020

REG_F_ERR1 = 4022
REG_F_ERR2 = 4024
REG_F_ERR3 = 4026
REG_F_ERR4 = 4028
REG_F_ERR5 = 4030
REG_F_ERR6 = 4032
REG_F_ERR7 = 4034
REG_F_ERR8 = 4036


def read_dword(address: int) -> int:
    regs = get_hr_values(address, 2)

    if len(regs) < 2:
        raise RuntimeError(f"Не удалось прочитать DWORD address={address}")

    lo = int(regs[0]) & 0xFFFF
    hi = int(regs[1]) & 0xFFFF

    return lo | (hi << 16)


@dataclass(frozen=True)
class McuDiagState:
    cnt_error1: int
    cnt_error2: int
    cnt_error3: int
    cnt_error4: int
    cnt_error5: int
    cnt_error6: int
    cnt_error7: int
    cnt_error8: int

    sw_version: int
    hw_version: int
    i2c_error: int

    f_err1: int
    f_err2: int
    f_err3: int
    f_err4: int
    f_err5: int
    f_err6: int
    f_err7: int
    f_err8: int


def read_mcu_diag_state() -> McuDiagState:
    return McuDiagState(
        cnt_error1=read_dword(REG_CNT_ERROR1),
        cnt_error2=read_dword(REG_CNT_ERROR2),
        cnt_error3=read_dword(REG_CNT_ERROR3),
        cnt_error4=read_dword(REG_CNT_ERROR4),
        cnt_error5=read_dword(REG_CNT_ERROR5),
        cnt_error6=read_dword(REG_CNT_ERROR6),
        cnt_error7=read_dword(REG_CNT_ERROR7),
        cnt_error8=read_dword(REG_CNT_ERROR8),

        sw_version=read_dword(REG_SW_VERSION),
        hw_version=read_dword(REG_HW_VERSION),
        i2c_error=read_dword(REG_I2C_ERROR),

        f_err1=read_dword(REG_F_ERR1),
        f_err2=read_dword(REG_F_ERR2),
        f_err3=read_dword(REG_F_ERR3),
        f_err4=read_dword(REG_F_ERR4),
        f_err5=read_dword(REG_F_ERR5),
        f_err6=read_dword(REG_F_ERR6),
        f_err7=read_dword(REG_F_ERR7),
        f_err8=read_dword(REG_F_ERR8),
    )


def start_mcu_diag_monitor(db, poll_sec: float = 1.0) -> threading.Thread:
    def worker():
        last_state: Optional[McuDiagState] = None

        logger.info("MCU_DIAG monitor started")

        while True:
            try:
                state = read_mcu_diag_state()

                if state != last_state:
                    db.log_mcu_state(asdict(state))
                    last_state = state
                    logger.info("MCU_DIAG state changed, saved to DB")

            except Exception as e:
                logger.exception(f"MCU_DIAG error={e}")

            time.sleep(poll_sec)

    thread = threading.Thread(
        target=worker,
        daemon=True,
    )
    thread.start()
    return thread