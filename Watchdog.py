# watchdog.py
# pyinstaller --onefile watchdog.py

import time
import subprocess
from pymodbus.client import ModbusTcpClient

PROVIDER_EXE = r"E:\DEV\Intelegent-Store\dist\ModbusProvider.exe"

HOST = "127.0.0.1"
PORT = 1502
UNIT = 2

CONNECT_TIMEOUT = 2
POLL_SEC = 3

HB_MAGIC_R0 = 100

PROVIDER_READY_TIMEOUT = 40

# рестарт по сети: если подряд N раз нет нормального ответа
FAILS_TO_RESTART = 5

# рестарт по “зависанию”: если HR1 не менялся N секунд (при этом сеть отвечает)
PROVIDER_FREEZE_TIMEOUT = 20


def _read_hr0_3():
    c = None
    try:
        c = ModbusTcpClient(HOST, port=PORT, timeout=CONNECT_TIMEOUT)
        if not c.connect():
            return None, False

        rr = c.read_holding_registers(0, 4, slave=UNIT)
        if not rr or rr.isError() or not getattr(rr, "registers", None) or len(rr.registers) < 4:
            return None, True

        return rr.registers[:4], True
    except Exception:
        return None, False
    finally:
        try:
            if c:
                c.close()
        except Exception:
            pass


def start_provider():
    p = subprocess.Popen([PROVIDER_EXE])
    print(f"[WD] started ModbusProvider.exe (pid={p.pid})")
    return p


def stop_provider(p: subprocess.Popen):
    if not p or p.poll() is not None:
        return
    print(f"[WD] stopping ModbusProvider.exe (pid={p.pid})")
    try:
        p.terminate()
        p.wait(timeout=8)
        print("[WD] provider terminated")
        return
    except Exception:
        pass
    try:
        p.kill()
        p.wait(timeout=8)
        print("[WD] provider killed")
    except Exception:
        print("[WD] provider kill failed")


def restart_provider(p: subprocess.Popen):
    stop_provider(p)
    time.sleep(1)
    return start_provider()


def wait_provider_ready(p: subprocess.Popen) -> bool:
    t0 = time.time()

    # маленькая пауза, чтобы не ловить первый connect timeout сразу
    time.sleep(1.0)

    while True:
        if p.poll() is not None:
            print("[WD] provider exited during startup")
            return False

        regs, ok = _read_hr0_3()
        if ok and regs:
            r0, r1, r2, r3 = regs
            print(f"[WD] provider ready: HR0={r0} HR1={r1} HR2={r2} HR3={r3}")
            return True

        if time.time() - t0 > PROVIDER_READY_TIMEOUT:
            print("[WD] provider not ready within timeout")
            return False

        time.sleep(1)


def main():
    p = start_provider()
    wait_provider_ready(p)

    consecutive_fails = 0

    last_r1 = None
    last_r1_change = time.time()

    while True:
        now = time.time()

        # если процесс умер — рестарт
        if p.poll() is not None:
            print("[WD] provider process not running -> restart")
            p = start_provider()
            wait_provider_ready(p)

            consecutive_fails = 0
            last_r1 = None
            last_r1_change = time.time()
            time.sleep(POLL_SEC)
            continue

        regs, transport_ok = _read_hr0_3()

        if not transport_ok or not regs:
            consecutive_fails += 1
            print(f"[WD] no modbus response ({consecutive_fails}/{FAILS_TO_RESTART})")
        else:
            consecutive_fails = 0
            r0, r1, plc_ok, plc_dt = regs

            if r0 != HB_MAGIC_R0:
                print(f"[WD] bad HR0={r0} (expected {HB_MAGIC_R0})")

            # freeze контроль
            if last_r1 is None or r1 != last_r1:
                last_r1 = r1
                last_r1_change = now
                # можно реже логировать, но пусть будет:
                print(f"[WD] provider hb(HR1)={r1}")

            # PLC диагностика из HR2/HR3
            if plc_ok == 0:
                print(f"[WD] PLC LINK LOST: dt={plc_dt}s (no restart)")

        # рестарт если подряд слишком много фейлов
        if consecutive_fails >= FAILS_TO_RESTART:
            print("[WD] too many consecutive failures -> restart provider")
            p = restart_provider(p)
            wait_provider_ready(p)

            consecutive_fails = 0
            last_r1 = None
            last_r1_change = time.time()
            time.sleep(POLL_SEC)
            continue

        # рестарт если сеть ОК, но HR1 “застыл”
        if consecutive_fails == 0 and (now - last_r1_change) > PROVIDER_FREEZE_TIMEOUT:
            print("[WD] provider freeze (HR1 not changing) -> restart provider")
            p = restart_provider(p)
            wait_provider_ready(p)

            consecutive_fails = 0
            last_r1 = None
            last_r1_change = time.time()
            time.sleep(POLL_SEC)
            continue

        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
