# store/views.py
from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django_filters.rest_framework import DjangoFilterBackend  # type: ignore

from .models import (
    Category,
    HotItem,
    Product,
    HeroItem,
    CountdownDeal,

    # NOTE:
    # The models below belonged to the old e-commerce (login/cart/checkout/payments).
    # They are intentionally NOT imported now because they are commented out in models.py.
    #
    # Customer,
    # Cart,
    # CartItem,
    # WishlistItem,
    # Review,
    # Address,
    # AccountDetail,
    # Order,
    # OrderItem,
    # Payment,
)

from .serializers import (
    CategorySerializer,
    HotItemSerializer,
    ProductSerializer,
    HeroItemSerializer,
    CountdownDealSerializer,

    # NOTE:
    # Old flow serializers (commented out intentionally)
    #
    # CustomerSerializer,
    # CartSerializer,
    # CartItemSerializer,
    # WishlistItemSerializer,
    # ReviewSerializer,
    # AddressSerializer,
    # AccountDetailSerializer,
    # OrderSerializer,
)

# =============================================================================
# ACTIVE VIEWSETS (Needed now)
# - Public catalog browsing
# - Homepage marketing sections
# =============================================================================

# --- Category ---------------------------------------------------------------

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"


# --- Product ----------------------------------------------------------------

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Product.objects
        .select_related("category")
        .prefetch_related("gallery")
        .all()
    )
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "category": ["exact"],
        "category__slug": ["exact"],
        "brand": ["exact", "iexact", "icontains"],
        "condition": ["exact"],
        "is_featured": ["exact"],
        "is_new_arrival": ["exact"],
        "is_best_seller": ["exact"],
        "is_in_stock": ["exact"],
    }
    search_fields = ["name"]
    ordering_fields = ["created_at", "updated_at", "price", "discount_price", "name"]

    @action(detail=False, methods=["get"])
    def featured(self, request):
        qs = self.filter_queryset(self.get_queryset().filter(is_featured=True))
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page or qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @action(detail=False, methods=["get"])
    def new_arrivals(self, request):
        qs = self.filter_queryset(self.get_queryset().filter(is_new_arrival=True))
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page or qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @action(detail=False, methods=["get"])
    def best_sellers(self, request):
        qs = self.filter_queryset(self.get_queryset().filter(is_best_seller=True))
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page or qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @action(detail=True, methods=["get"])
    def related(self, request, slug=None):
        product: Product = self.get_object()
        qs = (
            Product.objects
            .select_related("category")
            .prefetch_related("gallery")
            .filter(category=product.category)
            .exclude(pk=product.pk)
        )[:12]
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)


# --- Hero & Countdown -------------------------------------------------------

class HeroItemViewSet(viewsets.ModelViewSet):
    queryset = HeroItem.objects.select_related("product").order_by("position")
    serializer_class = HeroItemSerializer
    permission_classes = [AllowAny]


class CountdownDealViewSet(viewsets.ModelViewSet):
    queryset = (
        CountdownDeal.objects
        .select_related("product")
        .prefetch_related("product__gallery")
        .all()
    )
    serializer_class = CountdownDealSerializer
    permission_classes = [AllowAny]

    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request):
        now = timezone.now()
        qs = (
            self.get_queryset()
            .filter(active=True, starts_at__lte=now, ends_at__gte=now)
            .order_by("-starts_at")
        )
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)


# --- Hot Items / Banners ----------------------------------------------------

class HotItemViewSet(viewsets.ModelViewSet):
    """
    Read/write HotItem banners. 'active' returns only currently visible items
    (active=True and within optional starts_at/ends_at window), ordered by
    position then newest.
    """
    queryset = (
        HotItem.objects
        .select_related("product", "product__category")
        .prefetch_related("product__gallery")
        .all()
    )
    serializer_class = HotItemSerializer
    permission_classes = [AllowAny]

    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request):
        now = timezone.now()
        qs = (
            self.get_queryset()
            .filter(active=True)
            .filter(
                Q(starts_at__isnull=True) | Q(starts_at__lte=now),
                Q(ends_at__isnull=True)   | Q(ends_at__gte=now),
            )
            .order_by("position", "-created_at")
        )
        data = self.get_serializer(qs, many=True).data
        return Response(data)

# =============================================================================
# INACTIVE / FUTURE VIEWSETS (Commented out intentionally)
# These match the old login/cart/checkout/payment flow.
# =============================================================================

# --------------------------------------------------------------------------
# Resolve the current customer via Firebase headers (old flow)
# --------------------------------------------------------------------------
#
# from rest_framework import status
# from rest_framework.exceptions import PermissionDenied, ValidationError
#
# def get_or_create_customer(request) -> Customer:
#     user = getattr(request, "user", None)
#     if isinstance(user, Customer):
#         return user
#
#     uid = request.headers.get("X-Firebase-UID")
#     if not uid:
#         raise PermissionDenied(
#             "No authenticated user. Provide Authorization: Bearer <token> "
#             "or include the 'X-Firebase-UID' header."
#         )
#
#     email = request.headers.get("X-User-Email", "") or ""
#     full_name = request.headers.get("X-User-Name", "") or ""
#     photo = request.headers.get("X-User-Photo", "") or ""
#
#     customer, _ = Customer.objects.get_or_create(
#         firebase_uid=uid,
#         defaults={
#             "email": email or f"{uid}@local.invalid",
#             "full_name": full_name,
#             "photo_url": photo,
#         },
#     )
#
#     to_update: list[str] = []
#     if email and customer.email != email:
#         customer.email = email
#         to_update.append("email")
#     if full_name and customer.full_name != full_name:
#         customer.full_name = full_name
#         to_update.append("full_name")
#     if photo and customer.photo_url != photo:
#         customer.photo_url = photo
#         to_update.append("photo_url")
#     if to_update:
#         customer.save(update_fields=to_update)
#
#     return customer
#
#
# --- Cart ------------------------------------------------------------------
#
# class CartViewSet(viewsets.ViewSet):
#     ...
#
# --- Wishlist ---------------------------------------------------------------
#
# class WishlistViewSet(viewsets.ViewSet):
#     ...
#
# --- Reviews ---------------------------------------------------------------
#
# class ReviewViewSet(viewsets.ModelViewSet):
#     ...
#
# --- Addresses --------------------------------------------------------------
#
# class AddressViewSet(viewsets.ModelViewSet):
#     ...
#
# --- Account Details --------------------------------------------------------
#
# class AccountDetailViewSet(viewsets.ViewSet):
#     ...
#
# --- Customers --------------------------------------------------------------
#
# class CustomerViewSet(viewsets.ReadOnlyModelViewSet):
#     ...
#
# --- Orders -----------------------------------------------------------------
#
# class OrderViewSet(viewsets.ReadOnlyModelViewSet):
#     ...
#
