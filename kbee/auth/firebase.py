# kbee/auth/firebase.py
from typing import Optional, Tuple
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import PermissionDenied
from store.models import Customer

class HeaderUser:
    """Minimal user wrapper that satisfies DRF."""
    def __init__(self, customer: Customer):
        self.customer = customer
        self.id = customer.id
        self.email = customer.email
        self.username = customer.full_name or (customer.email or f"cust-{customer.id}")
        self.is_authenticated = True

    def __str__(self):
        return self.username

def get_or_create_customer_from_headers(request) -> Optional[Customer]:
    # Browser exposes custom headers as HTTP_<HEADER_NAME>
    uid   = request.META.get("HTTP_X_FIREBASE_UID")
    email = request.META.get("HTTP_X_USER_EMAIL")
    name  = request.META.get("HTTP_X_USER_NAME")
    photo = request.META.get("HTTP_X_USER_PHOTO")

    if not uid:
        return None

    cust, created = Customer.objects.get_or_create(
        firebase_uid=uid,
        defaults={"email": email or "", "full_name": name or "", "photo_url": photo or ""},
    )

    changed = False
    if email and cust.email != email:
        cust.email = email; changed = True
    if name and cust.full_name != name:
        cust.full_name = name; changed = True
    if photo and cust.photo_url != photo:
        cust.photo_url = photo; changed = True
    if changed:
        cust.save()

    return cust

class FirebaseHeaderAuthentication(BaseAuthentication):
    """
    Authenticate requests using the X-Firebase-* headers supplied by the client.
    """
    def authenticate(self, request) -> Optional[Tuple[HeaderUser, None]]:
        cust = get_or_create_customer_from_headers(request)
        if not cust:
            return None  # let other authenticators try; otherwise the request is anonymous
        return (HeaderUser(cust), None)
