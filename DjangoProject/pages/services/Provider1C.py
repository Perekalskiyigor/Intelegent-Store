import psycopg2
import requests
from psycopg2.extras import DictCursor

BASE_URL = "http://black/erp_game_razin/hs/cmpp"
# Пример: "cmpp:123" -> base64 => "Y21wcDoxMjM="
AUTH_BASIC = "Basic Y21wcDoxMjM="  # <-- сюда подставь свой Basic

DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "1",
    "host": "localhost",
    "port": 5432,
}

def get_cmpp_carrier(carrier_no: str | int, timeout: float = 15.0):
    """
    carrier_no: 296002
    return: dict/list если ответ JSON, иначе str (text)
    """
    carrier_no = str(carrier_no).strip()
    url = f"{BASE_URL}/{carrier_no}"

    headers = {
        "Authorization": AUTH_BASIC,
        "Accept": "application/json, text/plain, */*",
    }

    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()  # если 4xx/5xx -> выбросит исключение

    # пробуем JSON, если не JSON — вернем текст
    try:
        return r.json()
    except ValueError:
        return r.text
    

"""
берёт ответ API и пишет/обновляет записи в твоих таблицах, соблюдая правило:

ищем по carrier_no → это у тебя IH_ref_items.bar_code

если запись есть и qty_units не поменялся → ничего не делаем

если запись есть и qty_units поменялся → обновляем количество (и заодно можно обновить uom/series/size, чтобы база не “старела”)

если записи нет → вставляем в IH_ref_items, затем в IH_tech_unit и IH_ref_size, и связываем IH_ref_items.id_IH_TechUnit
"""

def get_cmpp_carrier(carrier_no: str | int, timeout: float = 15.0):
    carrier_no = str(carrier_no).strip()
    url = f"{BASE_URL}/{carrier_no}"

    headers = {
        "Authorization": AUTH_BASIC,
        "Accept": "application/json, text/plain, */*",
    }

    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()

    try:
        return r.json()
    except ValueError:
        return r.text


from psycopg2.extras import DictCursor

def upsert_from_api_payload(payload: dict, conn) -> dict:
    """
    payload = {
        "carrier_no": "283448",
        "series_no": "S00500744",
        "item_code": "О00336     ",
        "item_name": "...",
        "uom": "уп(2000шт)",
        "qty_units": 0,
        "size_name": "...",
        "size_code": "000000058"
    }
    """

    carrier_no = payload.get("carrier_no")
    series_no = payload.get("series_no")
    item_code = payload.get("item_code", "").strip()
    item_name = payload.get("item_name")
    uom = payload.get("uom")
    qty_units = payload.get("qty_units", 0)
    size_name = payload.get("size_name")
    size_code = payload.get("size_code")

    with conn.cursor(cursor_factory=DictCursor) as cur:

        # --- 1. Проверяем есть ли item ---
        cur.execute(
            '''
            SELECT id
            FROM public."IH_ref_items"
            WHERE bar_code = %s
            LIMIT 1;
            ''',
            (carrier_no,)
        )
        row = cur.fetchone()

        if row:
            # =========================
            # ОБНОВЛЯЕМ
            # =========================
            item_id = row["id"]

            # Обновляем товар
            cur.execute(
                '''
                UPDATE public."IH_ref_items"
                SET
                    name = %s,
                    ext_id = %s,
                    qwantity = %s
                WHERE id = %s;
                ''',
                (item_name, series_no, qty_units, item_id)
            )

            # Обновляем размер
            cur.execute(
                '''
                UPDATE public."IH_ref_size"
                SET
                    size_name = %s,
                    size_code = %s
                WHERE item_id = %s;
                ''',
                (size_name, size_code, item_id)
            )

            # Обновляем тех.единицу
            cur.execute(
                '''
                UPDATE public."IH_tech_unit"
                SET
                    item_code = %s,
                    uom = %s,
                    series_no = %s,
                    code = %s
                WHERE item_id = %s;
                ''',
                (item_code, uom, series_no, carrier_no, item_id)
            )

            status = "updated"

        else:
            # =========================
            # ВСТАВЛЯЕМ
            # =========================

            # Вставляем товар
            cur.execute(
                '''
                INSERT INTO public."IH_ref_items"
                (bar_code, ext_id, name, qwantity)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                ''',
                (carrier_no, series_no, item_name, qty_units)
            )
            item_id = cur.fetchone()["id"]

            # Вставляем размер
            cur.execute(
                '''
                INSERT INTO public."IH_ref_size"
                (item_id, size_name, size_code)
                VALUES (%s, %s, %s);
                ''',
                (item_id, size_name, size_code)
            )

            # Вставляем тех.единицу
            cur.execute(
                '''
                INSERT INTO public."IH_tech_unit"
                (item_id, item_code, uom, series_no, code)
                VALUES (%s, %s, %s, %s, %s);
                ''',
                (item_id, item_code, uom, series_no, carrier_no)
            )

            status = "inserted"

    conn.commit()

    return {
        "status": status,
        "item_id": item_id,
        "carrier_no": carrier_no
    }



if __name__ == "__main__":
    payload = get_cmpp_carrier(196707)
    print("API:", payload)

    with psycopg2.connect(**DB_CONFIG) as conn:
        result = upsert_from_api_payload(payload, conn)
        print(result)