from django.test import TestCase
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import UserRateThrottle

from kbee.auth.firebase import HeaderUser, _merge_guest_records_by_verified_email
from store.models import AccountDetail, Address, Cart, Customer, Order, Payment, PaymentStatus
from store.views_checkout import _claim_guest_payment_for_registered_customer


class HeaderUserTests(TestCase):
    def test_header_user_exposes_pk_for_drf_user_throttle(self):
        customer = Customer.objects.create(
            firebase_uid="firebase:test-user",
            email="test@example.com",
            full_name="Test User",
        )
        request = APIRequestFactory().get("/api/categories/")
        request.user = HeaderUser(customer)

        cache_key = UserRateThrottle().get_cache_key(request, view=None)

        self.assertEqual(request.user.pk, customer.pk)
        self.assertEqual(cache_key, f"throttle_user_{customer.pk}")


class FirebaseCustomerMergeTests(TestCase):
    def test_verified_email_login_claims_guest_order_and_profile_data(self):
        email = "buyer@example.com"
        registered = Customer.objects.create(
            firebase_uid="firebase:buyer",
            email=email,
            full_name="Buyer",
            is_guest=False,
        )
        guest = Customer.objects.create(
            firebase_uid="guest:phone-device",
            guest_key="phone-device",
            email=email,
            full_name="Guest customer",
            is_guest=True,
        )
        order = Order.objects.create(
            customer=guest,
            ship_full_name="Buyer",
            ship_line1="Accra Kingsway",
            ship_city="Accra",
            total="100.00",
        )
        address = Address.objects.create(
            customer=guest,
            full_name="Buyer",
            line1="Accra Kingsway",
            city="Accra",
            phone="+233248147215",
        )
        Cart.objects.create(customer=guest)
        AccountDetail.objects.create(customer=guest, phone="+233248147215", bio="Laptop buyer")

        _merge_guest_records_by_verified_email(email, registered)

        order.refresh_from_db()
        address.refresh_from_db()
        self.assertEqual(order.customer_id, registered.id)
        self.assertEqual(address.customer_id, registered.id)
        self.assertTrue(Cart.objects.filter(customer=registered).exists())
        registered.account.refresh_from_db()
        self.assertEqual(registered.account.phone, "+233248147215")
        self.assertEqual(registered.account.bio, "Laptop buyer")

    def test_payment_verify_claims_guest_payment_for_registered_customer_with_same_email(self):
        email = "buyer@example.com"
        registered = Customer.objects.create(
            firebase_uid="firebase:buyer",
            email=email,
            full_name="Buyer",
            is_guest=False,
        )
        guest = Customer.objects.create(
            firebase_uid="guest:phone-device",
            guest_key="phone-device",
            email=email,
            full_name="Guest customer",
            is_guest=True,
        )
        order = Order.objects.create(
            customer=guest,
            ship_full_name="Buyer",
            ship_line1="Accra Kingsway",
            ship_city="Accra",
            total="100.00",
        )
        payment = Payment.objects.create(
            order=order,
            provider="paystack",
            tx_ref="test-ref",
            status=PaymentStatus.PENDING,
            amount="100.00",
            raw={"init": {"customer_id": guest.id}},
        )

        owner = _claim_guest_payment_for_registered_customer(payment, guest, registered)

        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(owner.id, registered.id)
        self.assertEqual(order.customer_id, registered.id)
        self.assertEqual(payment.raw["init"]["customer_id"], registered.id)
