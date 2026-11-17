"""Allowlisted provider diagnostics: never publish exception bodies or credentials."""

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
    }
)


def details(error: Exception) -> dict:
    return public_details(
        {
            "provider_error_code": getattr(error, "code", None),
            "http_status": getattr(error, "status_code", None),
        }
    )


def public_details(result: dict) -> dict:
    """Do not trust arbitrary diagnostic fields from an injected/model response."""
    safe = {}
    code = result.get("provider_error_code")
    if not isinstance(code, str):
        code = None
    if code in SAFE_CODES:
        safe["provider_error_code"] = code
    status = result.get("http_status")
    if type(status) is int and 100 <= status <= 599:
        safe["http_status"] = status
    # Derive advice from known codes instead of forwarding arbitrary strings.
    if code in {"insufficient_quota", "billing_hard_limit_reached"}:
        safe.update(
            retryable=False, remediation="Check API billing, project credits and usage limits."
        )
    elif code == "rate_limit_exceeded":
        safe.update(
            retryable=True, remediation="Wait for the provider rate-limit window before retrying."
        )
    return safe
