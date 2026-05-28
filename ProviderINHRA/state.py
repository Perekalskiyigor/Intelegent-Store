# state.py
# файл хранилища состояния ячеек. Он держит в памяти состояние:
# светодиодов по каждой ячейке
# датчиков/герконов по каждой ячейке
# мета-информацию: сколько ячеек, когда стартовали, когда был последний опрос
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
import time
import threading
import logging

logger = logging.getLogger(__name__)
logger.info(f" STATE Инициализация структуры")

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
    auto_off_ts: Optional[float] = None  # когда автоматически выключиться (timestamp)
    original_color: int = 0  # сохранение оригинального цвета для восстановления
    original_mode: int = 0   # сохранение оригинального режима


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
    logger.info(f" STATE Инициализация структуры")
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
        self._led_timers: Dict[int, threading.Timer] = {}  # <-- ДОБАВИТЬ
        self._shutdown_event = threading.Event()  # <-- ДОБАВИТЬ

    def bins_count(self) -> int:
        return self._state["meta"]["bins_count"]
    
    def shutdown(self) -> None:
        """Останавливает все таймеры при завершении программы"""
        self._shutdown_event.set()
        with self._lock:
            for bin_no, timer in self._led_timers.items():
                if timer and timer.is_alive():
                    timer.cancel()
            self._led_timers.clear()
        logger.info("[STATE] All LED timers cancelled")

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
    def set_led(self, bin_no: int, color: int, mode: int, source: str = "api") -> None:
        """
        Установить LED без авто-выключения
        """
        self.set_led_with_timeout(bin_no, color, mode, 0, source)

    def set_led_with_timeout(self, bin_no: int, color: int, mode: int, duration_sec: int, source: str = "api") -> None:
        """
        Установить LED с автоматическим выключением через duration_sec секунд.
        Если duration_sec <= 0, то без авто-выключения.
        """
        with self._lock:
            self._ensure_bin(bin_no)
            led: LedState = self._state["bins"][bin_no]["led"]
            
            # Сохраняем оригинальные значения
            led.original_color = int(color)
            led.original_mode = int(mode)
            
            # Если есть активный таймер - отменяем его
            self._cancel_timer_locked(bin_no)
            
            # Устанавливаем новые значения
            led.color = int(color)
            led.mode = int(mode)
            led.desired_ts = now_ts()
            led.dirty = True
            led.source = source
            
            # Если нужен авто-отключение
            if duration_sec > 0:
                auto_off_ts = now_ts() + duration_sec
                led.auto_off_ts = auto_off_ts
                
                # Создаем таймер для выключения
                timer = threading.Timer(duration_sec, self._turn_off_led, args=[bin_no])
                self._led_timers[bin_no] = timer
                timer.start()
                
                logger.info(f"[STATE] LED set with timeout: bin={bin_no}, color={color}, "
                          f"mode={mode}, duration={duration_sec}s, source={source}")
            else:
                led.auto_off_ts = None
                logger.info(f"[STATE] LED set: bin={bin_no}, color={color}, mode={mode}, source={source}")

    def _turn_off_led(self, bin_no: int) -> None:
        """Выключает LED (устанавливает mode=0, color=0)"""
        if self._shutdown_event.is_set():
            return
            
        try:
            with self._lock:
                self._ensure_bin(bin_no)
                led: LedState = self._state["bins"][bin_no]["led"]
                
                # Проверяем, не был ли LED уже изменен после установки таймера
                # Если цвет или режим отличаются от сохраненных оригинальных, значит команда была перезаписана
                current_color = led.color
                current_mode = led.mode
                
                if current_color == led.original_color and current_mode == led.original_mode:
                    # Выключаем LED
                    led.color = 0
                    led.mode = 0
                    led.desired_ts = now_ts()
                    led.dirty = True
                    led.source = "auto_off"
                    led.auto_off_ts = None
                    led.original_color = 0
                    led.original_mode = 0
                    
                    logger.info(f"[STATE] LED auto-off: bin={bin_no}")
                else:
                    logger.info(f"[STATE] LED auto-off skipped for bin={bin_no}: "
                              f"state changed from original ({led.original_color},{led.original_mode}) "
                              f"to ({current_color},{current_mode})")
            
            # Очищаем таймер из словаря
            with self._lock:
                if bin_no in self._led_timers:
                    del self._led_timers[bin_no]
                    
        except Exception as e:
            logger.error(f"[STATE] Error turning off LED for bin={bin_no}: {e}")

    def _cancel_timer_locked(self, bin_no: int) -> None:
        """Отменяет таймер для ячейки (вызывается с блокировкой)"""
        if bin_no in self._led_timers:
            timer = self._led_timers[bin_no]
            if timer and timer.is_alive():
                timer.cancel()
            del self._led_timers[bin_no]
            
            # Сбрасываем auto_off_ts в LED состоянии
            if bin_no in self._state["bins"]:
                led: LedState = self._state["bins"][bin_no]["led"]
                led.auto_off_ts = None

    def cancel_led_timer(self, bin_no: int) -> bool:
        """
        Отменяет автоматическое выключение LED для ячейки.
        Возвращает True, если таймер существовал и был отменен.
        """
        with self._lock:
            self._ensure_bin(bin_no)
            if bin_no in self._led_timers:
                self._cancel_timer_locked(bin_no)
                logger.info(f"[STATE] LED timer cancelled for bin={bin_no}")
                return True
            return False

    def get_remaining_time(self, bin_no: int) -> float:
        """
        Возвращает оставшееся время до автоматического выключения LED в секундах.
        Возвращает 0, если таймера нет или время вышло.
        """
        with self._lock:
            self._ensure_bin(bin_no)
            led: LedState = self._state["bins"][bin_no]["led"]
            if led.auto_off_ts:
                remaining = led.auto_off_ts - now_ts()
                return max(0.0, remaining)
            return 0.0

    def mark_led_applied(self, bin_no: int) -> None:
        """
        Вызывать после успешной записи в Modbus.
        Worker вызывает после успешной записи в Modbus. dirty = False отмечаем как отправленное
        """
        with self._lock:
            self._ensure_bin(bin_no)
            led: LedState = self._state["bins"][bin_no]["led"]
            led.applied_ts = now_ts()
            led.dirty = False
        logger.info(f"[STATE] LED applied: bin={bin_no}")

    def get_dirty_leds(self) -> Dict[int, Dict[str, int]]:
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