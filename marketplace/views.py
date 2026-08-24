import hashlib
import hmac
import json
import os
import secrets
from random import randint
from datetime import timedelta
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .models import BankAccount, EmailOTP, ExchangeLink, Listing, Order, Profile, TicketAttachment
from .reservations import release_expired_reservations
from .services import bank_name_for_code, create_bachs_destination, create_checkout, list_banks, refund_payment, resolve_bank, upload_ticket_file

def send_templated_email(to, subject, template, context):
    from .tasks import send_email_task
    return send_email_task.delay(to, subject, template, context)

def register(request):
    if request.method == "POST":
        data = request.POST
        if User.objects.filter(username=data["email"].lower()).exists():
            messages.error(request, "An account with that email already exists.")
            return render(request, "marketplace/register.html")
        user = User.objects.create_user(username=data["email"].lower(), email=data["email"].lower(), password=data["password"], first_name=data["name"])
        Profile.objects.create(user=user, phone=data["phone"], social_link=data.get("social_link", ""))
        code = f"{randint(0, 999999):06d}"
        EmailOTP.objects.create(user=user, code=code, expires_at=timezone.now() + timedelta(minutes=10))
        try:
            send_templated_email(user.email, "Your TicketTrust verification code", "verify", {"code": code})
        except Exception as error:
            messages.error(request, f"SendByte rejected the verification email: {str(error)[:220]}")
        request.session["verify_user_id"] = user.pk
        return redirect("verify_email")
    return render(request, "marketplace/register.html")

def verify_email(request):
    user_id = request.session.get("verify_user_id")
    user = get_object_or_404(User, pk=user_id) if user_id else None
    if request.method == "POST" and user:
        otp = EmailOTP.objects.filter(user=user, code=request.POST["code"], used=False, expires_at__gte=timezone.now()).first()
        if otp:
            otp.used = True; otp.save(update_fields=["used"])
            user.profile.email_verified = True; user.profile.save(update_fields=["email_verified"])
            login(request, user); messages.success(request, "Email verified. Welcome to TicketTrust.")
            return redirect("dashboard")
        messages.error(request, "That code is invalid or expired.")
    return render(request, "marketplace/verify_email.html", {"email": user.email if user else ""})

def resend_otp(request):
    user_id = request.session.get("verify_user_id")
    user = get_object_or_404(User, pk=user_id) if user_id else None
    if not user:
        return redirect("register")
    EmailOTP.objects.filter(user=user, used=False).update(used=True)
    code = f"{randint(0, 999999):06d}"
    EmailOTP.objects.create(user=user, code=code, expires_at=timezone.now() + timedelta(minutes=10))
    try:
        send_templated_email(user.email, "Your new TicketTrust verification code", "verify", {"code": code})
        messages.success(request, "A new verification code has been sent.")
    except Exception as error:
        messages.error(request, f"SendByte rejected the email: {str(error)[:220]}")
    return redirect("verify_email")

def sign_in(request):
    if request.method == "POST":
        user = authenticate(request, username=request.POST["email"].lower(), password=request.POST["password"])
        if user:
            login(request, user); return redirect(request.GET.get("next", "dashboard"))
        messages.error(request, "Email or password is incorrect.")
    return render(request, "marketplace/login.html")

def sign_out(request):
    logout(request); return redirect("home")

@login_required
def dashboard(request):
    listings = request.user.listings.all()
    orders = Order.objects.filter(listing__seller=request.user).select_related("listing")
    return render(request, "marketplace/dashboard_v3.html", {"listings": listings, "orders": orders, "profile": request.user.profile})

@login_required
def bank_account(request):
    if request.method == "POST":
        try:
            resolved = resolve_bank(request.POST["bank_code"], request.POST["account_number"])
            account_name = resolved.get("account_name", request.POST["account_name"])
            destination = create_bachs_destination(request.POST["bank_code"], request.POST["account_number"], account_name)
            BankAccount.objects.update_or_create(profile=request.user.profile, is_default=True, defaults={"bank_name": bank_name_for_code(request.POST["bank_code"]), "bank_code": request.POST["bank_code"], "account_number": request.POST["account_number"], "account_name": account_name, "verified": True, "bachs_destination_id": destination.get("id", ""), "bachs_destination_status": destination.get("status", "")})
            messages.success(request, "Payout account saved and verified.")
            return redirect("dashboard")
        except Exception as error:
            messages.error(request, f"Bachs could not verify this payout account: {str(error)[:220]}")
    return render(request, "marketplace/bank_account.html", {"banks": list_banks(), "account": request.user.profile.bank_accounts.filter(is_default=True).first()})

def create_exchange(request):
    if request.method == "POST":
        resolved = resolve_bank(request.POST["seller_bank_code"], request.POST["seller_account_number"])
        link = ExchangeLink.objects.create(token=secrets.token_urlsafe(24), seller_name=request.POST["seller_name"], seller_email=request.POST["seller_email"], seller_phone=request.POST["seller_phone"], seller_bank_name=bank_name_for_code(request.POST["seller_bank_code"]), seller_bank_code=request.POST["seller_bank_code"], seller_account_number=request.POST["seller_account_number"], title=request.POST["title"], price=request.POST["price"], event_date=request.POST["event_date"])
        return render(request, "marketplace/exchange_created.html", {"link": link, "share_url": request.build_absolute_uri(f"/exchange/{link.token}/")})
    return render(request, "marketplace/exchange_create.html", {"banks": list_banks()})

def exchange_detail(request, token):
    link = get_object_or_404(ExchangeLink, token=token)
    if request.method == "POST" and link.status == "open":
        link.buyer_name = request.POST["buyer_name"]; link.buyer_email = request.POST["buyer_email"]; link.buyer_phone = request.POST["buyer_phone"]; link.status = "paid"; link.save(update_fields=["buyer_name", "buyer_email", "buyer_phone", "status"])
        send_templated_email(link.seller_email, "Someone wants to buy your ticket", "buyer_request", {"buyer_name": link.buyer_name, "title": link.title, "dashboard_url": request.build_absolute_uri("/dashboard/")})
        send_templated_email(link.buyer_email, "TicketTrust payment received", "payment_received", {"title": link.title, "order_url": request.build_absolute_uri()})
        messages.success(request, "Payment recorded in protected escrow. Check your email for next steps.")
    return render(request, "marketplace/exchange_detail.html", {"link": link})

@csrf_exempt
def bachs_webhook(request):
    if request.method != "POST":
        return JsonResponse({"detail": "POST required"}, status=405)
    secret = os.environ.get("BACHS_WEBHOOK_SECRET", "")
    supplied = request.headers.get("X-Bachs-Signature", request.headers.get("X-Webhook-Signature", ""))
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest() if secret else ""
    if not secret or not supplied or not hmac.compare_digest(supplied, expected):
        return JsonResponse({"detail": "Invalid signature"}, status=401)
    payload = json.loads(request.body or "{}")
    data = payload.get("data", payload)
    metadata = data.get("metadata", {}) or {}
    order_id = metadata.get("order_id") or data.get("order_id")
    if order_id:
        order = Order.objects.filter(pk=order_id).first()
        event = str(payload.get("type", payload.get("event", data.get("status", "")))).lower()
        payment_confirmed = False
        if order and ("succeed" in event or event in {"accepted", "paid"}):
            if order.status == "awaiting_payment" and order.reservation_expires_at and order.reservation_expires_at > timezone.now():
                order.status = "in_escrow"; order.payment_reference = str(data.get("id", data.get("reference", ""))); order.save(update_fields=["status", "payment_reference", "updated_at"])
                if order.listing.seller_id:
                    profile = order.listing.seller.profile
                    profile.pending_balance += order.total
                    profile.save(update_fields=["pending_balance"])
                payment_confirmed = True
            elif order.status == "awaiting_payment":
                order.status = "refund_requested"; order.save(update_fields=["status", "updated_at"])
        elif order and "refund" in event:
            order.status = "refunded"; order.save(update_fields=["status", "updated_at"])
        if payment_confirmed:
            order_url = request.build_absolute_uri(f"/order/{order.pk}/?buyer_token={order.buyer_access_token}")
            try:
                send_templated_email(order.buyer_email, "Your TicketTrust payment is protected", "payment_received", {"title": order.listing.title, "order_url": order_url})
            except Exception:
                pass
            try:
                send_templated_email(order.listing.seller_email, "Payment received — deliver the ticket", "payment_escrow_seller", {"title": order.listing.title, "order_url": order_url, "dashboard_url": request.build_absolute_uri("/dashboard/")})
            except Exception:
                pass
    return JsonResponse({"received": True})

def home(request):
    listings = Listing.objects.filter(status="available", event_date__gte=timezone.now())
    return render(request, "marketplace/home.html", {"listings": listings})

def sell(request):
    if request.method == "POST":
        data = request.POST
        if request.user.is_authenticated:
            profile = request.user.profile
            account = profile.bank_accounts.filter(is_default=True).first()
            if not account:
                messages.error(request, "Add a verified payout account before creating a listing.")
                return redirect("bank_account")
            seller_name, seller_email = request.user.get_full_name() or request.user.first_name, request.user.email
            bank_code = account.bank_code if account else ""
            account_number = account.account_number if account else ""
            account_name = account.account_name if account else ""
            bank_name = account.bank_name if account else ""
        else:
            resolved = resolve_bank(data["seller_bank_code"], data["seller_account_number"])
            seller_name, seller_email = data["seller_name"], data["seller_email"]
            bank_code, account_number = data["seller_bank_code"], data["seller_account_number"]
            account_name, bank_name = resolved.get("account_name", data.get("seller_account_name", "")), bank_name_for_code(data["seller_bank_code"])
        listing = Listing.objects.create(seller=request.user if request.user.is_authenticated else None, title=data["title"], venue=data["venue"], city=data["city"], event_date=data["event_date"], ticket_type=data["ticket_type"], quantity=data["quantity"], available_quantity=data["quantity"], price=data["price"], description=data.get("description", ""), delivery_note=data["delivery_note"], seller_name=seller_name, seller_email=seller_email, seller_bank=bank_name, seller_bank_code=bank_code, seller_account_number=account_number, seller_account_name=account_name)
        messages.success(request, "Your listing is live. Buyers will see that funds are protected until delivery is confirmed.")
        return redirect("listing_detail", pk=listing.pk)
    return render(request, "marketplace/sell.html", {"banks": list_banks(), "account": request.user.profile.bank_accounts.filter(is_default=True).first() if request.user.is_authenticated else None})

def listing_detail(request, pk):
    return render(request, "marketplace/listing_detail.html", {"listing": get_object_or_404(Listing, pk=pk)})

@transaction.atomic
def buy(request, pk):
    release_expired_reservations()
    listing = get_object_or_404(Listing.objects.select_for_update(), pk=pk)
    if request.user.is_authenticated and listing.seller_id == request.user.id:
        messages.error(request, "You cannot buy your own listing.")
        return redirect("listing_detail", pk=listing.pk)
    if listing.status == "sold" or listing.available_quantity < 1:
        messages.error(request, "Sorry, this ticket is no longer available.")
        return redirect("listing_detail", pk=listing.pk)
    if request.method == "POST":
        hold_until = timezone.now() + timedelta(minutes=15)
        order = Order.objects.create(listing=listing, buyer=request.user if request.user.is_authenticated else None, buyer_name=request.POST["buyer_name"], buyer_email=request.POST["buyer_email"], status="awaiting_payment", payment_expires_at=hold_until, reservation_expires_at=hold_until)
        listing.available_quantity -= 1
        listing.status = "reserved" if listing.available_quantity == 0 else "available"
        listing.save(update_fields=["available_quantity", "status"])
        checkout = create_checkout(order, request)
        checkout_url = checkout.get("checkout_url") or checkout.get("url")
        if checkout_url and not checkout.get("demo"):
            return redirect(checkout_url)
        messages.success(request, "Ticket held for 15 minutes. Complete payment before the hold expires.")
        return redirect("order_detail", pk=order.pk)
    return render(request, "marketplace/buy.html", {"listing": listing})

def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    buyer_view = request.GET.get("buyer_token") == str(order.buyer_access_token) or (request.user.is_authenticated and order.buyer_id == request.user.id)
    return render(request, "marketplace/order_detail_v5.html", {"order": order, "buyer_view": buyer_view})

def deliver_ticket(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method == "POST" and order.status == "in_escrow" and order.listing.seller_id == request.user.id:
        ticket_details = request.POST.get("ticket_details", "").strip()
        uploaded_files = request.FILES.getlist("ticket_files")
        if not uploaded_files and request.FILES.get("ticket_file"):
            uploaded_files = [request.FILES["ticket_file"]]
        if not ticket_details and not uploaded:
            messages.error(request, "Add ticket details or upload the ticket file before marking it as sent.")
            return redirect("order_detail", pk=pk)
        if uploaded_files:
            try:
                for uploaded in uploaded_files:
                    result = upload_ticket_file(uploaded, order.pk)
                    file_url = result.get("secure_url", result.get("url", ""))
                    TicketAttachment.objects.create(order=order, file_url=file_url, file_name=uploaded.name, file_type=uploaded.content_type or "application/octet-stream")
                    if not order.ticket_file_url:
                        order.ticket_file_url = file_url
                        order.ticket_file_name = uploaded.name
                        order.ticket_file_type = uploaded.content_type or "application/octet-stream"
            except Exception as error:
                messages.error(request, f"Ticket upload failed: {str(error)[:180]}")
                return redirect("order_detail", pk=pk)
        order.ticket_details = ticket_details
        order.status = "delivered"
        order.save(update_fields=["ticket_details", "ticket_file_url", "ticket_file_name", "ticket_file_type", "status", "updated_at"])
        order_url = request.build_absolute_uri(f"/order/{order.pk}/?buyer_token={order.buyer_access_token}")
        send_templated_email(order.buyer_email, "Your ticket has been sent", "ticket_delivered", {"title": order.listing.title, "order_url": order_url, "off_platform": not bool(uploaded_files)})
        send_templated_email(order.listing.seller_email, "Ticket delivery recorded", "ticket_delivered", {"title": order.listing.title, "order_url": request.build_absolute_uri(), "off_platform": False})
        messages.success(request, "Ticket details delivered. The buyer can now confirm receipt.")
    return redirect("order_detail", pk=pk)

@transaction.atomic
def confirm_receipt(request, pk):
    order = get_object_or_404(Order.objects.select_related("listing"), pk=pk)
    buyer_token_valid = request.GET.get("buyer_token") == str(order.buyer_access_token) or request.POST.get("buyer_token") == str(order.buyer_access_token)
    if request.method == "POST" and order.status == "delivered" and (buyer_token_valid or (request.user.is_authenticated and order.buyer_id == request.user.id)):
        order.status = "released"
        order.save(update_fields=["status", "updated_at"])
        order.listing.status = "sold" if order.listing.available_quantity == 0 else "available"
        order.listing.save(update_fields=["status"])
        if order.listing.seller_id:
            profile = order.listing.seller.profile
            profile.pending_balance = max(profile.pending_balance - order.total, 0)
            profile.save(update_fields=["pending_balance", "wallet_balance"])
        order.payout_status = "queued"
        order.save(update_fields=["payout_status", "updated_at"])
        from .tasks import process_payout_task
        process_payout_task.delay(order.pk)
        messages.success(request, "Receipt confirmed. Seller payout is now queued.")
    return redirect("order_detail", pk=pk)

def request_refund(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method == "POST" and order.status in {"in_escrow", "delivered"}:
        order.status = "refund_requested"
        order.save(update_fields=["status", "updated_at"])
        refund_payment(order)
        send_templated_email(order.listing.seller_email, "Refund requested for your ticket", "refund_requested", {"title": order.listing.title, "order_url": request.build_absolute_uri()})
        send_templated_email(order.buyer_email, "Your TicketTrust refund request", "dispute_opened", {"title": order.listing.title, "order_url": request.build_absolute_uri()})
        messages.info(request, "Refund request received. It will be reviewed before funds are returned.")
    return redirect("order_detail", pk=pk)

def release_reservations_job(request):
    cron_secret = os.environ.get("CRON_SECRET", "")
    authorization = request.headers.get("Authorization", "")
    if cron_secret and authorization != f"Bearer {cron_secret}":
        return JsonResponse({"detail": "Unauthorized"}, status=401)
    return JsonResponse({"released": release_expired_reservations()})
