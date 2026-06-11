import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .exceptions import ImmutableLedgerError


class Wallet(models.Model):
    """A wallet deliberately has NO balance field.

    The balance is always derived from LedgerEntry rows — see
    apps.core.services.balance.get_wallet_balance().
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="wallets"
    )
    currency = models.CharField(max_length=3, default="UZS")
    # Static QR is generated once per wallet and stored as a URL.
    static_qr_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} [{self.id}]"

    @property
    def balance_info(self):
        from .services.balance import get_wallet_balance

        return get_wallet_balance(self.id)


class LedgerQuerySet(models.QuerySet):
    """Append-only enforcement at the queryset level."""

    def update(self, **kwargs):
        raise ImmutableLedgerError("Ledger entries are append-only; UPDATE is forbidden")

    def delete(self):
        raise ImmutableLedgerError("Ledger entries are append-only; DELETE is forbidden")


class LedgerEntry(models.Model):
    """One immutable money event. The ledger is the source of truth.

    balance   = SUM(credit) - SUM(debit)
    held      = SUM(hold)   - SUM(reversal)        (a reversal releases its hold)
    available = balance - held
    """

    class Type(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"
        HOLD = "hold", "Hold"
        REVERSAL = "reversal", "Reversal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="entries")
    type = models.CharField(max_length=8, choices=Type.choices)
    amount = models.BigIntegerField(help_text="Tiyin (1/100 UZS), strictly positive")
    ref_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False,
                              help_text="Idempotency key")
    related_entry = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversals",
        help_text="For reversal entries: the hold entry being released",
    )
    # default (not auto_now_add) so imports/tests may set an explicit timestamp;
    # immutability still applies after insert.
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = LedgerQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0),
                                   name="ledger_amount_positive"),
        ]
        indexes = [
            # Covers balance aggregation and (created_at, id) cursor seeks.
            models.Index(fields=["wallet", "-created_at", "-id"], name="ledger_cursor_idx"),
        ]

    def __str__(self):
        return f"{self.type} {self.amount} -> {self.wallet_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableLedgerError("Ledger entries are append-only; cannot modify")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableLedgerError("Ledger entries are append-only; cannot delete")


class Transfer(models.Model):
    """Links the two legs of a P2P transfer created in one atomic transaction."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender_wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT,
                                      related_name="transfers_out")
    recipient_wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT,
                                         related_name="transfers_in")
    debit_entry = models.OneToOneField(LedgerEntry, on_delete=models.PROTECT,
                                       related_name="transfer_as_debit")
    credit_entry = models.OneToOneField(LedgerEntry, on_delete=models.PROTECT,
                                        related_name="transfer_as_credit")
    amount = models.BigIntegerField()
    idempotency_key = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sender_wallet_id} -> {self.recipient_wallet_id}: {self.amount}"
