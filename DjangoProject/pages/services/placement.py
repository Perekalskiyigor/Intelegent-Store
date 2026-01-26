import time
from pages.services import logInsert

def run_placement() -> dict:
    logInsert.ih_log("Начата операция размещения", operation="PLACEMENT", source="placement", user="ivanov")

    for i in range(5):
        logInsert.ih_log(f"Шаг {i+1}/5: делаю работу...", operation="PLACEMENT", source="placement", user="ivanov")
        time.sleep(0.3)

    logInsert.ih_log("Операция завершена", operation="PLACEMENT", source="placement", user="ivanov")
    return {"ok": True}
