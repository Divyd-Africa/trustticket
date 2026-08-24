from django.core.management.base import BaseCommand
from marketplace.reservations import release_expired_reservations

class Command(BaseCommand):
    help = "Release unpaid ticket reservations after their 15-minute hold expires."

    def handle(self, *args, **options):
        self.stdout.write(f"Released {release_expired_reservations()} expired reservation(s).")
