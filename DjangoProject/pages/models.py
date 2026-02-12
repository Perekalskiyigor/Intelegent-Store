from django.db import models
import uuid

# ====== Справочники ======

class RefItem(models.Model):
    id = models.AutoField(primary_key=True)
    ext_id = models.TextField()                      # NOT NULL
    name = models.TextField(unique=True, null=True)  # в БД UNIQUE(name)
    bar_code = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "IH_ref_items"
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
        db_table = "IH_ref_size"
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
        db_table = "IH_tech_unit"
        managed = False

    def __str__(self):
        return f"TechUnit#{self.id} code={self.code}"


# ====== Локации склада ======

class Warehouse(models.Model):
    id = models.AutoField(primary_key=True)
    code = models.IntegerField(null=True, blank=True)
    name = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "IH_site"   # это та же таблица, что и у Site
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
        db_table = "IH_rack"
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
        db_table = "IH_bin_signal"
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
    ErrorSensor = models.BooleanField(db_column='"ErrorSensor"')

    class Meta:
        db_table = 'IH_bin'    # public.bin
        managed = False

    def __str__(self):
        return f"Bin#{self.id} addr={self.address} pos={self.position_no}"



#логи общие
class OpLog(models.Model):
    id = models.BigAutoField(primary_key=True, db_column="id")  # ← ДОБАВЬ

    created_at = models.DateTimeField(db_column="created_at")
    operation = models.TextField(db_column="operation")
    source = models.TextField(db_column="source")
    message = models.TextField(db_column="message")
    user = models.TextField(db_column="user", null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'IH_LOG'   # ← ВАЖНО: убери кавычки тут
        ordering = ["id"]

# Файлы
def select_upload_to(instance, filename: str) -> str:
    # кладём в отдельную папку и даём UUID имя
    ext = filename.split(".")[-1].lower()
    return f"uploads/select/{instance.uid}.{ext}"

class IHFileSelect(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "uploaded"
        PARSED   = "parsed", "parsed"
        ACTIVE   = "active", "active"
        ERROR    = "error", "error"
        ARCHIVED = "archived", "archived"

    # --- поля как в твоём SELECT ---
    original_name = models.TextField()
    sha256 = models.CharField(max_length=64, blank=True, null=True)     # char(64)
    size_bytes = models.BigIntegerField()

    uploaded_by = models.TextField(blank=True, null=True)
    workstation_id = models.TextField(blank=True, null=True)

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.UPLOADED,
    )

    error_text = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    parsed_at = models.DateTimeField(blank=True, null=True)

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    file = models.FileField(upload_to=select_upload_to, blank=True, null=True)
    stored_path = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'IH_File_Select'   # Django сам добавит schema public
        verbose_name = "IH File Select"
        verbose_name_plural = "IH File Select"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["uid"]),
            models.Index(fields=["sha256"]),
        ]

    def __str__(self) -> str:
        return f"{self.original_name} ({self.status})"