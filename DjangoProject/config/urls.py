from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView
from pages import views

# API
from pages.views import BinDetailView, ReelUpsertView



urlpatterns = [
    path('admin/', admin.site.urls),
    path('', TemplateView.as_view(template_name='index.html'), name='home'),
    path('inhra-settings/', views.inhra_settings, name='inhra-settings'),
    path('status/', views.status_view, name='status'),
    path("status/partial/", views.status_partial, name="status_partial"), # Таблица с ячейками
    path('about/', TemplateView.as_view(template_name='about.html'), name='about'),
    path('insert/', TemplateView.as_view(template_name='insert.html'), name='insert'),
    
    # Отвечает а публикацию
    path("logs/partial/", views.logs_partial, name="logs_partial"),

    # Кнопки размещениее
    path("ops/start-placement/", views.start_placement, name="start_placement"),
    path("logs/partial/", views.logs_partial, name="logs_partial"),

    # Отбор
    path('selection/', TemplateView.as_view(template_name='selection.html'), name='selection'), 
    path("ops/start-selection/", views.start_selection, name="start_selection"),

    # Инвентаризация
    path('inventarization/', TemplateView.as_view(template_name='inventarization.html'), name='inventarization'),
    path("ops/start-inventarization/", views.start_inventarization, name="start_inventarization"),

    # Тех обслуживание
    path('tech_maintance/', TemplateView.as_view(template_name='tech_maintance.html'), name='tech_maintance'),
    path("ops/start-tech_maintance/", views.start_tech_maintance, name="start_tech_maintance"),

    #Файлы
    path("select/", views.selection_page, name="selection_page"),
    path("select/file/upload/", views.upload_select_file, name="upload_select_file"),
    # опционально: partial со списком
    path("select/files/partial/", views.files_select_list, name="files_select_list"),


    
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


    ############################## API JSON ###############################################################

    path("api/v1/bins/<int:id>/", BinDetailView.as_view(), name="bin-detail"),
    path("api/v1/reels/upsert/", ReelUpsertView.as_view(), name="reels-upsert"),

    ############################## API JSON ###############################################################
]