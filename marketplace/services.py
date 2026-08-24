import json
import os
import urllib.error
import urllib.request
import logging
import ssl
import secrets
import certifi
import cloudinary
import cloudinary.uploader
from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
FALLBACK_BANKS = [{"name": "Access Bank", "code": "044"}, {"name": "First Bank", "code": "011"}, {"name": "GTBank", "code": "058"}, {"name": "UBA", "code": "033"}, {"name": "Zenith Bank", "code": "057"}]

def _post(url, payload, token):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "TicketTrust/1.0"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=12, context=SSL_CONTEXT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        logger.error("Provider request failed: status=%s body=%s", error.code, body[:1000])
        raise RuntimeError(f"Provider rejected request ({error.code}): {body[:300]}") from error
    except urllib.error.URLError as error:
        logger.error("Provider connection failed: %s", error.reason)
        raise RuntimeError("Provider connection failed") from error

def send_email(to, subject, html):
    token = os.environ.get("SENDBYTE_API_KEY")
    if not token:
        return {"demo": True}
    base_url = os.environ.get("SENDBYTE_BASE_URL", "https://api.sendbyte.africa/v1").rstrip("/")
    email_url = os.environ.get("SENDBYTE_EMAIL_URL", f"{base_url}/emails")
    sender = os.environ.get("SENDBYTE_FROM_EMAIL", os.environ.get("SENDBYTE_FROM", "TicketTrust <hello@tickettrust.ng>"))
    return _post(email_url, {"from": sender, "to": to, "subject": subject, "html": html}, token)

def send_templated_email(to, subject, template, context):
    return send_email(to, subject, render_to_string(f"emails/{template}.html", context))

def upload_ticket_file(file_obj, order_id):
    cloudinary.config(cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"], api_key=os.environ["CLOUDINARY_API_KEY"], api_secret=os.environ["CLOUDINARY_API_SECRET"], secure=True)
    return cloudinary.uploader.upload(file_obj, resource_type="auto", folder="tickettrust/tickets", public_id=f"order-{order_id}-{secrets.token_hex(8)}", use_filename=False)

def _get(url, token):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "TicketTrust/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=12, context=SSL_CONTEXT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        logger.error("Provider request failed: status=%s body=%s", error.code, body[:1000])
        raise RuntimeError(f"Provider rejected request ({error.code}): {body[:300]}") from error

def create_checkout(order, request):
    token = os.environ.get("BACHS_API_KEY")
    public_base = os.environ.get("PUBLIC_APP_URL", "").rstrip("/")
    order_url = f"{public_base}/order/{order.pk}/" if public_base else request.build_absolute_uri(f"/order/{order.pk}/")
    if not token:
        return {"demo": True, "checkout_url": order_url}
    base = os.environ.get("BACHS_API_BASE", "https://sandbox-api.bachs.io").rstrip("/")
    payload = {"pricing": {"currency": "NGN", "amount": f"{order.total:.2f}"}, "customer": {"email": order.buyer_email, "name": order.buyer_name}, "success_url": f"{order_url}?paid=1", "cancel_url": f"{order_url}?cancelled=1", "expires_in_minutes": 15, "reference": f"tickettrust-order-{order.pk}", "metadata": {"order_id": str(order.pk)}}
    return _post(f"{base}/v1/checkout-sessions", payload, token)

def release_payout(order):
    token = os.environ.get("BACHS_API_KEY")
    account = None
    if order.listing.seller_id:
        account = order.listing.seller.profile.bank_accounts.filter(is_default=True).first()
    if token and account and account.bachs_destination_id:
        base = os.environ.get("BACHS_API_BASE", "https://sandbox-api.bachs.io").rstrip("/")
        source_currency = os.environ.get("BACHS_SOURCE_CURRENCY", "NGN")
        payout = {"destination": account.bachs_destination_id, "reference": f"tickettrust-order-{order.pk}"}
        if source_currency == "NGN":
            payout["amount"] = f"{order.total:.2f}"
        else:
            payout["quote_id"] = create_payout_quote(order.total, source_currency, "NGN")["quote_id"]
        return _post(f"{base}/v1/payouts", payout, token)
    url = os.environ.get("BACHS_PAYOUT_URL")
    if not url or not token:
        return {"demo": True}
    return _post(url, {"order_id": str(order.pk), "amount": str(order.total), "bank_code": account.bank_code if account else order.listing.seller_bank_code, "account_number": account.account_number if account else order.listing.seller_account_number, "metadata": {"listing_id": str(order.listing_id)}}, token)

def refund_payment(order):
    url, token = os.environ.get("BACHS_REFUND_URL"), os.environ.get("BACHS_API_KEY")
    if not url or not token:
        return {"demo": True}
    return _post(url, {"order_id": str(order.pk), "amount": str(order.total), "metadata": {"reason": "tickettrust_refund"}}, token)

def list_banks():
    bachs_token = os.environ.get("BACHS_API_KEY")
    if bachs_token:
        base = os.environ.get("BACHS_API_BASE", "https://sandbox-api.bachs.io").rstrip("/")
        try:
            data = _get(f"{base}/v1/reference/banks?country={os.environ.get('BACHS_COUNTRY', 'NG')}", bachs_token)
            return data.get("banks", [])
        except Exception:
            logger.exception("Bachs bank list unavailable; using temporary fallback")
            return FALLBACK_BANKS
    token = os.environ.get("BANK_API_KEY")
    url = os.environ.get("BANK_LIST_URL")
    if not token or not url:
        return FALLBACK_BANKS
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "TicketTrust/1.0"})
    with urllib.request.urlopen(request, timeout=12, context=SSL_CONTEXT) as response:
        data = json.loads(response.read())
    return data.get("data", data.get("banks", data))

def bank_name_for_code(code):
    return next((str(bank.get("name", bank.get("bank_name", ""))) for bank in list_banks() if str(bank.get("code", bank.get("bank_code", ""))) == str(code)), "Selected bank")

def resolve_bank(bank_code, account_number):
    bachs_token = os.environ.get("BACHS_API_KEY")
    if bachs_token:
        base = os.environ.get("BACHS_API_BASE", "https://sandbox-api.bachs.io").rstrip("/")
        data = _post(f"{base}/v1/misc/bank-accounts/resolve", {"account_number": account_number, "bank_code": bank_code, "country": os.environ.get("BACHS_COUNTRY", "NG")}, bachs_token)
        if data.get("resolved") is False:
            raise RuntimeError(data.get("message") or "Bachs could not resolve this account")
        return data
    token = os.environ.get("BANK_API_KEY")
    url = os.environ.get("BANK_RESOLVE_URL")
    if not token or not url:
        return {"account_name": "Demo Account Holder", "bank_code": bank_code, "account_number": account_number, "demo": True}
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(f"{url}{separator}bank_code={bank_code}&account_number={account_number}", headers={"Authorization": f"Bearer {token}", "User-Agent": "TicketTrust/1.0"})
    with urllib.request.urlopen(request, timeout=12, context=SSL_CONTEXT) as response:
        data = json.loads(response.read())
    return data.get("data", data)

def create_bachs_destination(bank_code, account_number, account_name):
    token = os.environ.get("BACHS_API_KEY")
    if not token:
        return {"demo": True}
    base = os.environ.get("BACHS_API_BASE", "https://sandbox-api.bachs.io").rstrip("/")
    return _post(f"{base}/v1/payouts/destinations", {"name": "TicketTrust payout account", "currency": "NGN", "type": "bank_account", "account_number": account_number, "bank_code": bank_code, "account_name": account_name}, token)

def create_payout_quote(amount, from_currency, to_currency="NGN"):
    token = os.environ.get("BACHS_API_KEY")
    if not token or from_currency == to_currency:
        return {"direct_amount": f"{amount:.2f}", "from_currency": from_currency, "to_currency": to_currency}
    base = os.environ.get("BACHS_API_BASE", "https://sandbox-api.bachs.io").rstrip("/")
    return _post(f"{base}/v1/payouts/quotes", {"from_currency": from_currency, "to_currency": to_currency, "amount": f"{amount:.2f}"}, token)
