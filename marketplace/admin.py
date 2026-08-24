from django.contrib import admin
from .models import Listing, Order

@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "event_date", "price", "status", "seller_name")
    list_filter = ("status", "city")

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "buyer_name", "status", "updated_at")
    list_filter = ("status",)
