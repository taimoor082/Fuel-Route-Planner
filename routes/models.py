from django.db import models


class FuelStation(models.Model):
    opis_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    retail_price = models.DecimalField(max_digits=6, decimal_places=3)
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
        ]

    def __str__(self):
        return f'{self.name} ({self.city}, {self.state})'
