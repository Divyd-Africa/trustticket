from django.db import transaction
from django.utils import timezone
from .models import Order

@transaction.atomic
def release_expired_reservations():
    now = timezone.now()
    orders = list(Order.objects.select_for_update().select_related("listing").filter(status="awaiting_payment", reservation_expires_at__lte=now))
    released = 0
    for order in orders:
        order.status = "expired"
        order.save(update_fields=["status", "updated_at"])
        listing = order.listing
        listing.available_quantity = min(listing.quantity, listing.available_quantity + 1)
        listing.status = "available" if listing.available_quantity > 0 else "reserved"
        listing.save(update_fields=["available_quantity", "status"])
        released += 1
    return released
