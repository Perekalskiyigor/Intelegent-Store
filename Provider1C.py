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

def upsert_cmpp_to_db(payload: dict, conn) -> dict:
    carrier_no = str(payload.get("carrier_no", "")).strip()
    if not carrier_no:
        raise ValueError("payload.carrier_no is empty")

    # ext_id = series_no (NOT NULL)
    series_no = (payload.get("series_no") or "").strip()
    if not series_no:
        raise ValueError('payload.series_no is empty (needed for IH_ref_items.ext_id NOT NULL)')

    item_name = (payload.get("item_name") or "").strip()
    item_code = (payload.get("item_code") or "").strip() or None
    uom = (payload.get("uom") or "").strip() or None
    size_name = (payload.get("size_name") or "").strip() or None
    size_code = (payload.get("size_code") or "").strip() or None

    qty_units_raw = payload.get("qty_units")
    qty_units = int(qty_units_raw) if qty_units_raw is not None else None

    with conn.cursor(cursor_factory=DictCursor) as cur:
        # 1) ищем по bar_code
        cur.execute(
            """
            SELECT id, qwantity, ext_id, "id_IH_TechUnit"
            FROM public."IH_ref_items"
            WHERE bar_code = %s
            FOR UPDATE
            """,
            (carrier_no,),
        )
        row = cur.fetchone()

        # =========================
        # CASE A: запись есть
        # =========================
        if row:
            item_id = row["id"]
            old_qty = row["qwantity"]

            # если qty не поменялся — ничего не делаем
            if qty_units is not None and old_qty == qty_units:
                conn.commit()
                return {"status": "noop", "item_id": item_id, "carrier_no": carrier_no, "qty_units": qty_units}

            # обновляем item (и ext_id тоже держим актуальным)
            cur.execute(
                """
                UPDATE public."IH_ref_items"
                SET
                    ext_id = %s,
                    name = COALESCE(NULLIF(%s, ''), name),
                    qwantity = COALESCE(%s, qwantity)
                WHERE id = %s
                """,
                (series_no, item_name, qty_units, item_id),
            )

            # tech_unit
            tech_unit_id = row["id_IH_TechUnit"]
            if tech_unit_id:
                cur.execute(
                    """
                    UPDATE public."IH_tech_unit"
                    SET
                        item_code = COALESCE(%s, item_code),
                        uom = COALESCE(%s, uom),
                        series_no = COALESCE(%s, series_no)
                    WHERE id = %s
                    """,
                    (item_code, uom, series_no, tech_unit_id),
                )
            else:
                # создаём tech_unit и привязываем
                cur.execute(
                    """
                    INSERT INTO public."IH_tech_unit" (item_id, item_code, uom, series_no)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (item_id, item_code, uom, series_no),
                )
                tech_unit_id = cur.fetchone()["id"]

                cur.execute(
                    """
                    UPDATE public."IH_ref_items"
                    SET "id_IH_TechUnit" = %s
                    WHERE id = %s
                    """,
                    (tech_unit_id, item_id),
                )

            # size (одна строка на item_id)
            cur.execute("""SELECT id FROM public."IH_ref_size" WHERE item_id=%s""", (item_id,))
            if cur.fetchone():
                cur.execute(
                    """
                    UPDATE public."IH_ref_size"
                    SET
                        size_name = COALESCE(%s, size_name),
                        size_code = COALESCE(NULLIF(%s, ''), size_code)
                    WHERE item_id = %s
                    """,
                    (size_name, size_code, item_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO public."IH_ref_size" (item_id, size_name, size_code)
                    VALUES (%s, %s, %s)
                    """,
                    (item_id, size_name, size_code),
                )

            conn.commit()
            return {"status": "updated", "item_id": item_id, "carrier_no": carrier_no, "qty_old": old_qty, "qty_new": qty_units}

        # =========================
        # CASE B: записи нет -> вставка
        # =========================
        cur.execute(
            """
            INSERT INTO public."IH_ref_items" (ext_id, name, bar_code, qwantity)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (series_no, item_name, carrier_no, qty_units),
        )
        item_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO public."IH_tech_unit" (item_id, item_code, uom, series_no)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (item_id, item_code, uom, series_no),
        )
        tech_unit_id = cur.fetchone()["id"]

        cur.execute(
            """
            UPDATE public."IH_ref_items"
            SET "id_IH_TechUnit" = %s
            WHERE id = %s
            """,
            (tech_unit_id, item_id),
        )

        cur.execute(
            """
            INSERT INTO public."IH_ref_size" (item_id, size_name, size_code)
            VALUES (%s, %s, %s)
            """,
            (item_id, size_name, size_code),
        )

        conn.commit()
        return {"status": "inserted", "item_id": item_id, "carrier_no": carrier_no, "qty_units": qty_units}



# if __name__ == "__main__":
#     payload = get_cmpp_carrier(296002)
#     print("API:", payload)

#     with psycopg2.connect(**DB_CONFIG) as conn:
#         result = upsert_cmpp_to_db(payload, conn)
#         print("DB:", result)