# scaner.py

import keyboard
from threading import Event
from typing import Optional

_buffer = []
_event = Event()
_last_code: Optional[str] = None
_hook = None

def _on_event(e):
    global _buffer, _last_code
    if e.event_type != "down":
        return

    name = e.name

    # конец ввода
    if name in ("enter", "return"):
        if _buffer:
            _last_code = "".join(_buffer)
            _buffer.clear()
            _event.set()
        return

    # добавляем только печатные клавиши
    if len(name) == 1:
        _buffer.append(name)


def start():
    global _hook
    if _hook is None:
        _hook = keyboard.hook(_on_event)


def stop():
    global _hook
    if _hook is not None:
        keyboard.unhook(_on_event)
        _hook = None


def wait_next(timeout: Optional[float] = None) -> Optional[str]:
    """
    Ждёт следующий штрихкод и возвращает его строкой.
    Если timeout == None — ждёт БЕСКОНЕЧНО, пока не будет скана.
    """
    _event.clear()
    ok = _event.wait(timeout)  # если timeout None — ждёт бесконечно
    if not ok:
        return None
    return _last_code