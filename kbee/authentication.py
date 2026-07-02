import json
import logging
import os
from functools import lru_cache
from typing import Optional, Tuple

import firebase_admin
from django.contrib.auth import get_user_model
from firebase_admin import auth as firebase_auth, credentials
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def firebase_app_ready() -> bool:
    if firebase_admin._apps:
        return True

    credentials_file = (
        os.environ.get("FIREBASE_CREDENTIALS_FILE")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        or ""
    ).strip()
    raw_credentials = (
        os.environ.get("FIREBASE_CREDENTIALS")
        or os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.environ.get("FIREBASE_CONFIG")
        or ""
    ).strip()

    try:
        if credentials_file:
            firebase_admin.initialize_app(credentials.Certificate(credentials_file))
        elif raw_credentials:
            firebase_admin.initialize_app(credentials.Certificate(json.loads(raw_credentials)))
        else:
            firebase_admin.initialize_app()
        log.info("Firebase initialized successfully")
        return True
    except Exception:
        log.exception("Firebase initialization failed")
        return False


def bearer_token(request) -> str:
    auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION") or ""
    if not auth_header:
        return ""
    return auth_header.split(" ").pop().strip()


def debug_claims_from_headers(request) -> Optional[dict]:
    uid = request.headers.get("X-Firebase-UID") or ""
    if not uid:
        return None
    return {
        "uid": uid,
        "email": request.headers.get("X-User-Email") or "",
        "name": request.headers.get("X-User-Name") or "",
        "picture": request.headers.get("X-User-Photo") or "",
        "email_verified": True,
        "firebase": {"sign_in_provider": "debug"},
    }


def verified_firebase_claims(request) -> Optional[dict]:
    token = bearer_token(request)
    if not token:
        from django.conf import settings

        if getattr(settings, "ALLOW_DEBUG_AUTH_HEADERS", False):
            return debug_claims_from_headers(request)
        return None

    if not firebase_app_ready():
        from django.conf import settings

        if getattr(settings, "ALLOW_DEBUG_AUTH_HEADERS", False):
            debug_claims = debug_claims_from_headers(request)
            if debug_claims:
                return debug_claims
        raise exceptions.AuthenticationFailed("Firebase authentication is not configured.")

    try:
        return firebase_auth.verify_id_token(token, check_revoked=True)
    except Exception as exc:
        from django.conf import settings

        if getattr(settings, "ALLOW_DEBUG_AUTH_HEADERS", False):
            debug_claims = debug_claims_from_headers(request)
            if debug_claims:
                return debug_claims
        raise exceptions.AuthenticationFailed("Invalid Firebase ID token") from exc


def claim_email_is_verified(claims: dict) -> bool:
    if claims.get("email_verified") is True:
        return True
    firebase_claims = claims.get("firebase") or {}
    provider = firebase_claims.get("sign_in_provider") or ""
    return bool(claims.get("email") and provider in {"google.com", "debug"})


def merge_guest_records_by_verified_email(email: str, customer) -> None:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return

    from store.models import AccountDetail, Address, Cart, Order, Review, WishlistItem

    guests = list(
        customer.__class__.objects
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


def django_user_from_claims(claims: dict):
    uid = claims.get("uid") or claims.get("user_id") or ""
    email = (claims.get("email") or "").strip()
    name = (claims.get("name") or "").strip()
    first_name, _, last_name = name.partition(" ")
    User = get_user_model()

    user = User.objects.filter(email__iexact=email).first() if email else None
    if not user:
        username = uid[:150] if uid else (email.split("@")[0] or "firebase-user")
        base_username = username
        suffix = 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f"{base_username[:145]}-{suffix}"
        user = User.objects.create_user(username=username, email=email or "")

    changed = []
    if email and user.email != email:
        user.email = email
        changed.append("email")
    if first_name and user.first_name != first_name:
        user.first_name = first_name[:150]
        changed.append("first_name")
    if last_name and user.last_name != last_name:
        user.last_name = last_name[:150]
        changed.append("last_name")
    if changed:
        user.save(update_fields=changed)
    return user


def customer_from_claims(claims: dict):
    from store.models import Customer

    uid = claims.get("uid") or claims.get("user_id") or ""
    email = (claims.get("email") or "").strip()
    name = (claims.get("name") or "").strip()
    photo = (claims.get("picture") or "").strip()

    if not uid:
        return None

    customer = Customer.objects.filter(firebase_uid=uid).first()
    if not customer and email and claim_email_is_verified(claims):
        customer = Customer.objects.filter(is_guest=False, email__iexact=email).first()
    if not customer:
        customer = Customer.objects.create(
            firebase_uid=uid,
            email=email,
            full_name=name,
            photo_url=photo,
            is_guest=False,
        )

    changed = []
    if customer.firebase_uid != uid:
        customer.firebase_uid = uid
        changed.append("firebase_uid")
    for field, value in (("email", email), ("full_name", name), ("photo_url", photo)):
        if value and getattr(customer, field) != value:
            setattr(customer, field, value)
            changed.append(field)
    if customer.is_guest:
        customer.is_guest = False
        changed.append("is_guest")
    if customer.guest_key:
        customer.guest_key = None
        changed.append("guest_key")
    if changed:
        customer.save(update_fields=changed)

    if email and claim_email_is_verified(claims):
        merge_guest_records_by_verified_email(email, customer)

    return customer


def customer_from_verified_claims(request):
    customer = getattr(request, "firebase_customer", None)
    if customer is not None:
        return customer

    claims = verified_firebase_claims(request)
    if not claims:
        return None

    user = django_user_from_claims(claims)
    customer = customer_from_claims(claims)
    request.firebase_user = user
    request.firebase_customer = customer
    return customer


class FirebaseAuthentication(BaseAuthentication):
    def authenticate(self, request) -> Optional[Tuple[object, None]]:
        claims = verified_firebase_claims(request)
        if not claims:
            return None

        user = django_user_from_claims(claims)
        customer = customer_from_claims(claims)
        request.firebase_customer = customer
        request.firebase_claims = claims
        return (user, None)
