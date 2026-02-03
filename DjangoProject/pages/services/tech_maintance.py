# Отбор катушки
import time
import psycopg2
from psycopg2.extras import DictCursor
from pages.services import parserXLS

import time
from pages.services import logInsert
from typing import Optional


# --- Конфигурация БД ---
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432
}

"""
Модуль: tech_maintance.py
Назначение:
    Реализация режима ТЕХНИЧЕСКОГО ОБСЛУЖИВАНИЯ (SERVICE) складской системы.

Общая схема работы:
    Операция техобслуживания запускается оператором
    (через веб-интерфейс Django или напрямую из сервиса).

    В рамках операции выполняется:
        1) принудительное закрытие всех ранее незавершённых операций;
        2) открытие новой операции типа SERVICE в IH_Operation;
        3) получение списка ячеек, помеченных как неисправные (ErrorSensor = true);
        4) перевод системы в режим непрерывного опроса всех ячеек;
        5) индикация состояния ячеек через подсветку;
        6) ручной выход оператора из режима техобслуживания;
        7) перевод системы обратно в режим IDLE.

Логика работы в режиме техобслуживания:
    Во время активного режима SERVICE выполняется циклический опрос всех ячеек IH_bin.
    По состоянию датчика Sensor выполняется управление подсветкой:

        - Sensor = 1 → зелёная индикация (bin_status_id = 3);
        - Sensor = 0 → красная индикация (bin_status_id = 1).

    Обновление подсветки выполняется атомарным UPDATE-запросом
    для всех ячеек одновременно (через IH_led_task).

    Опрос продолжается до тех пор, пока оператор вручную
    не завершит режим, введя команду:
        q + Enter

Работа с неисправными ячейками:
    Перед запуском режима опроса выполняется выборка ячеек,
    помеченных как неисправные:
        IH_bin."ErrorSensor" = TRUE

    Список используется для диагностики и анализа,
    но подсветка управляется для всех ячеек системы.

Завершение операции:
    После выхода из режима техобслуживания:
        - активная операция SERVICE считается завершённой;
        - открывается операция IDLE (op_type = 'IDLE', status = 'IDLE'),
          чтобы система вернулась в исходное безопасное состояние.

Ограничения и особенности:
    - Режим техобслуживания является ручным и операторо-зависимым.
    - В системе всегда должна существовать одна активная операция
      (SERVICE или IDLE).
    - Если операция IDLE уже активна, новая IDLE не создаётся.

Публичные функции модуля:
    - run_tech_maintance()
        Полный сценарий запуска и завершения техобслуживания.

    - open_service_operation()
        Закрывает все незавершённые операции и открывает SERVICE.

    - get_error_sensor_bin_ids()
        Возвращает список id ячеек с ErrorSensor = true.

    - tech_service_mode_all_bins_console()
        Запускает консольный режим мониторинга и подсветки ячеек.

    - open_idle_operation()
        Переводит систему обратно в режим IDLE.

Возвращаемые значения:
    Все основные функции возвращают dict с флагом ok
    и диагностической информацией (id операции, сообщения, ошибки).
"""


operator = "ivanov"
workstation_id = "WS-01"

def run_tech_maintance() -> dict:

    logInsert.ih_log("СТАРТ Операции тех обслуживания", operation="TECH", source="Тех. обслуживание", user=operator)

    logInsert.ih_log("Запуск отбора функция open_service_operation", operation="TECH", source="Тех. обслуживание", user=operator)
    res = open_service_operation(operator=operator, workstation_id=workstation_id)
    logInsert.ih_log(f"Открыта операция инвентаризации {res}", operation="TECH", source="Тех. обслуживание", user=operator)
    print(res)

    logInsert.ih_log("Запуск отбора функция get_error_sensor_bin_ids()", operation="TECH", source="Тех. обслуживание", user=operator)
    res = get_error_sensor_bin_ids()
    logInsert.ih_log(f"Получили ячейки с ошибками {res}", operation="TECH", source="Тех. обслуживание", user=operator)
    print(res)

    logInsert.ih_log("Запуск отбора функция tech_service_mode_all_bins_console(poll_interval=1.0)", operation="TECH", source="Тех. обслуживание", user=operator)
    tech_service_mode_all_bins_console(poll_interval=1.0)
    logInsert.ih_log(f"Операция опроса ячеек запущена", operation="TECH", source="Тех. обслуживание", user=operator)


    logInsert.ih_log("Запуск отбора функция open_idle_operation(operator, workstation_id)", operation="TECH", source="Тех. обслуживание", user=operator)
    res = open_idle_operation(operator, workstation_id)
    logInsert.ih_log(f"Открыта операция IDLE", operation="TECH", source="Тех. обслуживание", user=operator)
    print(res)

    
    logInsert.ih_log("ФИНИШ Операции отбора", operation="TECH", source="Тех. обслуживание", user="ivanov")
    return {"ok": True}


############СТАРТ  открываем операцию в IH_Operation################################
def open_service_operation(operator: str, workstation_id: str, op_type: str = "SERVICE") -> dict:
    """
    Режим тех.обслуживания: открываем операцию в IH_Operation

    1) Закрывает все незавершённые операции в IH_Operation (finished_at IS NULL).
    2) Открывает новую операцию типа SERVICE (тех.обслуживание).
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 1. Закрываем все незавершённые операции
            print('[DB] Закрываем все незавершённые операции в IH_Operation')
            cur.execute(
                """
                UPDATE public."IH_Operation"
                SET 
                    finished_at = NOW(),
                    status      = 'FINISHED'
                WHERE finished_at IS NULL;
                """
            )
            closed_count = cur.rowcount
            print(f"[DB] Закрыто операций: {closed_count}")

            # 2. Открываем новую операцию SERVICE (тех.обслуживание)
            print(f"[DB] Открываем новую операцию {op_type} (тех.обслуживание)")
            cur.execute(
                """
                INSERT INTO public."IH_Operation"
                    (op_type, status, operator, workstation_id, started_at, finished_at)
                VALUES
                    (%s,     %s,     %s,       %s,            NOW(),      NULL)
                RETURNING id;
                """,
                (op_type, "IN_PROGRESS", operator, workstation_id),
            )

            new_id = cur.fetchone()[0]

        conn.commit()
        msg = f"Открыта новая операция {op_type}, id={new_id}, закрыто старых: {closed_count}"
        print("[DB]", msg)
        return {
            "ok": True,
            "op_id": new_id,
            "message": msg,
            "closed_operations": closed_count,
        }

    except Exception as e:
        if conn is not None:
            conn.rollback()
        msg = f"Ошибка при открытии операции {op_type}: {e}"
        print("[ERROR]", msg)
        return {"ok": False, "op_id": None, "message": msg}

    finally:
        if conn is not None:
            conn.close()


############СТОП открываем операцию в IH_Operation ################################




############СТАРТ Возвращает список id ячеек, помеченных как неисправные ################################
def get_error_sensor_bin_ids() -> dict:
    """
    Возвращает список id ячеек,
    помеченных как неисправные (IH_bin."ErrorSensor" = TRUE)
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True

        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                """
                SELECT id
                FROM public."IH_bin"
                WHERE COALESCE("ErrorSensor", false) = true
                ORDER BY id;
                """
            )
            rows = cur.fetchall()

        bin_ids = [r["id"] for r in rows]

        return {
            "ok": True,
            "count": len(bin_ids),
            "bin_ids": bin_ids,
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "count": 0,
            "bin_ids": [],
        }

    finally:
        if conn:
            conn.close()

############СТОП  Возвращает список id ячеек, помеченных как неисправные################################





############СТАРТ по списку неисправных bin_id выставляет подсветку ################################
import threading

def tech_service_mode_all_bins_console(poll_interval: float = 0.5) -> dict:
    """
    Режим тех.обслуживания (консольный), мониторим ВСЕ ячейки.

    - Sensor=1 -> зелёный (bin_status_id=3)
    - Sensor=0 -> красный  (bin_status_id=1)
    - Один UPDATE (атомарно)
    - Выход: q + Enter
    """

    stop = {"value": False}

    def input_thread():
        while True:
            cmd = input("ТО: q + Enter — выход > ").strip().lower()
            if cmd == "q":
                stop["value"] = True
                return

    threading.Thread(target=input_thread, daemon=True).start()

    conn = None
    iteration = 0

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        while True:
            if stop["value"]:
                conn.commit()
                print("[SERVICE] Выход из режима ТО")
                return {
                    "ok": True,
                    "iterations": iteration,
                    "message": "Режим техобслуживания завершён оператором",
                }

            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    UPDATE public."IH_led_task" t
                    SET bin_status_id = CASE
                                            WHEN COALESCE(b."Sensor", 0) = 1 THEN 3
                                            ELSE 1
                                        END,
                        "Blynk_id"     = 1
                    FROM public."IH_bin" b
                    WHERE t.bin_id = b.id;
                    """
                )

            conn.commit()
            iteration += 1
            print(f"[SERVICE] цикл={iteration}")
            time.sleep(poll_interval)

    except KeyboardInterrupt:
        if conn:
            conn.rollback()
        return {"ok": True, "message": "Остановлено Ctrl+C", "iterations": iteration}

    except Exception as e:
        if conn:
            conn.rollback()
        return {"ok": False, "error": str(e), "iterations": iteration}

    finally:
        if conn:
            conn.close()
############СТОП  по списку неисправных bin_id выставляет подсветку################################






############СТАРТ  ################################
def open_idle_operation(operator: str, workstation_id: str) -> dict:
    """
    Открывает операцию IDLE (op_type='IDLE', status='IDLE')
    с finished_at = NULL.

    Важно:
      - Если последняя операция НЕ IDLE и НЕ закрыта → закрываем её.
      - Если последняя операция — IDLE и она уже открыта → НИЧЕГО НЕ ДЕЛАЕМ.
        (IDLE должен висеть открытым)
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False

        with conn.cursor(cursor_factory=DictCursor) as cur:

            # Берём последнюю операцию
            cur.execute("""
                SELECT id, op_type, finished_at
                FROM public."IH_Operation"
                ORDER BY id DESC
                LIMIT 1;
            """)
            row = cur.fetchone()

            if row is not None:
                last_id = row["id"]
                last_type = row["op_type"]
                last_finished = row["finished_at"]

                # Если последняя операция — IDLE и она открыта → ничего не делаем
                if last_type == "IDLE" and last_finished is None:
                    msg = f"Операция IDLE уже активна (id={last_id}). Новую не создаём."
                    print("[DB]", msg)
                    return {
                        "ok": True,
                        "op_id": last_id,
                        "message": msg,
                    }

                # Если последняя не IDLE и открыта → закрываем
                if last_type != "IDLE" and last_finished is None:
                    print(f"[DB] Закрываем предыдущую незавершённую операцию id={last_id}")
                    cur.execute(
                        '''
                        UPDATE public."IH_Operation"
                        SET finished_at = NOW()
                        WHERE id = %s;
                        ''',
                        (last_id,)
                    )

            # Создаём новую IDLE
            print("[DB] Открываем новую операцию IDLE")
            cur.execute(
                '''
                INSERT INTO public."IH_Operation"
                    (op_type, status, operator, workstation_id, started_at, finished_at)
                VALUES
                    ('IDLE', 'IDLE', %s, %s, NOW(), NULL)
                RETURNING id;
                ''',
                (operator, workstation_id)
            )
            new_id = cur.fetchone()[0]

        conn.commit()
        msg = f"Открыта новая операция IDLE, id={new_id}"
        print("[DB]", msg)

        return {
            "ok": True,
            "op_id": new_id,
            "message": msg,
        }

    except Exception as e:
        if conn:
            conn.rollback()
        msg = f"Ошибка при открытии IDLE: {e}"
        print("[ERROR]", msg)

        return {
            "ok": False,
            "op_id": None,
            "message": msg,
        }

    finally:
        if conn:
            conn.close()
############СТОП  ################################
