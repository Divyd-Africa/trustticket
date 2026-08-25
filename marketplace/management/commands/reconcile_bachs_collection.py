import json
import os

from django.core.management.base import BaseCommand

from marketplace.payment_reconciliation import reconcile_collection_event


class Command(BaseCommand):
    help = "Reconcile a successful Bachs collection event idempotently."

    def add_arguments(self, parser):
        parser.add_argument("--order-id", required=True)
        parser.add_argument("--charge-id", required=True)
        parser.add_argument("--checkout-id", default="")
        parser.add_argument("--reference", default="")
        parser.add_argument("--amount", required=True)
        parser.add_argument("--currency", default="NGN")
        parser.add_argument("--force", action="store_true", help="Accept a provider-confirmed payment even if the 15-minute reservation expired.")

    def handle(self, *args, **options):
        payload = {
            "id": f"manual-reconcile-{options['charge_id']}",
            "type": "collection.succeeded",
            "data": {
                "charge_id": options["charge_id"],
                "checkout_id": options["checkout_id"],
                "reference": options["reference"],
                "status": "SUCCEEDED",
                "amount": options["amount"],
                "currency": options["currency"],
                "metadata": {"order_id": options["order_id"]},
            },
        }
        result = reconcile_collection_event(payload, allow_expired=options["force"])
        if result.get("status") == "confirmed":
            order = result["order"]
            from marketplace.tasks import send_email_task
            public_url = os.environ.get("PUBLIC_APP_URL", "").rstrip("/")
            order_url = f"{public_url}/order/{order.pk}/?buyer_token={order.buyer_access_token}"
            send_email_task.delay(order.buyer_email, "Your TicketTrust payment is protected", "payment_received", {"title": order.listing.title, "order_url": order_url})
            send_email_task.delay(order.listing.seller_email, "Payment received — deliver the ticket", "payment_escrow_seller", {"title": order.listing.title, "order_url": order_url, "dashboard_url": f"{public_url}/dashboard/"})
        self.stdout.write(json.dumps({key: value for key, value in result.items() if key != "order"}, default=str))
