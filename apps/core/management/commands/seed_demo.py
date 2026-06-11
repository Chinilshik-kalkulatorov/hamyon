"""Demo data: admin + two users with wallets and starting balances.

Starting balances are created the only legal way — as credit ledger entries.
"""

from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from apps.core.models import LedgerEntry, Wallet
from apps.core.services.ledger import post_entry
from apps.kyc.models import KYCApplication
from apps.users.models import KYCLevel, User


class Command(BaseCommand):
    help = "Seed demo users, wallets and balances"

    def handle(self, *args, **options):
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={"is_staff": True, "is_superuser": True},
        )
        if created:
            admin.set_password("admin123")
            admin.save()

        users = {}
        for username, phone, level, initial_uzs in [
            ("alice", "+998900000001", KYCLevel.FULL, 1_000_000),
            ("bob", "+998900000002", KYCLevel.BASIC, 100_000),
        ]:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"phone": phone, "kyc_level": level},
            )
            if created:
                user.set_password("demo123")
                user.save()
                app = KYCApplication.objects.create(
                    user=user,
                    requested_level=level,
                    passport_ref=f"s3://kyc-demo/{username}/passport.jpg",
                    selfie_ref=f"s3://kyc-demo/{username}/selfie.jpg",
                )
                app.approve(by=admin)
                wallet = Wallet.objects.create(user=user)
                post_entry(wallet, LedgerEntry.Type.CREDIT, initial_uzs * 100)
            users[username] = user

        self.stdout.write(self.style.SUCCESS("Demo data ready:\n"))
        for username, user in users.items():
            token, _ = Token.objects.get_or_create(user=user)
            wallet = user.wallets.first()
            info = wallet.balance_info
            self.stdout.write(
                f"  {username} / demo123  kyc={user.kyc_level}\n"
                f"    token : {token.key}\n"
                f"    wallet: {wallet.id}\n"
                f"    balance: {info['balance']} tiyin "
                f"({info['balance'] // 100:,} UZS)\n"
            )
        self.stdout.write("  admin / admin123 (superuser, /admin/)")
