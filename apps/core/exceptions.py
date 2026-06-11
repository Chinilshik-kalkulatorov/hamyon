"""Domain exceptions. Views translate them to HTTP via apps.core.api."""


class ImmutableLedgerError(Exception):
    """Any attempt to UPDATE or DELETE a ledger entry."""


class BlockedError(Exception):
    """User or wallet is blacklisted. Maps to an empty 403 — no detail leaked."""


class KYCRejectedError(Exception):
    """User's latest KYC application is rejected: all transactions forbidden."""


class KYCLimitExceededError(Exception):
    """Operation would exceed the rolling 30-day spend limit for the KYC level."""


class InsufficientFundsError(Exception):
    """Available balance is lower than the requested amount."""


class InvalidTransition(Exception):
    """Illegal state machine transition. Never silently ignored."""
