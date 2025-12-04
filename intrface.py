# -*- coding: utf-8 -*-
"""
Tkinter GUI для "умного склада"
Иерархия: site (Склад) -> rack (Стеллаж) -> shelf (Полка) -> bin (Ячейка)
Возможности: просмотр всего дерева, добавление, редактирование. Поиск/удаление — не реализованы.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import psycopg2
import psycopg2.extras

from config import DB_CONFIG


# ==== Настройки подключения к БД ====
DB_DSN = {
    "host": "localhost",
    "port": 5432,
    "dbname": "your_db",
    "user": "your_user",
    "password": "your_password",
}

# ==== SQL ====
SQL_SELECT_SITES  = "SELECT id, code, name FROM public.site ORDER BY id"
SQL_SELECT_RACKS  = "SELECT id, site_id, code, name FROM public.rack WHERE site_id=%s ORDER BY id"
SQL_SELECT_SHELVES= "SELECT id, rack_id, code, level_no FROM public.shelf WHERE rack_id=%s ORDER BY id"
SQL_SELECT_BINS   = "SELECT id, shelf_id, address, position_no FROM public.bin WHERE shelf_id=%s ORDER BY id"

SQL_INSERT_SITE   = "INSERT INTO public.site (code, name) VALUES (%s, %s) RETURNING id"
SQL_UPDATE_SITE   = "UPDATE public.site SET code=%s, name=%s WHERE id=%s"

SQL_INSERT_RACK   = "INSERT INTO public.rack (site_id, code, name) VALUES (%s, %s, %s) RETURNING id"
SQL_UPDATE_RACK   = "UPDATE public.rack SET site_id=%s, code=%s, name=%s WHERE id=%s"

SQL_INSERT_SHELF  = "INSERT INTO public.shelf (rack_id, code, level_no) VALUES (%s, %s, %s) RETURNING id"
SQL_UPDATE_SHELF  = "UPDATE public.shelf SET rack_id=%s, code=%s, level_no=%s WHERE id=%s"

SQL_INSERT_BIN    = "INSERT INTO public.bin (shelf_id, address, position_no) VALUES (%s, %s, %s) RETURNING id"
SQL_UPDATE_BIN    = "UPDATE public.bin SET shelf_id=%s, address=%s, position_no=%s WHERE id=%s"


# ==== Обёртка БД ====
class DB:
    def __init__(self, dsn: dict):
        self.conn = psycopg2.connect(**dsn)
        self.conn.autocommit = True

    def fetchall(self, sql, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()

    def fetchone(self, sql, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()

    def execute(self, sql, params=None, returning=False):
        with self.conn.cursor() as cur:
            cur.execute(sql, params or ())
            if returning:
                rid = cur.fetchone()[0]
                return rid

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


# ==== Приложение ====
class WarehouseApp(tk.Tk):
    def __init__(self, db: DB):
        super().__init__()
        self.title("Умный склад — Управление (site/rack/shelf/bin)")
        self.geometry("1100x650")
        self.minsize(950, 560)

        self.db = db

        self._build_ui()
        self._load_tree()

    # ---------- UI ----------
    def _build_ui(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=5)
        self.rowconfigure(0, weight=1)

        # Левая панель (Tree)
        left = ttk.Frame(self, padding=(10,10))
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        lbl = ttk.Label(left, text="Склад → Стеллаж → Полка → Ячейка", font=("Segoe UI", 10, "bold"))
        lbl.grid(row=0, column=0, sticky="w", pady=(0,6))

        self.tree = ttk.Treeview(left, show="tree")
        self.tree.grid(row=1, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        vsb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.on_tree_expand_collapse)

        # Правая панель (формы)
        right = ttk.Frame(self, padding=(10,10))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        # Переключатель типа объекта
        type_frame = ttk.LabelFrame(right, text="Тип объекта")
        type_frame.grid(row=0, column=0, sticky="ew", pady=(0,10))
        self.obj_type = tk.StringVar(value="site")
        for i, (val, txt) in enumerate([
            ("site", "Склад"),
            ("rack", "Стеллаж"),
            ("shelf","Полка"),
            ("bin",  "Ячейка"),
        ]):
            rb = ttk.Radiobutton(type_frame, text=txt, value=val, variable=self.obj_type, command=self._on_type_change)
            rb.grid(row=0, column=i, padx=6, pady=6)

        # Форма
        self.form = ttk.LabelFrame(right, text="Данные")
        self.form.grid(row=1, column=0, sticky="nsew")
        for r in range(12):
            self.form.rowconfigure(r, weight=0)
        self.form.columnconfigure(1, weight=1)

        # Поля формы (общие + зависят от типа)
        self.var_id = tk.StringVar()
        self.var_code = tk.StringVar()
        self.var_name = tk.StringVar()
        self.var_level_no = tk.StringVar()
        self.var_position_no = tk.StringVar()
        self.var_address = tk.StringVar()

        self.cmb_site_for_rack = ttk.Combobox(self.form, state="readonly")
        self.cmb_rack_for_shelf = ttk.Combobox(self.form, state="readonly")
        self.cmb_shelf_for_bin = ttk.Combobox(self.form, state="readonly")

        # Метки и поля — будем показывать/прятать по типу
        self._build_form_widgets()

        # Кнопки действия
        btns = ttk.Frame(right)
        btns.grid(row=2, column=0, sticky="ew", pady=(10,0))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        btns.columnconfigure(2, weight=1)

        self.btn_add = ttk.Button(btns, text="Добавить", command=self.on_add)
        self.btn_add.grid(row=0, column=0, sticky="ew", padx=4)

        self.btn_save = ttk.Button(btns, text="Сохранить изменения", command=self.on_save)
        self.btn_save.grid(row=0, column=1, sticky="ew", padx=4)

        self.btn_refresh = ttk.Button(btns, text="Обновить дерево", command=self._reload_tree_preserving_selection)
        self.btn_refresh.grid(row=0, column=2, sticky="ew", padx=4)

        # Нижняя строка статуса
        self.status = tk.StringVar(value="Готово")
        statusbar = ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w")
        statusbar.grid(row=1, column=0, columnspan=2, sticky="ew")

        self._on_type_change()

    def _build_form_widgets(self):
        # Очищаем форму
        for child in self.form.winfo_children():
            child.destroy()

        row = 0
        ttk.Label(self.form, text="ID (только чтение):").grid(row=row, column=0, sticky="e", padx=6, pady=6)
        ent_id = ttk.Entry(self.form, textvariable=self.var_id, state="readonly")
        ent_id.grid(row=row, column=1, sticky="ew", padx=6, pady=6)

        obj = self.obj_type.get()

        # Общие поля: code/name
        if obj in ("site", "rack", "shelf"):
            row += 1
            ttk.Label(self.form, text="Код:").grid(row=row, column=0, sticky="e", padx=6, pady=6)
            ttk.Entry(self.form, textvariable=self.var_code).grid(row=row, column=1, sticky="ew", padx=6, pady=6)
        if obj in ("site", "rack"):
            row += 1
            ttk.Label(self.form, text="Наименование:").grid(row=row, column=0, sticky="e", padx=6, pady=6)
            ttk.Entry(self.form, textvariable=self.var_name).grid(row=row, column=1, sticky="ew", padx=6, pady=6)

        # Зависимые поля (Foreign Keys)
        if obj == "rack":
            row += 1
            ttk.Label(self.form, text="Склад (site):").grid(row=row, column=0, sticky="e", padx=6, pady=6)
            self.cmb_site_for_rack = ttk.Combobox(self.form, state="readonly")
            self.cmb_site_for_rack.grid(row=row, column=1, sticky="ew", padx=6, pady=6)
            self._fill_sites_combobox()  # заполнить

        if obj == "shelf":
            row += 1
            ttk.Label(self.form, text="Стеллаж (rack):").grid(row=row, column=0, sticky="e", padx=6, pady=6)
            self.cmb_rack_for_shelf = ttk.Combobox(self.form, state="readonly")
            self.cmb_rack_for_shelf.grid(row=row, column=1, sticky="ew", padx=6, pady=6)
            self._fill_racks_combobox()

            row += 1
            ttk.Label(self.form, text="Код полки:").grid(row=row, column=0, sticky="e", padx=6, pady=6)
            ttk.Entry(self.form, textvariable=self.var_code).grid(row=row, column=1, sticky="ew", padx=6, pady=6)

            row += 1
            ttk.Label(self.form, text="Уровень (level_no):").grid(row=row, column=0, sticky="e", padx=6, pady=6)
            ttk.Entry(self.form, textvariable=self.var_level_no).grid(row=row, column=1, sticky="ew", padx=6, pady=6)

        if obj == "bin":
            row += 1
            ttk.Label(self.form, text="Полка (shelf):").grid(row=row, column=0, sticky="e", padx=6, pady=6)
            self.cmb_shelf_for_bin = ttk.Combobox(self.form, state="readonly")
            self.cmb_shelf_for_bin.grid(row=row, column=1, sticky="ew", padx=6, pady=6)
            self._fill_shelves_combobox()

            row += 1
            ttk.Label(self.form, text="Адрес (address):").grid(row=row, column=0, sticky="e", padx=6, pady=6)
            ttk.Entry(self.form, textvariable=self.var_address).grid(row=row, column=1, sticky="ew", padx=6, pady=6)

            row += 1
            ttk.Label(self.form, text="Позиция (position_no):").grid(row=row, column=0, sticky="e", padx=6, pady=6)
            ttk.Entry(self.form, textvariable=self.var_position_no).grid(row=row, column=1, sticky="ew", padx=6, pady=6)

    # ---------- Загрузка дерева ----------
    def _load_tree(self):
        self.tree.delete(*self.tree.get_children())
        try:
            sites = self.db.fetchall(SQL_SELECT_SITES)
            for s in sites:
                sid = f"site:{s['id']}"
                text = f"Склад [{s['id']}] {s['code']} — {s['name']}"
                self.tree.insert("", "end", iid=sid, text=text, values=("site", s['id']))
                # отложенная подзагрузка при раскрытии — чтобы быстрее
                self.tree.insert(sid, "end", iid=f"{sid}:placeholder", text="…")
        except Exception as e:
            messagebox.showerror("Ошибка загрузки", str(e))

        # Событие раскрытия узла для ленивой подгрузки
        self.tree.bind("<<TreeviewOpen>>", self.on_tree_open)

    def _reload_tree_preserving_selection(self):
        sel = self.tree.selection()
        self._load_tree()
        # Попробуем восстановить выбор (если ещё существует)
        if sel:
            try:
                self.tree.selection_set(sel[0])
                self.tree.see(sel[0])
            except Exception:
                pass

    def on_tree_open(self, event):
        item = self.tree.focus()
        if not item:
            return
        # Если есть placeholder — грузим детей
        children = self.tree.get_children(item)
        if len(children) == 1 and children[0].endswith("placeholder"):
            self.tree.delete(children[0])
            self._populate_children(item)

    def _populate_children(self, iid):
        try:
            kind, pk = iid.split(":")[:2]
            pk = int(pk)
            if kind == "site":
                racks = self.db.fetchall(SQL_SELECT_RACKS, (pk,))
                for r in racks:
                    rid = f"rack:{r['id']}"
                    t = f"Стеллаж [{r['id']}] {r['code']} — {r['name']}"
                    self.tree.insert(iid, "end", iid=rid, text=t)
                    self.tree.insert(rid, "end", iid=f"{rid}:placeholder", text="…")
            elif kind == "rack":
                shelves = self.db.fetchall(SQL_SELECT_SHELVES, (pk,))
                for sh in shelves:
                    shid = f"shelf:{sh['id']}"
                    t = f"Полка [{sh['id']}] {sh['code']} — уровень {sh['level_no']}"
                    self.tree.insert(iid, "end", iid=shid, text=t)
                    self.tree.insert(shid, "end", iid=f"{shid}:placeholder", text="…")
            elif kind == "shelf":
                bins = self.db.fetchall(SQL_SELECT_BINS, (pk,))
                for b in bins:
                    bid = f"bin:{b['id']}"
                    t = f"Ячейка [{b['id']}] {b['address']} — позиция {b['position_no']}"
                    self.tree.insert(iid, "end", iid=bid, text=t)
        except Exception as e:
            messagebox.showerror("Ошибка подгрузки", str(e))

    # ---------- Выбор в дереве ----------
    def on_tree_select(self, event):
        iid = self.tree.focus()
        if not iid:
            return
        kind, pk = iid.split(":")[:2]
        self.obj_type.set(kind)
        self._on_type_change()  # перестроить форму
        self._load_record_into_form(kind, int(pk))

    def on_tree_expand_collapse(self, event):
        # Двойной клик — просто раскрыть/свернуть (Tk сам делает), логика уже в on_tree_open
        pass

    # ---------- Заполнение формы ----------
    def _load_record_into_form(self, kind: str, pk: int):
        self._clear_form()
        try:
            if kind == "site":
                row = self.db.fetchone("SELECT id, code, name FROM public.site WHERE id=%s", (pk,))
                if row:
                    self.var_id.set(row["id"])
                    self.var_code.set(row["code"] or "")
                    self.var_name.set(row["name"] or "")
            elif kind == "rack":
                row = self.db.fetchone("SELECT id, site_id, code, name FROM public.rack WHERE id=%s", (pk,))
                if row:
                    self.var_id.set(row["id"])
                    self._fill_sites_combobox(select_id=row["site_id"])
                    self.var_code.set(row["code"] or "")
                    self.var_name.set(row["name"] or "")
            elif kind == "shelf":
                row = self.db.fetchone("SELECT id, rack_id, code, level_no FROM public.shelf WHERE id=%s", (pk,))
                if row:
                    self.var_id.set(row["id"])
                    self._fill_racks_combobox(select_id=row["rack_id"])
                    self.var_code.set(row["code"] or "")
                    self.var_level_no.set("" if row["level_no"] is None else str(row["level_no"]))
            elif kind == "bin":
                row = self.db.fetchone("SELECT id, shelf_id, address, position_no FROM public.bin WHERE id=%s", (pk,))
                if row:
                    self.var_id.set(row["id"])
                    self._fill_shelves_combobox(select_id=row["shelf_id"])
                    self.var_address.set(row["address"] or "")
                    self.var_position_no.set("" if row["position_no"] is None else str(row["position_no"]))
        except Exception as e:
            messagebox.showerror("Ошибка загрузки записи", str(e))

    def _clear_form(self):
        self.var_id.set("")
        self.var_code.set("")
        self.var_name.set("")
        self.var_level_no.set("")
        self.var_position_no.set("")
        self.var_address.set("")

    # ---------- Комбобоксы связей ----------
    def _fill_sites_combobox(self, select_id=None):
        rows = self.db.fetchall(SQL_SELECT_SITES)
        items = [f"{r['id']}: {r['code']} — {r['name']}" for r in rows]
        self.cmb_site_for_rack["values"] = items
        if select_id:
            for i, r in enumerate(rows):
                if r["id"] == select_id:
                    self.cmb_site_for_rack.current(i)
                    break

    def _fill_racks_combobox(self, select_id=None):
        # Все стеллажи всех складов (для удобства выбора при добавлении/редактировании полки)
        racks = self.db.fetchall("SELECT id, site_id, code, name FROM public.rack ORDER BY id")
        items = []
        for r in racks:
            # Покажем и склад, и стеллаж
            site = self.db.fetchone("SELECT id, code, name FROM public.site WHERE id=%s", (r["site_id"],))
            site_txt = f"{site['id']}:{site['code']}" if site else "?"
            items.append(f"{r['id']}: [{site_txt}] {r['code']} — {r['name']}")
        self.cmb_rack_for_shelf["values"] = items
        if select_id:
            for i, r in enumerate(racks):
                if r["id"] == select_id:
                    self.cmb_rack_for_shelf.current(i)
                    break

    def _fill_shelves_combobox(self, select_id=None):
        shelves = self.db.fetchall("SELECT sh.id, sh.rack_id, sh.code, sh.level_no, r.code AS rack_code FROM public.shelf sh JOIN public.rack r ON r.id=sh.rack_id ORDER BY sh.id")
        items = [f"{sh['id']}: [Rack {sh['rack_id']}:{sh['rack_code']}] {sh['code']} — уровень {sh['level_no']}" for sh in shelves]
        self.cmb_shelf_for_bin["values"] = items
        if select_id:
            for i, sh in enumerate(shelves):
                if sh["id"] == select_id:
                    self.cmb_shelf_for_bin.current(i)
                    break

    # ---------- Изменение типа формы ----------
    def _on_type_change(self):
        self._build_form_widgets()
        self.status.set(f"Тип объекта: {self.obj_type.get().upper()}")

    # ---------- Добавление ----------
    def on_add(self):
        kind = self.obj_type.get()
        try:
            if kind == "site":
                code = self.var_code.get().strip()
                name = self.var_name.get().strip()
                if not code or not name:
                    return messagebox.showwarning("Проверка", "Укажите Код и Наименование склада.")
                new_id = self.db.execute(SQL_INSERT_SITE, (code, name), returning=True)
                self.status.set(f"Добавлен склад ID={new_id}")
            elif kind == "rack":
                if not self.cmb_site_for_rack.get():
                    return messagebox.showwarning("Проверка", "Выберите склад (site) для стеллажа.")
                site_id = int(self.cmb_site_for_rack.get().split(":")[0])
                code = self.var_code.get().strip()
                name = self.var_name.get().strip()
                if not code or not name:
                    return messagebox.showwarning("Проверка", "Укажите Код и Наименование стеллажа.")
                new_id = self.db.execute(SQL_INSERT_RACK, (site_id, code, name), returning=True)
                self.status.set(f"Добавлен стеллаж ID={new_id}")
            elif kind == "shelf":
                if not self.cmb_rack_for_shelf.get():
                    return messagebox.showwarning("Проверка", "Выберите стеллаж (rack) для полки.")
                rack_id = int(self.cmb_rack_for_shelf.get().split(":")[0])
                code = self.var_code.get().strip()
                level_no = self._parse_int(self.var_level_no.get(), "Уровень (level_no)")
                if code is None or level_no is None:
                    if code is None:
                        messagebox.showwarning("Проверка", "Укажите Код полки.")
                    return
                new_id = self.db.execute(SQL_INSERT_SHELF, (rack_id, code, level_no), returning=True)
                self.status.set(f"Добавлена полка ID={new_id}")
            elif kind == "bin":
                if not self.cmb_shelf_for_bin.get():
                    return messagebox.showwarning("Проверка", "Выберите полку (shelf) для ячейки.")
                shelf_id = int(self.cmb_shelf_for_bin.get().split(":")[0])
                address = self.var_address.get().strip()
                position_no = self._parse_int(self.var_position_no.get(), "Позиция (position_no)")
                if not address or position_no is None:
                    if not address:
                        messagebox.showwarning("Проверка", "Укажите Адрес (address) ячейки.")
                    return
                new_id = self.db.execute(SQL_INSERT_BIN, (shelf_id, address, position_no), returning=True)
                self.status.set(f"Добавлена ячейка ID={new_id}")
            self._reload_tree_preserving_selection()
        except Exception as e:
            messagebox.showerror("Ошибка добавления", str(e))

    # ---------- Сохранение (редактирование) ----------
    def on_save(self):
        kind = self.obj_type.get()
        if not self.var_id.get():
            return messagebox.showinfo("Инфо", "Нет выбранной записи для сохранения. Выберите запись в дереве.")
        pk = int(self.var_id.get())
        try:
            if kind == "site":
                code = self.var_code.get().strip()
                name = self.var_name.get().strip()
                if not code or not name:
                    return messagebox.showwarning("Проверка", "Укажите Код и Наименование склада.")
                self.db.execute(SQL_UPDATE_SITE, (code, name, pk))
                self.status.set(f"Обновлён склад ID={pk}")
            elif kind == "rack":
                if not self.cmb_site_for_rack.get():
                    return messagebox.showwarning("Проверка", "Выберите склад (site) для стеллажа.")
                site_id = int(self.cmb_site_for_rack.get().split(":")[0])
                code = self.var_code.get().strip()
                name = self.var_name.get().strip()
                if not code or not name:
                    return messagebox.showwarning("Проверка", "Укажите Код и Наименование стеллажа.")
                self.db.execute(SQL_UPDATE_RACK, (site_id, code, name, pk))
                self.status.set(f"Обновлён стеллаж ID={pk}")
            elif kind == "shelf":
                if not self.cmb_rack_for_shelf.get():
                    return messagebox.showwarning("Проверка", "Выберите стеллаж (rack) для полки.")
                rack_id = int(self.cmb_rack_for_shelf.get().split(":")[0])
                code = self.var_code.get().strip()
                level_no = self._parse_int(self.var_level_no.get(), "Уровень (level_no)")
                if code is None or level_no is None:
                    if code is None:
                        messagebox.showwarning("Проверка", "Укажите Код полки.")
                    return
                self.db.execute(SQL_UPDATE_SHELF, (rack_id, code, level_no, pk))
                self.status.set(f"Обновлена полка ID={pk}")
            elif kind == "bin":
                if not self.cmb_shelf_for_bin.get():
                    return messagebox.showwarning("Проверка", "Выберите полку (shelf) для ячейки.")
                shelf_id = int(self.cmb_shelf_for_bin.get().split(":")[0])
                address = self.var_address.get().strip()
                position_no = self._parse_int(self.var_position_no.get(), "Позиция (position_no)")
                if not address or position_no is None:
                    if not address:
                        messagebox.showwarning("Проверка", "Укажите Адрес (address) ячейки.")
                    return
                self.db.execute(SQL_UPDATE_BIN, (shelf_id, address, position_no, pk))
                self.status.set(f"Обновлена ячейка ID={pk}")
            self._reload_tree_preserving_selection()
        except Exception as e:
            messagebox.showerror("Ошибка сохранения", str(e))

    # ---------- Утилиты ----------
    @staticmethod
    def _parse_int(val, field_name):
        v = val.strip()
        if v == "":
            messagebox.showwarning("Проверка", f"Укажите {field_name}.")
            return None
        try:
            return int(v)
        except ValueError:
            messagebox.showwarning("Проверка", f"{field_name} должно быть целым числом.")
            return None


def main():
    try:
        db = DB(DB_CONFIG)
    except Exception as e:
        messagebox.showerror("Подключение к БД", f"Не удалось подключиться: {e}")
        return
    app = WarehouseApp(db)
    app.protocol("WM_DELETE_WINDOW", lambda: (db.close(), app.destroy()))
    app.mainloop()


if __name__ == "__main__":
    main()
