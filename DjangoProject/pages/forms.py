# app/forms.py
from django import forms
from .models import Warehouse
from .models import Rack
from .models import Shelf
from .models import Bin

class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name"]



##############ФОРМЫ СТЕЛАЖА

class RackForm(forms.ModelForm):
    class Meta:
        model = Rack
        fields = ["site", "code", "name"]


#####################ПОЛКА
class ShelfForm(forms.ModelForm):
    class Meta:
        model = Shelf
        fields = ["rack", "code", "level_no"]

#####################Ячейка
class BinForm(forms.ModelForm):
    class Meta:
        model = Bin
        fields = ["shelf", "address", "position_no"]