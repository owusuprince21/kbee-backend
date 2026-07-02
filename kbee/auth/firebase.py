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


def _claim_email_is_verified(claims: dict) -> bool:
    if claims.get("email_verified") is True:
        return True
    firebase_claims = claims.get("firebase") or {}
    provider = firebase_claims.get("sign_in_provider") or ""
    return bool(claims.get("email") and provider == "google.com")


def _merge_guest_records_by_verified_email(email: str, customer: Customer) -> None:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return

    from store.models import AccountDetail, Address, Cart, Order, Review, WishlistItem

    guests = list(
        Customer.objects
        .filter(is_guest=True, email__iexact=normalized_email)
        .exclude(pk=customer.pk)
    )
    if not guests:
        return

    customer_account, _ = AccountDetail.objects.get_or_create(customer=customer)
    for guest in guests:
        Order.objects.filter(customer=guest).update(customer=customer)
        Address.objects.filter(customer=guest).update(customer=customer)
        Cart.objects.filter(customer=guest).update(customer=customer)

        guest_account = getattr(guest, "account", None)
        account_changed = []
        if guest_account:
            if guest_account.phone and not customer_account.phone:
                customer_account.phone = guest_account.phone
                account_changed.append("phone")
            if guest_account.bio and not customer_account.bio:
                customer_account.bio = guest_account.bio
                account_changed.append("bio")
        if account_changed:
            customer_account.save(update_fields=account_changed)

        for guest_wishlist in WishlistItem.objects.filter(customer=guest).select_related("product"):
            WishlistItem.objects.get_or_create(customer=customer, product=guest_wishlist.product)
        WishlistItem.objects.filter(customer=guest).delete()

        for guest_review in Review.objects.filter(customer=guest).select_related("product"):
            existing_review = Review.objects.filter(customer=customer, product=guest_review.product).first()
            if existing_review:
                guest_review.delete()
            else:
                guest_review.customer = customer
                guest_review.save(update_fields=["customer", "updated_at"])


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

    if email and _claim_email_is_verified(claims):
        _merge_guest_records_by_verified_email(email, cust)

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
