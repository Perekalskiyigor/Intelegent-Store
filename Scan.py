import psycopg2
from psycopg2.extras import RealDictCursor
from config import DB_CONFIG


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def scan_item(code: str, include_sizes: bool = True) -> dict | None:
    """
    Сканируем 'code' и ищем товар в ref_items.
    Приоритет поиска:
      1) bar_code = code
      2) ext_id   = code
      3) name ILIKE code

    Возвращает словарь с полной инфой по ref_items,
    плюс sizes (список размеров) если include_sizes=True.
    """
    code = (code or "").strip()
    if not code:
        return None

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1) поиск по bar_code
            cur.execute("""
                SELECT *
                FROM public.ref_items
                WHERE bar_code = %s
                ORDER BY id ASC
                LIMIT 1;
            """, (code,))
            row = cur.fetchone()

            # 2) если не нашли, ищем по ext_id
            if row is None:
                cur.execute("""
                    SELECT *
                    FROM public.ref_items
                    WHERE ext_id = %s
                    ORDER BY id ASC
                    LIMIT 1;
                """, (code,))
                row = cur.fetchone()

            # 3) если не нашли, ищем по name (регистронезависимо)
            if row is None:
                cur.execute("""
                    SELECT *
                    FROM public.ref_items
                    WHERE name ILIKE %s
                    ORDER BY id ASC
                    LIMIT 1;
                """, (code,))
                row = cur.fetchone()

            if row is None:
                return None

            item = dict(row)

            if include_sizes:
                cur.execute("""
                    SELECT *
                    FROM public.ref_size
                    WHERE item_id = %s
                    ORDER BY id ASC;
                """, (item["id"],))
                sizes = [dict(r) for r in cur.fetchall()]
                item["sizes"] = sizes

            return item
    finally:
        conn.close()
        
code = ".sf#Bekd"  # твой bar_code
result = scan_item(code)
if result:
    print("Найдено:", result)
else:
    print("Не найдено")
