from django.test import TestCase
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import UserRateThrottle

from kbee.auth.firebase import HeaderUser
from store.models import Customer


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
