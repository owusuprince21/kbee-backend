# store/checks.py
from django.conf import settings
from django.core.checks import register, Warning, Tags


@register(Tags.security)
def paystack_keys_check(app_configs, **kwargs):
    """
    Warn (do not crash) if Paystack keys are missing.
    """
    warnings = []
    if getattr(settings, "PAYMENT_PROVIDER", "paystack").lower() == "paystack":
        secret = getattr(settings, "PAYSTACK_SECRET_KEY", "")
        public = getattr(settings, "PAYSTACK_PUBLIC_KEY", "")
        if not secret:
            warnings.append(Warning(
                "PAYSTACK_SECRET_KEY is not set; payment initialize/verify/webhook will fail.",
                id="store.W001",
            ))
        if not public:
            warnings.append(Warning(
                "PAYSTACK_PUBLIC_KEY is not set; client initialization will fail.",
                id="store.W002",
            ))
    return warnings
