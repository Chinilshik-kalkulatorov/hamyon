from django.conf import settings


def get_spending_limit(user) -> int:
    """Max spend (tiyin) per rolling 30-day window for the user's KYC level.

    Limits live in settings.KYC_SPEND_LIMITS — configurable, not hardcoded.
    """
    return settings.KYC_SPEND_LIMITS[user.kyc_level]
