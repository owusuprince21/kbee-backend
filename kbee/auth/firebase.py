from kbee.authentication import (  # noqa: F401
    FirebaseAuthentication as FirebaseHeaderAuthentication,
    customer_from_verified_claims,
    merge_guest_records_by_verified_email as _merge_guest_records_by_verified_email,
)


class HeaderUser:
    """Compatibility wrapper for older tests/imports."""

    def __init__(self, customer):
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
