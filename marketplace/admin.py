from django.contrib import admin
from .models import BachsWebhookDelivery, Listing, Order

@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "event_date", "price", "status", "seller_name")
    list_filter = ("status", "city")

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "buyer_name", "status", "updated_at")
    list_filter = ("status",)

@admin.register(BachsWebhookDelivery)
class BachsWebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "event_id", "status", "signature_valid", "order")
    list_filter = ("status", "signature_valid", "event_type")
    readonly_fields = ("created_at", "processed_at")
