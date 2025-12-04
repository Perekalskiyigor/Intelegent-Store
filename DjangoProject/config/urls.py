from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView
from pages import views



urlpatterns = [
    path('admin/', admin.site.urls),
    path('', TemplateView.as_view(template_name='index.html'), name='home'),
    path('inhra-settings/', views.inhra_settings, name='inhra-settings'),
    path('status/', views.status_view, name='status'),
    path('about/', TemplateView.as_view(template_name='about.html'), name='about'),

    path("warehouses/action/", views.warehouse_action, name="warehouse_action"),
    path("warehouses/add/", views.WarehouseCreateView.as_view(), name="warehouse_create"),
    path("warehouses/<int:pk>/edit/", views.WarehouseUpdateView.as_view(), name="warehouse_update"),
    path("warehouses/<int:pk>/delete/", views.WarehouseDeleteView.as_view(), name="warehouse_delete"),

    # стеллажи
    path("racks/action/", views.rack_action, name="rack_action"),
    path("warehouses/<int:warehouse_pk>/racks/add/", views.RackCreateView.as_view(), name="rack_create"),
    path("racks/<int:pk>/edit/", views.RackUpdateView.as_view(), name="rack_update"),
    path("racks/<int:pk>/delete/", views.RackDeleteView.as_view(), name="rack_delete"),

    # shelves
    path("shelves/action/", views.shelf_action, name="shelf_action"),
    path("racks/<int:rack_pk>/shelves/add/", views.ShelfCreateView.as_view(), name="shelf_create"),
    path("shelves/<int:pk>/edit/", views.ShelfUpdateView.as_view(), name="shelf_update"),
    path("shelves/<int:pk>/delete/", views.ShelfDeleteView.as_view(), name="shelf_delete"),

    # Ячейки
    path("bins/action/", views.bin_action, name="bin_action"),
    path("shelves/<int:shelf_pk>/bins/add/", views.BinCreateView.as_view(), name="bin_create"),
    path("bins/<int:pk>/edit/", views.BinUpdateView.as_view(), name="bin_update"),
    path("bins/<int:pk>/delete/", views.BinDeleteView.as_view(), name="bin_delete"),

    #path("sites/", views.site_list, name="site_list_raw"),
]