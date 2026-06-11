"""The three guards every transaction endpoint runs, in this exact order:

1. Blacklist  -> empty 403, no detail leaked
2. KYC        -> rejected users blocked; rolling 30-day spend limit
3. Balance    -> sufficient available funds

Blacklist is additionally enforced earlier by BlacklistMiddleware; running it
here again keeps the invariant even for code paths that bypass HTTP.
"""

from datetime import timedelta

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.blacklist.service import is_blocked
from apps.core.exceptions import (
    BlockedError,
    InsufficientFundsError,
    KYCLimitExceededError,
    KYCRejectedError,
)
from apps.core.models import LedgerEntry

from .balance import get_wallet_balance


def run_guards(user, wallet, amount: int, *, spends_funds: bool = True):
    """Validate a transaction attempt. Raises a domain exception on failure.

    spends_funds=False for top-ups: money enters the wallet, so the spend
    limit and the available-balance checks do not apply (documented in README).
    """
    # 1. Blacklist
    if is_blocked(user=user, wallet_id=wallet.id, phone=getattr(user, "phone", None)):
        raise BlockedError()

    # 2. KYC
    check_kyc(user, amount if spends_funds else 0)

    # 3. Balance
    if spends_funds:
        available = get_wallet_balance(wallet.id, use_cache=False)["available"]
        if available < amount:
            raise InsufficientFundsError()


def check_kyc(user, spend_amount: int):
    from django.conf import settings

    from apps.kyc.models import KYCApplication
    from apps.kyc.services import get_spending_limit

    latest = user.kyc_applications.order_by("-created_at").first()
    if latest is not None and latest.status == KYCApplication.Status.REJECTED:
        raise KYCRejectedError()

    if spend_amount <= 0:
        return

    limit = get_spending_limit(user)
    window_start = timezone.now() - timedelta(days=settings.KYC_LIMIT_WINDOW_DAYS)
    spent = LedgerEntry.objects.filter(
        wallet__user=user,
        type=LedgerEntry.Type.DEBIT,
        created_at__gte=window_start,
    ).aggregate(total=Coalesce(Sum("amount"), 0))["total"]

    if spent + spend_amount > limit:
        raise KYCLimitExceededError()
