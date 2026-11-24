"""Allowlisted provider diagnostics: never publish exception bodies or credentials."""

from typing import Any

SAFE_CODES = frozenset(
    {
        "insufficient_quota",
        "rate_limit_exceeded",
        "invalid_api_key",
        "model_not_found",
        "unsupported_parameter",
        "invalid_request_error",
        "billing_hard_limit_reached",
        "account_deactivated",
        "credit_balance_exhausted",
        "organization_usage_limit_exceeded",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "slow_down",
        "server_is_overloaded",
    }
)


def details(error: Exception) -> dict:
    raw = {
        "provider_error_code": getattr(error, "code", None),
        "provider_error_type": getattr(error, "type", None),
        "http_status": getattr(error, "status_code", None),
    }
    # Some API responses omit code; classify known phrases without exposing the message.
    message = str(getattr(error, "message", "")).lower()
    if any(
        phrase in message
        for phrase in (
            "exceeded your current quota",
            "check your plan and billing",
            "credit balance exhausted",
        )
    ):
        raw["provider_error_category"] = "quota_exhausted"
    elif "rate limit reached" in message:
        raw["provider_error_category"] = "temporary_rate_limit"
    return public_details(raw)


def public_details(result: dict) -> dict:
    """Do not trust arbitrary diagnostic fields from an injected/model response."""
    safe: dict[str, Any] = {}
    code = result.get("provider_error_code")
    if not isinstance(code, str):
        code = None
    if code in SAFE_CODES:
        safe["provider_error_code"] = code
    kind = result.get("provider_error_type")
    if isinstance(kind, str) and kind in {
        "insufficient_quota",
        "rate_limit_error",
        "requests",
        "tokens",
    }:
        safe["provider_error_type"] = kind
    category = result.get("provider_error_category")
    if isinstance(category, str) and category in {"quota_exhausted", "temporary_rate_limit"}:
        safe["provider_error_category"] = category
    status = result.get("http_status")
    if type(status) is int and 100 <= status <= 599:
        safe["http_status"] = status
    # Derive advice from known codes instead of forwarding arbitrary strings.
    if (
        code
        in {
            "insufficient_quota",
            "billing_hard_limit_reached",
            "credit_balance_exhausted",
            "organization_usage_limit_exceeded",
            "organization_spend_limit_exceeded",
            "project_spend_limit_exceeded",
        }
        or kind == "insufficient_quota"
        or category == "quota_exhausted"
    ):
        safe.update(
            retryable=False, remediation="Check API billing, project credits and usage limits."
        )
    elif (
        code in {"rate_limit_exceeded", "slow_down", "server_is_overloaded"}
        or category == "temporary_rate_limit"
    ):
        safe.update(
            retryable=True, remediation="Wait for the provider rate-limit window before retrying."
        )
    return safe
