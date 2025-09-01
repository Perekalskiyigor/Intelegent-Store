import psycopg2
from psycopg2.extras import RealDictCursor
from config import DB_CONFIG


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def upsert_item_with_size_by_name(item_name: str,
                                  item_ext_id: str | None,
                                  size_name: str,
                                  size_ext_id: str | None):
    """
    Upsert по name:
      - ref_items: ON CONFLICT (name) DO UPDATE SET ext_id = EXCLUDED.ext_id
      - ref_size : ON CONFLICT (item_id, name) DO UPDATE SET ext_id = EXCLUDED.ext_id

    Возвращает (item_id, size_id).
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1) upsert item по name
            cur.execute("""
                INSERT INTO public.ref_items (name, ext_id)
                VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE
                    SET ext_id = EXCLUDED.ext_id
                RETURNING id;
            """, (item_name, item_ext_id))
            item_id = cur.fetchone()["id"]

            # 2) upsert size по (item_id, name)
            cur.execute("""
                INSERT INTO public.ref_size (name, ext_id, item_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (item_id, name) DO UPDATE
                    SET ext_id = EXCLUDED.ext_id
                RETURNING id;
            """, (size_name, size_ext_id, item_id))
            size_id = cur.fetchone()["id"]

        conn.commit()
        return item_id, size_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


item_id, size_id = upsert_item_with_size_by_name(
        item_name="LED3",
        item_ext_id="itm-1001",   # можно None, если не нужно
        size_name="42",
        size_ext_id="sz-42-1001"  # можно None
    )
print(f"item_id={item_id}, size_id={size_id}")
