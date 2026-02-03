from datetime import timezone
from django.shortcuts import render, redirect
from django import forms as dj_forms
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView
from .models import Shelf, Rack, Warehouse, Bin, OpLog, IHFileSelect
from .forms import WarehouseForm
from .forms import RackForm  # см. ниже
from .forms import ShelfForm
from .forms import BinForm
from django.shortcuts import get_object_or_404
from django import forms
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST


# views.py
# views.py
def inhra_settings(request):
    warehouses = Warehouse.objects.order_by('-id')

    wid = request.GET.get('warehouse')
    selected_warehouse = Warehouse.objects.filter(pk=wid).first() if wid else None
    racks = Rack.objects.filter(site_id=wid).order_by('-id') if wid else Rack.objects.none()

    rid = request.GET.get('rack')
    selected_rack = Rack.objects.filter(pk=rid, site_id=wid).first() if (rid and wid) else None
    shelves = Shelf.objects.filter(rack_id=rid).order_by('-id') if rid else Shelf.objects.none()

    sid = request.GET.get('shelf')
    selected_shelf = Shelf.objects.filter(pk=sid, rack_id=rid).first() if (sid and rid) else None
    bins = Bin.objects.filter(shelf_id=sid).order_by('-id') if sid else Bin.objects.none()

    error = request.GET.get('error', '')

    return render(request, 'inhra-settings.html', {
        'warehouses': warehouses,
        'racks': racks,
        'shelves': shelves,
        'bins': bins,
        'selected_warehouse': selected_warehouse,
        'selected_warehouse_id': str(wid) if wid else '',
        'selected_rack': selected_rack,
        'selected_rack_id': str(rid) if rid else '',
        'selected_shelf': selected_shelf,
        'selected_shelf_id': str(sid) if sid else '',
        'error': error,
    })



def warehouse_action(request):
    """
    Принимает форму с селектом:
      - action=add    -> /warehouses/add/
      - action=edit   -> /warehouses/<id>/edit/
      - action=delete -> /warehouses/<id>/delete/
      - action=refresh -> назад на список
    """
    action = request.GET.get("action") or request.POST.get("action")
    wid = request.GET.get("id") or request.POST.get("id")

    if action == "add":
        return redirect("warehouse_create")

    if action in {"edit", "delete"}:
        if not wid:
            # вернёмся на список с сообщением
            url = reverse("inhra-settings") + "?error=Сначала+выберите+склад"
            return redirect(url)
        if action == "edit":
            return redirect("warehouse_update", pk=wid)
        else:
            return redirect("warehouse_delete", pk=wid)

    # refresh или неизвестное действие — просто назад на список
    return redirect("inhra-settings")

class WarehouseCreateView(CreateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = "warehouse_form.html"
    success_url = reverse_lazy("inhra-settings")

class WarehouseUpdateView(UpdateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = "warehouse_form.html"
    success_url = reverse_lazy("inhra-settings")

class WarehouseDeleteView(DeleteView):
    model = Warehouse
    template_name = "warehouse_confirm_delete.html"
    success_url = reverse_lazy("inhra-settings")


#############################СТЕЛАЖ
def rack_action(request):
    """
    Принимает форму с селектом:
      - action=add    + warehouse=<wid> -> /warehouses/<wid>/racks/add/
      - action=edit   + id=<rid>        -> /racks/<rid>/edit/
      - action=delete + id=<rid>        -> /racks/<rid>/delete/
      - action=refresh -> назад на список
    """
    action = request.GET.get("action") or request.POST.get("action")
    rid = request.GET.get("id") or request.POST.get("id")
    wid = request.GET.get("warehouse") or request.POST.get("warehouse")

    if action == "add":
        if not wid:
            url = reverse("inhra-settings") + "?error=Сначала+выберите+склад"
            return redirect(url)
        return redirect("rack_create", warehouse_pk=wid)

    if action in {"edit", "delete"}:
        if not rid:
            url = reverse("inhra-settings") + "?error=Сначала+выберите+стеллаж"
            return redirect(url)
        if action == "edit":
            return redirect("rack_update", pk=rid)
        else:
            return redirect("rack_delete", pk=rid)

    return redirect("inhra-settings")

class RackCreateView(CreateView):
    model = Rack
    form_class = RackForm
    template_name = "rack_form.html"

    def get_initial(self):
        initial = super().get_initial()
        initial["site"] = get_object_or_404(Warehouse, pk=self.kwargs["warehouse_pk"])
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["site"].widget = forms.HiddenInput()  # не даём менять склад в форме
        return form

    def form_valid(self, form):
        form.instance.site = get_object_or_404(Warehouse, pk=self.kwargs["warehouse_pk"])
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("inhra-settings")


class RackUpdateView(UpdateView):
    model = Rack
    form_class = RackForm
    template_name = "rack_form.html"
    success_url = reverse_lazy("inhra-settings")


class RackDeleteView(DeleteView):
    model = Rack
    template_name = "rack_confirm_delete.html"
    success_url = reverse_lazy("inhra-settings")



##########################ПОЛКА
# views.py
def shelf_action(request):
    """
    Ожидает:
      - action=add    + rack=<rack_id> -> /racks/<rack_id>/shelves/add/
      - action=edit   + id=<shelf_id>  -> /shelves/<id>/edit/
      - action=delete + id=<shelf_id>  -> /shelves/<id>/delete/
      - action=refresh -> назад на список
    """
    action = request.GET.get("action") or request.POST.get("action")
    sid = request.GET.get("id") or request.POST.get("id")
    rid = request.GET.get("rack") or request.POST.get("rack")

    if action == "add":
        if not rid:
            return redirect(reverse("inhra-settings") + "?error=Сначала+выберите+стеллаж (rack)")
        return redirect("shelf_create", rack_pk=rid)

    if action in {"edit", "delete"}:
        if not sid:
            return redirect(reverse("inhra-settings") + "?error=Сначала+выберите+полку")
        return redirect("shelf_update", pk=sid) if action == "edit" else redirect("shelf_delete", pk=sid)

    return redirect("inhra-settings")


class ShelfCreateView(CreateView):
    model = Shelf
    form_class = ShelfForm
    template_name = "shelf_form.html"

    def get_initial(self):
        initial = super().get_initial()
        initial["rack"] = get_object_or_404(Rack, pk=self.kwargs["rack_pk"])
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["rack"].widget = dj_forms.HiddenInput()
        return form

    def form_valid(self, form):
        form.instance.rack = get_object_or_404(Rack, pk=self.kwargs["rack_pk"])
        return super().form_valid(form)

    def get_success_url(self):
        # можно вернуть на общую страницу
        return reverse_lazy("inhra-settings")


class ShelfUpdateView(UpdateView):
    model = Shelf
    form_class = ShelfForm
    template_name = "shelf_form.html"
    success_url = reverse_lazy("inhra-settings")


class ShelfDeleteView(DeleteView):
    model = Shelf
    template_name = "shelf_confirm_delete.html"
    success_url = reverse_lazy("inhra-settings")


##########################Ячейка
def bin_action(request):
    """
    Ожидает:
      - action=add    + shelf=<shelf_id> -> /shelves/<shelf_id>/bins/add/
      - action=edit   + id=<bin_id>      -> /bins/<id>/edit/
      - action=delete + id=<bin_id>      -> /bins/<id>/delete/
      - action=refresh -> назад на список (с сохранением контекста)
    """
    action = request.GET.get("action") or request.POST.get("action")
    bid = request.GET.get("id") or request.POST.get("id")
    sid = request.GET.get("shelf") or request.POST.get("shelf")
    rid = request.GET.get("rack") or request.POST.get("rack")
    wid = request.GET.get("warehouse") or request.POST.get("warehouse")

    if action == "add":
        if not sid:
            return redirect(reverse("inhra-settings") + "?error=Сначала+выберите+полку")
        return redirect("bin_create", shelf_pk=sid)

    if action in {"edit", "delete"}:
        if not bid:
            return redirect(reverse("inhra-settings") + "?error=Сначала+выберите+ячейку")
        return redirect("bin_update", pk=bid) if action == "edit" else redirect("bin_delete", pk=bid)

    # refresh -> вернуться с тем же контекстом
    qs = []
    if wid: qs.append(f"warehouse={wid}")
    if rid: qs.append(f"rack={rid}")
    if sid: qs.append(f"shelf={sid}")
    url = reverse("inhra-settings") + (("?" + "&".join(qs)) if qs else "")
    return redirect(url)


class BinCreateView(CreateView):
    model = Bin
    form_class = BinForm
    template_name = "bin_form.html"

    def get_initial(self):
        initial = super().get_initial()
        initial["shelf"] = get_object_or_404(Shelf, pk=self.kwargs["shelf_pk"])
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["shelf"].widget = dj_forms.HiddenInput()
        return form

    def form_valid(self, form):
        form.instance.shelf = get_object_or_404(Shelf, pk=self.kwargs["shelf_pk"])
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("inhra-settings")


class BinUpdateView(UpdateView):
    model = Bin
    form_class = BinForm
    template_name = "bin_form.html"
    success_url = reverse_lazy("inhra-settings")


class BinDeleteView(DeleteView):
    model = Bin
    template_name = "bin_confirm_delete.html"
    success_url = reverse_lazy("inhra-settings")

from collections import defaultdict
from django.shortcuts import render

def build_status_rows(COLS=100):
    bins = (
        Bin.objects
        .select_related("ref_item")
        .order_by("shelf_id", "id")
    )

    by_shelf = defaultdict(list)
    for b in bins:
        by_shelf[b.shelf_id].append(b)

    rows = []
    for shelf_id in sorted(by_shelf.keys()):
        cells = [{"css": "bg-white", "text": ""} for _ in range(COLS)]

        for idx, b in enumerate(by_shelf[shelf_id][:COLS]):
            text = b.ref_item.name if b.ref_item_id and b.ref_item else ""

            err = getattr(b, "ErrorSensor", None)
            if err is None:
                err = getattr(b, "error_sensor", False)

            if err:
                css = "bg-danger text-white"
            elif b.ref_item_id is not None:
                css = "bg-success text-white"
            else:
                css = "bg-white"

            cells[idx] = {"css": css, "text": text}

        rows.append({"shelf_id": shelf_id, "cells": cells})

    return rows

def status_view(request):
    COLS = 100
    rows = build_status_rows(COLS)

    return render(
        request,
        "status.html",
        {"rows": rows, "cols": range(1, COLS + 1)},
    )

def status_partial(request):
    COLS = 100
    rows = build_status_rows(COLS)

    return render(
        request,
        "partials/_status_table.html",
        {"rows": rows, "cols": range(1, COLS + 1)},
    )

#############################3кнопка размещения#############################
import threading
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from .models import OpLog

@csrf_exempt
def start_placement(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    # ленивый импорт — чтобы views.py не падал при старте проекта
    from pages.services.placement import run_placement

    def worker():
        try:
            run_placement()
        except Exception as e:
            # писать ошибку в БД логом:
            from pages.services import logInsert
            logInsert.ih_log(f"Ошибка вызова скрипта размещения из Django view start_placement(request): {e}", operation="PLACEMENT", source="django", user="ivanov")

    threading.Thread(target=worker, daemon=True).start()
    return JsonResponse({"ok": True})

#############################3кнопка размещения#############################


#############################Табица с логом#############################

# Логи в строку состяния
def logs_partial(request):
    logs = OpLog.objects.order_by("-id")[:200]
    logs = reversed(list(logs))
    return render(request, "partials/_op_logs.html", {"logs": logs})
#############################Табица с логом#############################


#############################3кнопка Selection#############################
import threading
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from .models import OpLog

from django.views.decorators.csrf import ensure_csrf_cookie

@ensure_csrf_cookie
def selection_page(request):
    current_file = IHFileSelect.objects.order_by("-created_at").first()
    return render(request, "selection.html", {"current_file": current_file})

@csrf_exempt
def start_selection(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    current_file = IHFileSelect.objects.order_by("-created_at").first()
    if not current_file:
        return JsonResponse({"ok": False, "error": "Текущий файл не выбран"}, status=400)

    # В зависимости от модели: current_file.file.path / current_file.file_path и т.п.
    # Ниже — самый частый вариант, если FileField:
    try:
        file_path = current_file.file.path
    except Exception:
        # если у тебя строковое поле с путем:
        file_path = getattr(current_file, "file_path", None)

    if not file_path:
        return JsonResponse({"ok": False, "error": "У текущего файла не найден путь"}, status=400)

    # ленивый импорт — чтобы views.py не падал при старте проекта
    from pages.services.selection import run_selection
    from pages.services import logInsert

    user = getattr(request, "user", None)
    username = getattr(user, "username", None) or "ivanov"

    def worker():
        try:
            logInsert.ih_log(
                f"Старт отбора по файлу: {current_file.original_name if hasattr(current_file,'original_name') else current_file} ({file_path})",
                operation="SELECTION",
                source="django",
                user=username,
            )
            run_selection(file_path=file_path, file_id=current_file.id, user=username)
        except Exception as e:
            logInsert.ih_log(
                f"Ошибка вызова скрипта отбора из Django view start_selection(): {e}",
                operation="SELECTION",
                source="django",
                user=username,
            )

    threading.Thread(target=worker, daemon=True).start()
    return JsonResponse({"ok": True, "file_id": current_file.id})

#############################3кнопка размещения#############################


#############################3кнопка Inventarization#############################
import threading
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from .models import OpLog

@csrf_exempt
def start_inventarization(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    # ленивый импорт — чтобы views.py не падал при старте проекта
    from pages.services.inventarization import run_inventarization

    def worker():
        try:
            run_inventarization()
        except Exception as e:
            # писать ошибку в БД логом:
            from pages.services import logInsert
            logInsert.ih_log(f"Ошибка вызова скрипта инвентаризации из Django view start_inventarization(request): {e}", operation="INVENTAR", source="django", user="ivanov")

    threading.Thread(target=worker, daemon=True).start()
    return JsonResponse({"ok": True})

#############################3кнопка размещения#############################



#############################3кнопка tech_maintance#############################
import threading
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from .models import OpLog

@csrf_exempt
def start_tech_maintance(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    # ленивый импорт — чтобы views.py не падал при старте проекта
    from pages.services.tech_maintance import run_tech_maintance

    def worker():
        try:
            run_tech_maintance()
        except Exception as e:
            # писать ошибку в БД логом:
            from pages.services import logInsert
            logInsert.ih_log(f"Ошибка вызова скрипта инвентаризации из Django view start_tech_maintance(request): {e}", operation="TECH", source="django", user="ivanov")

    threading.Thread(target=worker, daemon=True).start()
    return JsonResponse({"ok": True})

#############################3кнопка размещения#############################



#############################Файлы данных#############################
import os
import hashlib
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest

@csrf_exempt
@require_POST
def selection_page(request):
    """
    Страница отбора.
    Покажем последний загруженный файл.
    """
    current_file = IHFileSelect.objects.order_by("-created_at").first()
    return render(request, "selection.html", {"current_file": current_file})


@csrf_exempt
@require_POST
def upload_select_file(request):
    """
    Принимаем XLSX, сохраняем на диск с UUID именем,
    пишем метаданные в IH_File_Select.
    """
    f = request.FILES.get("file")
    if not f:
        return HttpResponseBadRequest("no file")

    if not f.name.lower().endswith(".xlsx"):
        return HttpResponseBadRequest("only .xlsx allowed")

    # подготовка папки
    rel_dir = "uploads/xlsx"
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    # создаём запись (uid генерится автоматически)
    obj = IHFileSelect(
        original_name=f.name,
        size_bytes=f.size,
        uploaded_by=request.user.username if getattr(request, "user", None) and request.user.is_authenticated else None,
        workstation_id=request.POST.get("workstation_id") or None,
        status=IHFileSelect.Status.UPLOADED,
        error_text=None,
    )

    # посчитаем sha256 и одновременно сохраним файл
    # (файл может быть большой → читаем chunks)
    sha = hashlib.sha256()
    abs_path = None
    rel_path = None

    # uid доступен только после obj.uid (он уже есть по default uuid4)
    rel_path = f"{rel_dir}/{obj.uid}.xlsx"
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)

    try:
        with open(abs_path, "wb") as out:
            for chunk in f.chunks():
                sha.update(chunk)
                out.write(chunk)
    except Exception as e:
        return HttpResponseBadRequest(f"save failed: {e}")

    obj.sha256 = sha.hexdigest()
    obj.stored_path = rel_path

    # сохраняем в БД
    obj.save()

    return JsonResponse({
        "ok": True,
        "id": obj.id,
        "uid": str(obj.uid),
        "original_name": obj.original_name,
        "stored_path": obj.stored_path,
        "sha256": obj.sha256,
        "size_bytes": obj.size_bytes,
        "status": obj.status,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
    })


def files_select_list(request):
    """
    Если хочешь страницу/эндпоинт списка файлов (для UI).
    Можно потом сделать partial.
    """
    files = IHFileSelect.objects.order_by("-created_at")[:50]
    return render(request, "partials/_select_files.html", {"files": files})


#############################Файлы данных#############################