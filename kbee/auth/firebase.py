import json
import logging
import os
from functools import lru_cache
from typing import Optional, Tuple

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from store.models import Customer

log = logging.getLogger(__name__)


class HeaderUser:
    """Minimal user wrapper that satisfies DRF."""

    def __init__(self, customer: Customer):
        self.customer = customer
        self.id = customer.id
        self.pk = customer.pk
        self.email = customer.email
        self.username = customer.full_name or (customer.email or f"cust-{customer.id}")
        self.is_authenticated = True
        self.is_anonymous = False
        self.is_active = True

    def __getattr__(self, name):
        return getattr(self.customer, name)

    def __str__(self):
        return self.username


@lru_cache(maxsize=1)
def _firebase_app_ready() -> bool:
    if firebase_admin._apps:
        return True

    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    try:
        if service_account_json:
            firebase_admin.initialize_app(credentials.Certificate(json.loads(service_account_json)))
        else:
            firebase_admin.initialize_app()
        return True
    except Exception:
        log.exception("Firebase Admin could not be initialized.")
        return False


def _bearer_token(request) -> str:
    header = request.headers.get("Authorization") or ""
    prefix = "Bearer "
    if not header.startswith(prefix):
        return ""
    return header[len(prefix) :].strip()


def verified_firebase_claims(request) -> Optional[dict]:
    token = _bearer_token(request)
    if not token:
        if getattr(settings, "ALLOW_DEBUG_AUTH_HEADERS", False):
            return _debug_claims_from_headers(request)
        return None
    if not _firebase_app_ready():
        if getattr(settings, "ALLOW_DEBUG_AUTH_HEADERS", False):
            return _debug_claims_from_headers(request)
        raise AuthenticationFailed("Firebase authentication is not configured.")
    try:
        return firebase_auth.verify_id_token(token, check_revoked=True)
    except Exception as exc:
        if getattr(settings, "ALLOW_DEBUG_AUTH_HEADERS", False):
            debug_claims = _debug_claims_from_headers(request)
            if debug_claims:
                return debug_claims
        raise AuthenticationFailed("Invalid or expired Firebase token.") from exc


def _debug_claims_from_headers(request) -> Optional[dict]:
    uid = request.headers.get("X-Firebase-UID") or ""
    if not uid:
        return None
    return {
        "uid": uid,
        "email": request.headers.get("X-User-Email") or "",
        "name": request.headers.get("X-User-Name") or "",
        "picture": request.headers.get("X-User-Photo") or "",
    }


def customer_from_verified_claims(request) -> Optional[Customer]:
    claims = verified_firebase_claims(request)
    if not claims:
        return None

    uid = claims.get("uid") or claims.get("user_id")
    email = claims.get("email") or ""
    name = claims.get("name") or request.headers.get("X-User-Name") or ""
    photo = claims.get("picture") or request.headers.get("X-User-Photo") or ""

    if not uid:
        return None

    cust, _created = Customer.objects.get_or_create(
        firebase_uid=uid,
        defaults={
            "email": email,
            "full_name": name,
            "photo_url": photo,
            "is_guest": False,
        },
    )

    changed: list[str] = []
    for field, value in (("email", email), ("full_name", name), ("photo_url", photo)):
        if value and getattr(cust, field) != value:
            setattr(cust, field, value)
            changed.append(field)
    if cust.is_guest:
        cust.is_guest = False
        changed.append("is_guest")
    if changed:
        cust.save(update_fields=changed)

    return cust


class FirebaseHeaderAuthentication(BaseAuthentication):
    """
    Authenticate requests using a verified Firebase ID token.
    """

    def authenticate(self, request) -> Optional[Tuple[HeaderUser, None]]:
        cust = customer_from_verified_claims(request)
        if not cust:
            return None  # let other authenticators try; otherwise the request is anonymous
        return (HeaderUser(cust), None)
