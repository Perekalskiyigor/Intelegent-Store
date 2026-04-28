# state.py
# файл хранилища состояния ячеек. Он держит в памяти состояние:
# светодиодов по каждой ячейке
# датчиков/герконов по каждой ячейке
# мета-информацию: сколько ячеек, когда стартовали, когда был последний опрос
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any
import time
import threading
import logging
logger = logging.getLogger(__name__)
logger.info(f" STATE Инициализация сструктуры")


# -----------------------------
# Константы (качество данных)
# -----------------------------
QUALITY_OK = "OK"
QUALITY_STALE = "STALE"
QUALITY_ERROR = "ERROR"


def now_ts() -> float:
    return time.time()


# -----------------------------
# Dataclasses: LED / Sensor
# -----------------------------
@dataclass
class LedState:
    bin: int
    color: int = 0          # 0 = выкл (например)
    mode: int = 0           # blynk mode / режим
    desired_ts: float = 0.0 # когда запросили (API/логика)
    applied_ts: float = 0.0 # когда реально применили в modbus
    dirty: bool = False     # нужно отправить в modbus
    source: str = "init"    # api/logic/init


@dataclass
class SensorState:
    bin: int
    value: bool = False
    ts: float = 0.0         # когда прочитали (последний опрос)
    changed_ts: float = 0.0 # когда поменялось
    quality: str = QUALITY_STALE


# -----------------------------
# Инициализация state
# -----------------------------
def init_state(bins_count: int) -> Dict[str, Any]:
    logger.info(f" STATE Инициализация сструктуры")
    """
    Создаёт структуру state:
      state["meta"]
      state["bins"][bin_no]["led"]    -> LedState
      state["bins"][bin_no]["sensor"] -> SensorState
    """
    bins: Dict[int, Dict[str, Any]] = {}
    t = now_ts()

    for i in range(1, bins_count + 1):
        bins[i] = {
            "led": LedState(bin=i, desired_ts=t, applied_ts=0.0, dirty=False, source="init"),
            "sensor": SensorState(bin=i, value=False, ts=0.0, changed_ts=0.0, quality=QUALITY_STALE),
        }

    return {
        "meta": {
            "bins_count": bins_count,
            "started_ts": t,
            "last_poll_ts": 0.0,
        },
        "bins": bins,
    }


# -----------------------------
# Хранилище состояния (thread-safe)
# -----------------------------
class StateStore:
    """
    Потокобезопасный доступ к state.

    - API/логика меняют desired LED -> dirty=True
    - Worker после успешной записи -> mark_led_applied() (dirty=False)
    - Worker обновляет датчики -> update_sensor() (+changed True/False)
    """
    def __init__(self, bins_count: int):
        self._lock = threading.RLock()
        self._state = init_state(bins_count)

    def bins_count(self) -> int:
        return self._state["meta"]["bins_count"]

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Возвращает snapshot состояния в виде обычных dict,
        чтобы легко сериализовать в JSON (Flask).
        """
        with self._lock:
            out_bins: Dict[int, Dict[str, Any]] = {}
            for b, d in self._state["bins"].items():
                out_bins[b] = {
                    "led": asdict(d["led"]),
                    "sensor": asdict(d["sensor"]),
                }
            return {"meta": dict(self._state["meta"]), "bins": out_bins}

    # -------------------------
    # LED (desired -> dirty)
    # -------------------------
    # вызывает это, когда надо поменять светодиод.Внутри ставится: dirty = True То есть команда не применена в модбас.
    def set_led(self, bin_no: int, color: int, mode: int, source: str = "api") -> None:
        with self._lock:
            self._ensure_bin(bin_no)
            led: LedState = self._state["bins"][bin_no]["led"]
            led.color = int(color)
            led.mode = int(mode)
            led.desired_ts = now_ts()
            led.dirty = True
            led.source = source
        logger.info(f"[STATE] LED desired: bin={bin_no}, color={color}, mode={mode}, source={source}")

    def mark_led_applied(self, bin_no: int) -> None:
        """
        Вызывать после успешной записи в Modbus.
        Worker вызывает после успешной записи в Modbus.  dirty = False отмечаем как отправленное
        """
        with self._lock:
            self._ensure_bin(bin_no)
            led: LedState = self._state["bins"][bin_no]["led"]
            led.applied_ts = now_ts()
            led.dirty = False
        logger.info(f"[STATE] LED applied: bin={bin_no}")

    def get_dirty_leds(self) -> Dict[int, Dict[str, int]]:
        # Worker вызывает это и получает список светодиодов, которые надо записать в ПЛК.
        """
        Worker забирает список команд на запись в Modbus.
        Возвращаем минимально нужные поля.
        """
        with self._lock:
            dirty: Dict[int, Dict[str, int]] = {}
            for b, d in self._state["bins"].items():
                led: LedState = d["led"]
                if led.dirty:
                    dirty[b] = {"color": led.color, "mode": led.mode}
            return dirty

    # -------------------------
    # Sensors
    # -------------------------
    def update_sensor(self, bin_no: int, value: bool, quality: str = QUALITY_OK) -> bool:
        """
        Worker вызывает после чтения датчика.
        Обновляет датчик.
        Возвращает True, если значение изменилось.
        """
        with self._lock:
            self._ensure_bin(bin_no)
            s: SensorState = self._state["bins"][bin_no]["sensor"]
            t = now_ts()

            old_value = s.value
            new_value = bool(value)

            changed = (new_value != old_value)

            s.ts = t
            s.quality = quality

            if changed:
                s.value = new_value
                s.changed_ts = t

        if changed:
            logger.info(
                f"[STATE] Sensor changed: bin={bin_no}, old={old_value}, new={new_value}, quality={quality}"
            )

        return changed

    def set_last_poll_ts(self) -> None:
        with self._lock:
            self._state["meta"]["last_poll_ts"] = now_ts()

    # -------------------------
    # Internal
    # -------------------------
    def _ensure_bin(self, bin_no: int) -> None:
        if bin_no not in self._state["bins"]:
            logger.error(f"[STATE] Unknown bin_no={bin_no}. bins_count={self.bins_count()}")
            raise ValueError(f"Unknown bin_no={bin_no}. bins_count={self.bins_count()}")