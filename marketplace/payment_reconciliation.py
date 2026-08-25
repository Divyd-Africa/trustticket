from django.db import transaction
from django.utils import timezone

from .models import Order


@transaction.atomic
def reconcile_collection_event(payload, allow_expired=False):
    """Apply a successful Bachs collection exactly once."""
    data = payload.get("data", payload) or {}
    metadata = data.get("metadata", {}) or {}
    event_type = str(payload.get("type", payload.get("event", data.get("status", "")))).lower()
    if not ("succeed" in event_type or event_type in {"accepted", "paid"}):
        return {"status": "ignored", "reason": "not a successful collection"}

    order_id = metadata.get("order_id") or data.get("order_id")
    if not order_id:
        return {"status": "ignored", "reason": "missing order_id"}

    # PostgreSQL cannot apply FOR UPDATE to the nullable side of the seller
    # outer join. Lock the order row first, then load related objects safely.
    order = Order.objects.select_for_update().filter(pk=order_id).first()
    if not order:
        return {"status": "ignored", "reason": f"order {order_id} not found"}
    order = Order.objects.select_related("listing__seller__profile").get(pk=order.pk)
    if order.status != "awaiting_payment":
        return {"status": "already_processed", "order_id": order.pk, "order_status": order.status}
    if order.reservation_expires_at and order.reservation_expires_at <= timezone.now() and not allow_expired:
        order.status = "refund_requested"
        order.payment_provider_response = payload
        order.save(update_fields=["status", "payment_provider_response", "updated_at"])
        return {"status": "refund_requested", "order_id": order.pk}

    order.status = "in_escrow"
    order.payment_reference = str(data.get("charge_id") or data.get("checkout_id") or data.get("reference") or "")
    order.payment_provider_response = payload
    order.save(update_fields=["status", "payment_reference", "payment_provider_response", "updated_at"])
    if order.listing.seller_id:
        profile = order.listing.seller.profile
        profile.pending_balance += order.total
        profile.save(update_fields=["pending_balance"])
    return {"status": "confirmed", "order_id": order.pk, "order": order}
