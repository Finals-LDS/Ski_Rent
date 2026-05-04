from django.db import models


class AppSettings(models.Model):
    """Хранилище настроек приложения (ключ-значение)."""
    key   = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True, default='')
    note  = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name        = 'Настройка'
        verbose_name_plural = 'Настройки'

    def __str__(self):
        return self.key

    # ── helpers ──────────────────────────────────────────────────────────
    @classmethod
    def get(cls, key, default=''):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(cls, key, value, note=''):
        obj, _ = cls.objects.get_or_create(key=key)
        obj.value = value
        if note:
            obj.note = note
        obj.save()
        return obj
