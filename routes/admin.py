from django.contrib import admin

from routes.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ('opis_id', 'name', 'city', 'state', 'retail_price')
    list_filter = ('state',)
    search_fields = ('name', 'city')
