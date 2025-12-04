from django.db import models


# ====== Справочники ======

class RefItem(models.Model):
    id = models.AutoField(primary_key=True)
    ext_id = models.TextField()                      # NOT NULL
    name = models.TextField(unique=True, null=True)  # в БД UNIQUE(name)
    bar_code = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ref_items"
        managed = False

    def __str__(self):
        return self.name or f"Item#{self.id}"


class RefSize(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.TextField()              # NOT NULL
    ext_id = models.TextField(null=True, blank=True)
    item = models.ForeignKey(
        RefItem,
        db_column="item_id",
        to_field="id",
        on_delete=models.DO_NOTHING,       # в БД ON DELETE NO ACTION
        related_name="sizes",
        null=True,                          # в схеме FK необязательный
        blank=True,
    )

    class Meta:
        db_table = "ref_size"
        managed = False


class TechUnit(models.Model):
    id = models.AutoField(primary_key=True)
    code = models.IntegerField(null=True, blank=True)
    item = models.ForeignKey(
        RefItem,
        db_column="item_id",
        to_field="id",
        on_delete=models.DO_NOTHING,       # NO ACTION
        related_name="tech_units",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "tech_unit"
        managed = False

    def __str__(self):
        return f"TechUnit#{self.id} code={self.code}"


# ====== Локации склада ======

class Warehouse(models.Model):
    id = models.AutoField(primary_key=True)
    code = models.IntegerField(null=True, blank=True)
    name = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "site"   # это та же таблица, что и у Site
        managed = False

    def __str__(self):
        return self.name or f"Site#{self.id}"


class Rack(models.Model):
    id = models.AutoField(primary_key=True)
    site = models.ForeignKey(
        Warehouse,
        db_column="site_id",
        to_field="id",
        on_delete=models.DO_NOTHING,       # NO ACTION
        related_name="racks",
        null=True,
        blank=True,
    )
    code = models.TextField(null=True, blank=True)
    name = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "rack"
        managed = False

    def __str__(self):
        return self.name or f"Rack#{self.id}"


class Shelf(models.Model):
    id = models.AutoField(primary_key=True)
    rack = models.ForeignKey(
        Rack,
        db_column="rack_id",
        to_field="id",
        on_delete=models.DO_NOTHING,       # NO ACTION
        related_name="shelves",
        null=True,
        blank=True,
    )
    code = models.IntegerField(null=True, blank=True)
    level_no = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "shelf"
        managed = False

    def __str__(self):
        return f"Shelf#{self.id} (level {self.level_no})"


# ====== Режимы индикации ячейки ======

class BinSignal(models.Model):
    # В БД: GENERATED ALWAYS AS IDENTITY (integer) → AutoField подходит
    id = models.AutoField(primary_key=True)
    led_color = models.TextField(db_column="ledColor", null=True, blank=True)
    mode_blynk = models.TextField(db_column="modeBlynk", null=True, blank=True)
    created_add = models.DateField(db_column="createdAdd", null=True, blank=True)

    class Meta:
        db_table = "bin_signal"
        managed = False

    def __str__(self):
        return f"BinSignal#{self.id} {self.led_color}/{self.mode_blynk}"


# ====== Ячейка (бункер) ======

class Bin(models.Model):
    id = models.AutoField(primary_key=True)
    shelf = models.ForeignKey(
        Shelf,
        db_column="shelf_id",
        to_field="id",
        on_delete=models.DO_NOTHING,       # В БД: NO ACTION
        related_name="bins",
        null=True,                          # в CREATE TABLE поле необязательное
        blank=True,
    )
    # В БД address = integer → меняем CharField на IntegerField
    address = models.IntegerField(null=True, blank=True)

    position_no = models.IntegerField(null=True, blank=True)

    # Новые связи из схемы:
    mode = models.ForeignKey(
        BinSignal,
        db_column="mode_id",
        to_field="id",
        on_delete=models.DO_NOTHING,       # NO ACTION
        related_name="bins",
        null=True,
        blank=True,
    )
    ref_item = models.ForeignKey(
        RefItem,
        db_column="ref_item_id",
        to_field="id",
        on_delete=models.DO_NOTHING,       # NO ACTION
        related_name="bins",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "bin"    # public.bin
        managed = False

    def __str__(self):
        return f"Bin#{self.id} addr={self.address} pos={self.position_no}"
