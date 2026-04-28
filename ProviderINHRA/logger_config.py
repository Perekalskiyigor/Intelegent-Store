import logging

def setup_logging():
    logging.basicConfig(
        filename="LOGINHRA.log",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        encoding='utf-8'   # ВОТ ЭТО КЛЮЧ
    )