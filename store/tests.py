from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory
from rest_framework.test import APIClient
from rest_framework.throttling import UserRateThrottle

from kbee.auth.firebase import HeaderUser, _merge_guest_records_by_verified_email
from store.models import (
    AccountDetail,
    Address,
    Cart,
    Category,
    Customer,
    MainCategory,
    Order,
    Payment,
    PaymentStatus,
    Product,
    WishlistItem,
)
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

    @override_settings(ALLOW_DEBUG_AUTH_HEADERS=True)
    def test_orders_endpoint_claims_guest_order_by_saved_code(self):
        registered = Customer.objects.create(
            firebase_uid="firebase:buyer",
            email="buyer@example.com",
            full_name="Buyer",
            is_guest=False,
        )
        guest = Customer.objects.create(
            firebase_uid="guest:phone-device",
            guest_key="phone-device",
            email="old-guest@example.invalid",
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

        response = APIClient().get(
            "/api/orders/",
            HTTP_X_FIREBASE_UID=registered.firebase_uid,
            HTTP_X_USER_EMAIL=registered.email,
            HTTP_X_USER_NAME=registered.full_name,
            HTTP_X_CLAIM_ORDER_CODES=order.code,
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.customer_id, registered.id)
        self.assertEqual(response.data["results"][0]["code"], order.code)

    @override_settings(ALLOW_DEBUG_AUTH_HEADERS=True)
    def test_orders_endpoint_claims_guest_order_by_payment_email(self):
        registered = Customer.objects.create(
            firebase_uid="firebase:buyer",
            email="buyer@example.com",
            full_name="Buyer",
            is_guest=False,
        )
        guest = Customer.objects.create(
            firebase_uid="guest:phone-device",
            guest_key="phone-device",
            email="guest-phone-device@guest.local",
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
        Payment.objects.create(
            order=order,
            provider="paystack",
            tx_ref="payment-email-ref",
            status=PaymentStatus.SUCCESSFUL,
            amount="100.00",
            raw={"verify": {"data": {"customer": {"email": registered.email}}}},
        )

        response = APIClient().get(
            "/api/orders/",
            HTTP_X_FIREBASE_UID=registered.firebase_uid,
            HTTP_X_USER_EMAIL=registered.email,
            HTTP_X_USER_NAME=registered.full_name,
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.customer_id, registered.id)
        self.assertEqual(response.data["results"][0]["code"], order.code)


class GuestReadTests(TestCase):
    def test_cart_read_does_not_create_guest_customer(self):
        response = APIClient().get("/api/cart/", HTTP_X_GUEST_ID="guest-browser-only")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["items"], [])
        self.assertEqual(response.data["subtotal"], "0.00")
        self.assertFalse(Customer.objects.filter(is_guest=True).exists())

    def test_guest_can_add_read_and_remove_wishlist_item(self):
        category = Category.objects.create(name=MainCategory.LAPTOPS, slug="laptops")
        product = Product.objects.create(
            name="Guest Laptop",
            slug="guest-laptop",
            category=category,
            price="2500.00",
            stock_quantity=3,
            main_image="products/guest-laptop.jpg",
        )
        client = APIClient()
        guest_headers = {"HTTP_X_GUEST_ID": "guest-browser-wishlist"}

        create_response = client.post(
            "/api/wishlist/",
            {"product_id": product.id},
            format="json",
            **guest_headers,
        )
        self.assertEqual(create_response.status_code, 201)
        guest = Customer.objects.get(guest_key="guest-browser-wishlist", is_guest=True)
        self.assertTrue(WishlistItem.objects.filter(customer=guest, product=product).exists())

        list_response = client.get("/api/wishlist/", **guest_headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["results"][0]["product"]["id"], product.id)

        delete_response = client.delete(f"/api/wishlist/by-product/{product.id}/", **guest_headers)
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(WishlistItem.objects.filter(customer=guest, product=product).exists())
