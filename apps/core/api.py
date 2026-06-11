"""Maps domain exceptions to HTTP responses for all transaction views."""

import functools

from rest_framework import status
from rest_framework.response import Response

from apps.core.exceptions import (
    BlockedError,
    InsufficientFundsError,
    InvalidTransition,
    KYCLimitExceededError,
    KYCRejectedError,
)
from apps.otp.service import OTPInvalidError, OTPLockedError, OTPMissingError


def map_domain_errors(view_method):
    @functools.wraps(view_method)
    def wrapper(*args, **kwargs):
        try:
            return view_method(*args, **kwargs)
        except BlockedError:
            # Deliberately empty body: no detail leaked to blocked actors.
            return Response(status=status.HTTP_403_FORBIDDEN)
        except KYCRejectedError:
            return Response({"code": "kyc_rejected"}, status=status.HTTP_403_FORBIDDEN)
        except KYCLimitExceededError:
            return Response({"code": "kyc_limit_exceeded"}, status=status.HTTP_403_FORBIDDEN)
        except InsufficientFundsError:
            return Response({"code": "insufficient_funds"}, status=status.HTTP_409_CONFLICT)
        except OTPLockedError:
            return Response({"code": "otp_locked"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        except OTPMissingError:
            return Response({"code": "otp_missing_or_expired"}, status=status.HTTP_400_BAD_REQUEST)
        except OTPInvalidError:
            return Response({"code": "otp_invalid"}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTransition as exc:
            return Response(
                {"code": "invalid_state_transition", "detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

    return wrapper
