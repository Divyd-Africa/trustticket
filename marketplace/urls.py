from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("verify-email/", views.verify_email, name="verify_email"),
    path("verify-email/resend/", views.resend_otp, name="resend_otp"),
    path("login/", views.sign_in, name="login"),
    path("logout/", views.sign_out, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/bank/", views.bank_account, name="bank_account"),
    path("exchange/new/", views.create_exchange, name="create_exchange"),
    path("exchange/<str:token>/", views.exchange_detail, name="exchange_detail"),
    path("webhooks/bachs/", views.bachs_webhook, name="bachs_webhook"),
    path("jobs/release-reservations/", views.release_reservations_job, name="release_reservations_job"),
    path("sell/", views.sell, name="sell"),
    path("listing/<int:pk>/", views.listing_detail, name="listing_detail"),
    path("listing/<int:pk>/buy/", views.buy, name="buy"),
    path("order/<int:pk>/", views.order_detail, name="order_detail"),
    path("order/<int:pk>/confirm/", views.confirm_receipt, name="confirm_receipt"),
    path("order/<int:pk>/deliver/", views.deliver_ticket, name="deliver_ticket"),
    path("order/<int:pk>/refund/", views.request_refund, name="request_refund"),
]
