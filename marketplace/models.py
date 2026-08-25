import uuid
from django.conf import settings
from django.db import models
from django.contrib.auth.models import User

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=30)
    social_link = models.URLField(blank=True)
    email_verified = models.BooleanField(default=False)
    wallet_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pending_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

class EmailOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_otps")
    code = models.CharField(max_length=6)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class BankAccount(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="bank_accounts")
    bank_name = models.CharField(max_length=120)
    bank_code = models.CharField(max_length=30)
    account_number = models.CharField(max_length=20)
    account_name = models.CharField(max_length=160)
    verified = models.BooleanField(default=False)
    bachs_destination_id = models.CharField(max_length=100, blank=True)
    bachs_destination_status = models.CharField(max_length=40, blank=True)
    is_default = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

class ExchangeLink(models.Model):
    STATUS_CHOICES = [("open", "Open"), ("paid", "Paid"), ("delivered", "Delivered"), ("completed", "Completed"), ("disputed", "Disputed"), ("cancelled", "Cancelled")]
    token = models.CharField(max_length=64, unique=True)
    seller_name = models.CharField(max_length=100)
    seller_email = models.EmailField()
    seller_phone = models.CharField(max_length=30)
    seller_bank_name = models.CharField(max_length=120, blank=True)
    seller_bank_code = models.CharField(max_length=30, blank=True)
    seller_account_number = models.CharField(max_length=20, blank=True)
    title = models.CharField(max_length=180)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    event_date = models.DateTimeField()
    buyer_name = models.CharField(max_length=100, blank=True)
    buyer_email = models.EmailField(blank=True)
    buyer_phone = models.CharField(max_length=30, blank=True)
    ticket_details = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)

class Listing(models.Model):
    STATUS_CHOICES = [("available", "Available"), ("reserved", "Reserved"), ("sold", "Sold")]
    seller = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="listings")
    title = models.CharField(max_length=180)
    venue = models.CharField(max_length=180)
    city = models.CharField(max_length=80, default="Lagos")
    event_date = models.DateTimeField()
    ticket_type = models.CharField(max_length=100, default="General admission")
    quantity = models.PositiveIntegerField(default=1)
    available_quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True)
    delivery_note = models.CharField(max_length=180, default="Ticket details released by the seller")
    seller_name = models.CharField(max_length=100)
    seller_email = models.EmailField()
    seller_bank = models.CharField(max_length=120, blank=True)
    seller_bank_code = models.CharField(max_length=30, blank=True)
    seller_account_number = models.CharField(max_length=20, blank=True)
    seller_account_name = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="available")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["event_date"]

    def __str__(self):
        return self.title

class Order(models.Model):
    STATUS_CHOICES = [("awaiting_payment", "Awaiting payment"), ("expired", "Reservation expired"), ("in_escrow", "In escrow"), ("delivered", "Ticket delivered"), ("released", "Funds released"), ("refund_requested", "Refund requested"), ("refunded", "Refunded")]
    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="orders")
    buyer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    buyer_name = models.CharField(max_length=100)
    buyer_email = models.EmailField()
    buyer_bank = models.CharField(max_length=120, blank=True)
    buyer_bank_code = models.CharField(max_length=30, blank=True)
    buyer_account_number = models.CharField(max_length=20, blank=True)
    buyer_account_name = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="awaiting_payment")
    ticket_details = models.TextField(blank=True)
    ticket_file_url = models.URLField(blank=True)
    ticket_file_name = models.CharField(max_length=255, blank=True)
    ticket_file_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    payment_reference = models.CharField(max_length=160, blank=True)
    payment_provider_response = models.JSONField(default=dict, blank=True)
    payment_expires_at = models.DateTimeField(null=True, blank=True)
    reservation_expires_at = models.DateTimeField(null=True, blank=True)
    buyer_access_token = models.UUIDField(default=uuid.uuid4, editable=False)
    payout_status = models.CharField(max_length=20, default="not_started")
    payout_reference = models.CharField(max_length=160, blank=True)
    payout_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payout_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payout_response = models.JSONField(default=dict, blank=True)
    payout_error = models.TextField(blank=True)
    payout_initiated_at = models.DateTimeField(null=True, blank=True)
    payout_completed_at = models.DateTimeField(null=True, blank=True)

    @property
    def total(self):
        return self.listing.price

class TicketAttachment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="ticket_attachments")
    file_url = models.URLField()
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
