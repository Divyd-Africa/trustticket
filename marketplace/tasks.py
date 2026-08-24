from celery import shared_task
from django.utils import timezone
from .models import Order
from .services import release_payout, send_templated_email

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_email_task(self, to, subject, template, context):
    return send_templated_email(to, subject, template, context)

@shared_task(bind=True)
def process_payout_task(self, order_id):
    order = Order.objects.select_related("listing__seller__profile").get(pk=order_id)
    if order.payout_status in {"paid", "processing"}:
        return {"status": order.payout_status}
    try:
        result = release_payout(order) or {}
    except Exception as error:
        order.payout_status = "failed"
        order.payout_error = str(error)[:1000]
        order.payout_initiated_at = timezone.now()
        order.save(update_fields=["payout_status", "payout_error", "payout_initiated_at", "updated_at"])
        if order.listing.seller_id:
            profile = order.listing.seller.profile
            profile.wallet_balance += order.total
            profile.save(update_fields=["wallet_balance"])
        return {"status": "failed", "error": str(error)}
    provider_status = str(result.get("status", result.get("payout_status", ""))).lower()
    payout_status = "paid" if provider_status in {"succeeded", "successful", "completed", "paid", "settled"} else "processing"
    order.payout_status = payout_status
    order.payout_reference = str(result.get("id", result.get("payout_id", result.get("reference", ""))))
    order.payout_amount = result.get("amount", order.total) or order.total
    order.payout_fee = result.get("fee", result.get("fees", 0)) or 0
    order.payout_response = result if isinstance(result, dict) else {"raw": str(result)}
    order.payout_initiated_at = timezone.now()
    if payout_status == "paid":
        order.payout_completed_at = timezone.now()
    order.save(update_fields=["payout_status", "payout_reference", "payout_amount", "payout_fee", "payout_response", "payout_initiated_at", "payout_completed_at", "updated_at"])
    send_email_task.delay(order.listing.seller_email, "Your TicketTrust payout is on the way", "payout_queued", {"title": order.listing.title})
    send_email_task.delay(order.buyer_email, "Ticket receipt confirmed", "receipt_confirmed", {"title": order.listing.title})
    return result
