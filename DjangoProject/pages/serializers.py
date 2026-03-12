from rest_framework import serializers
from .models import Bin, RefItem, RefSize

# Сериалайзер для размеров
class RefSizeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RefSize
        fields = ["id", "size", "size_name", "size_code", "ext_id"]


# Сериалайзер для товара + вложенный список sizes
class RefItemSerializer(serializers.ModelSerializer):
    sizes = RefSizeSerializer(many=True, read_only=True)  # <-- item.sizes.all()

    class Meta:
        model = RefItem
        fields = [
            "id", "ext_id", "name", "bar_code", "manufactor", "qwantity",
            "sizes", "dropped"
        ]

# Сериалайзер для Bin + вложенный ref_item
class BinSerializer(serializers.ModelSerializer):
    ref_item = RefItemSerializer(read_only=True)
    class Meta:
        model = Bin
        fields = "__all__"


#### АПИ вставки в справочник

class ReelUpsertInSerializer(serializers.Serializer):
    carrier_no = serializers.CharField()
    series_no = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    item_code = serializers.CharField()
    item_name = serializers.CharField()
    uom = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    qty_units = serializers.IntegerField(required=False, default=0)

    reel_diam = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    reel_width = serializers.FloatField(required=False, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    dropped = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        for k in attrs:
            if isinstance(attrs[k], str):
                attrs[k] = attrs[k].strip()
        return attrs