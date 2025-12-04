from django.shortcuts import render, redirect
from django import forms as dj_forms
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView
from .models import Shelf, Rack, Warehouse, Bin
from .forms import WarehouseForm
from .forms import RackForm  # см. ниже
from .forms import ShelfForm
from .forms import BinForm
from django.shortcuts import get_object_or_404
from django import forms


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

# Страница со статусами

def status_view(request):
    COLS = 10
    shelves = (
        Shelf.objects
        .prefetch_related('bins__ref_item', 'bins__mode')
        .order_by('level_no', 'id')
    )

    rows = []
    for shelf in shelves:
        # подготовим 10 пустых ячеек по умолчанию
        cells = [{"css": "bg-white", "text": ""} for _ in range(COLS)]

        for b in shelf.bins.all():
            # колонка = Bin.id (1..10). всё остальное игнорируем
            if not b.id:
                continue
            col_idx = b.id - 1
            if col_idx < 0 or col_idx >= COLS:
                continue

            # текст
            text = ""
            if b.ref_item_id is not None and getattr(b, "ref_item", None):
                text = b.ref_item.name or ""

            # цвет
            if b.mode_id == 1:
                css = "bg-success text-white"
            elif b.mode_id == 2:
                css = "bg-danger text-white"
            elif b.mode_id == 3:
                css = "bg-light text-body"  # светло-серый
            else:
                css = "bg-white"

            cells[col_idx] = {"css": css, "text": text}

        rows.append({"shelf": shelf, "cells": cells})

    ctx = {
        "rows": rows,
        "cols": range(1, COLS + 1),
    }
    return render(request, "status.html", ctx)
