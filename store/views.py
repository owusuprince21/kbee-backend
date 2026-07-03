# store/views.py
from __future__ import annotations

from typing import Any
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from kbee.auth.firebase import customer_from_verified_claims

import django_filters
from django_filters.rest_framework import DjangoFilterBackend  # type: ignore

from .models import (
    AccountDetail,
    Address,
    Cart,
    CartItem,
    Category,
    Customer,
    HotItem,
    Order,
    OrderStatus,
    Product,
    HeroItem,
    CountdownDeal,
    Review,
    CheckoutCharge,
    ShippingRegion,
    ShippingTown,
    WishlistItem,

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
    AccountDetailSerializer,
    AddressSerializer,
    CartSerializer,
    CartItemSerializer,
    CategorySerializer,
    CustomerMeSerializer,
    CustomerSerializer,
    HotItemSerializer,
    OrderSerializer,
    ProductSerializer,
    HeroItemSerializer,
    CountdownDealSerializer,
    ReviewSerializer,
    ShippingRegionSerializer,
    ShippingTownSerializer,
    WishlistItemSerializer,

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
    throttle_scope = "catalog"


class ProductFilter(django_filters.FilterSet):
    category = django_filters.NumberFilter(field_name="category", lookup_expr="exact")
    category__slug = django_filters.CharFilter(field_name="category__slug", lookup_expr="exact")
    brand = django_filters.CharFilter(method="filter_brand")
    condition = django_filters.CharFilter(field_name="condition", lookup_expr="exact")
    is_featured = django_filters.BooleanFilter(field_name="is_featured")
    is_new_arrival = django_filters.BooleanFilter(field_name="is_new_arrival")
    is_best_seller = django_filters.BooleanFilter(field_name="is_best_seller")
    is_in_stock = django_filters.BooleanFilter(field_name="is_in_stock")

    class Meta:
        model = Product
        fields = []

    def filter_brand(self, queryset, name, value):
        if not value or str(value).strip().lower() in {"undefined", "null"}:
            return queryset
        return queryset.filter(brand__iexact=str(value).strip())


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
    filterset_class = ProductFilter
    search_fields = ["name"]
    ordering_fields = ["created_at", "updated_at", "price", "discount_price", "name"]
    throttle_scope = "catalog"

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

class HeroItemViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = HeroItem.objects.select_related("product").order_by("position")
    serializer_class = HeroItemSerializer
    permission_classes = [AllowAny]
    throttle_scope = "catalog"


class CountdownDealViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        CountdownDeal.objects
        .select_related("product")
        .prefetch_related("product__gallery")
        .all()
    )
    serializer_class = CountdownDealSerializer
    permission_classes = [AllowAny]
    throttle_scope = "catalog"

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

class HotItemViewSet(viewsets.ReadOnlyModelViewSet):
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
    throttle_scope = "catalog"

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
# ACTIVE COMMERCE VIEWSETS
# =============================================================================

CUSTOMER_SESSION_KEY = "customer_id"


def customer_from_session(request) -> Customer | None:
    customer_id = request.session.get(CUSTOMER_SESSION_KEY)
    if not customer_id:
        return None
    return Customer.objects.filter(pk=customer_id, is_guest=False).first()


def customer_from_guest_key(request) -> Customer | None:
    guest_key = request.headers.get("X-Guest-ID") or ""
    if not guest_key:
        return None
    return Customer.objects.filter(guest_key=guest_key, is_guest=True).first()


def get_existing_customer(request) -> Customer | None:
    try:
        customer = customer_from_verified_claims(request)
    except AuthenticationFailed as exc:
        if request_has_firebase_auth_material(request):
            raise exc
        customer = None
    if customer:
        remember_customer_session(request, customer)
        return customer

    customer = customer_from_session(request)
    if customer:
        return customer

    return customer_from_guest_key(request)


def empty_cart_data() -> dict:
    return {
        "id": 0,
        "customer": None,
        "created_at": None,
        "updated_at": None,
        "checked_out_at": None,
        "is_active": True,
        "items": [],
        "subtotal": "0.00",
    }


def remember_customer_session(request, customer: Customer) -> None:
    if customer.is_guest:
        return
    request.session[CUSTOMER_SESSION_KEY] = customer.pk
    request.session.modified = True


def request_has_firebase_auth_material(request) -> bool:
    authorization = request.headers.get("Authorization") or ""
    return authorization.startswith("Bearer ") or bool(request.headers.get("X-Firebase-UID"))


def get_or_create_customer(request) -> Customer:
    try:
        customer = customer_from_verified_claims(request)
    except AuthenticationFailed as exc:
        if request_has_firebase_auth_material(request):
            raise exc
        customer = None
    if not customer and request_has_firebase_auth_material(request):
        raise AuthenticationFailed("Firebase authentication is required for this request.")
    if customer:
        remember_customer_session(request, customer)
        guest_key = request.headers.get("X-Guest-ID") or ""
        if guest_key:
            merge_guest_customer_into_customer(guest_key, customer)
        return customer

    customer = customer_from_session(request)
    if customer:
        guest_key = request.headers.get("X-Guest-ID") or ""
        if guest_key:
            merge_guest_customer_into_customer(guest_key, customer)
        return customer

    body_email = ""
    try:
        body_email = request.data.get("email", "") if hasattr(request, "data") else ""
    except Exception:
        body_email = ""
    email = body_email
    full_name = ""
    guest_key = request.headers.get("X-Guest-ID") or ""
    if not guest_key:
        if not request.session.session_key:
            request.session.create()
        guest_key = request.session.session_key
    if not guest_key:
        raise PermissionDenied("No Firebase user or guest identity found.")

    customer, _ = Customer.objects.get_or_create(
        firebase_uid=f"guest:{guest_key}",
        defaults={
            "guest_key": guest_key,
            "email": email or f"{guest_key}@guest.local",
            "full_name": full_name or "Guest customer",
            "is_guest": True,
        },
    )
    changed = []
    if email and customer.email != email:
        customer.email = email
        changed.append("email")
    if full_name and customer.full_name != full_name:
        customer.full_name = full_name
        changed.append("full_name")
    if changed:
        customer.save(update_fields=changed)
    return customer


def get_registered_customer(request) -> Customer:
    try:
        customer = customer_from_verified_claims(request)
    except AuthenticationFailed as exc:
        if request_has_firebase_auth_material(request):
            raise exc
        customer = None
    if customer and not customer.is_guest:
        remember_customer_session(request, customer)
        return customer

    customer = customer_from_session(request)
    if customer and not customer.is_guest:
        return customer

    raise PermissionDenied("Sign in is required for this request.")


def claim_guest_orders_from_header(request, customer: Customer) -> None:
    if customer.is_guest:
        return

    claim_filter = Q()

    raw_codes = request.headers.get("X-Claim-Order-Codes") or ""
    codes = {
        code.strip().upper()
        for code in raw_codes.split(",")
        if code.strip()
    }
    if codes:
        claim_filter |= Q(code__in=codes)

    if customer.email:
        claim_filter |= Q(customer__email__iexact=customer.email)
        claim_filter |= Q(payments__raw__init__email__iexact=customer.email)
        claim_filter |= Q(payments__raw__verify__data__customer__email__iexact=customer.email)
        claim_filter |= Q(payments__raw__webhook__data__customer__email__iexact=customer.email)
        claim_filter |= Q(payments__raw__init_gateway__data__customer__email__iexact=customer.email)

    if not claim_filter:
        return

    Order.objects.filter(
        claim_filter,
        customer__is_guest=True,
    ).update(customer=customer, updated_at=timezone.now())


def get_active_cart(customer: Customer) -> Cart:
    carts = list(
        Cart.objects
        .filter(customer=customer, checked_out_at=None)
        .order_by("-updated_at", "-id")
        .prefetch_related("items__product")
    )
    if not carts:
        return Cart.objects.create(customer=customer)

    primary = carts[0]
    duplicate_carts = carts[1:]
    for duplicate in duplicate_carts:
        for duplicate_item in duplicate.items.select_related("product"):
            target_item, created = CartItem.objects.get_or_create(
                cart=primary,
                product=duplicate_item.product,
                defaults={
                    "quantity": duplicate_item.quantity,
                    "unit_price": duplicate_item.unit_price or duplicate_item.product.discount_price or duplicate_item.product.price,
                },
            )
            if not created:
                target_item.quantity += duplicate_item.quantity
                if target_item.unit_price is None:
                    target_item.unit_price = duplicate_item.unit_price or duplicate_item.product.discount_price or duplicate_item.product.price
                target_item.save(update_fields=["quantity", "unit_price"])
        duplicate.items.all().delete()
        duplicate.checked_out_at = timezone.now()
        duplicate.save(update_fields=["checked_out_at", "updated_at"])

    return primary


def merge_guest_customer_into_customer(guest_key: str, customer: Customer) -> None:
    if not guest_key:
        return
    guest = Customer.objects.filter(guest_key=guest_key, is_guest=True).exclude(pk=customer.pk).first()
    if not guest:
        return

    Order.objects.filter(customer=guest).update(customer=customer)
    Address.objects.filter(customer=guest).update(customer=customer)

    guest_account = getattr(guest, "account", None)
    customer_account, _ = AccountDetail.objects.get_or_create(customer=customer)
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

    guest_cart = Cart.objects.filter(customer=guest, checked_out_at=None).prefetch_related("items__product").first()
    if guest_cart and guest_cart.items.exists():
        target_cart = get_active_cart(customer)
        for guest_item in guest_cart.items.select_related("product"):
            target_item, created = CartItem.objects.get_or_create(
                cart=target_cart,
                product=guest_item.product,
                defaults={
                    "quantity": guest_item.quantity,
                    "unit_price": guest_item.unit_price or guest_item.product.discount_price or guest_item.product.price,
                },
            )
            if not created:
                target_item.quantity += guest_item.quantity
                if target_item.unit_price is None:
                    target_item.unit_price = guest_item.unit_price or guest_item.product.discount_price or guest_item.product.price
                target_item.save(update_fields=["quantity", "unit_price"])
        guest_cart.items.all().delete()
        guest_cart.checked_out_at = timezone.now()
        guest_cart.save(update_fields=["checked_out_at", "updated_at"])

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


def fresh_cart_data(cart: Cart) -> dict:
    fresh = (
        Cart.objects
        .prefetch_related("items__product", "items__product__category", "items__product__gallery")
        .get(pk=cart.pk)
    )
    return CartSerializer(fresh).data


def validate_product_stock(product: Product, quantity: int) -> None:
    available = int(product.stock_quantity or 0)
    if not product.is_in_stock or available <= 0:
        raise ValidationError({"detail": f"{product.name} is out of stock."})
    if quantity > available:
        raise ValidationError({"detail": f"Only {available} unit(s) of {product.name} available."})


class CartViewSet(viewsets.ViewSet):
    serializer_class = CartSerializer
    permission_classes = [AllowAny]
    throttle_scope = "cart"

    def list(self, request):
        customer = get_existing_customer(request)
        if not customer:
            return Response(empty_cart_data())
        cart = get_active_cart(customer)
        return Response(CartSerializer(cart).data)

    @action(detail=False, methods=["post"])
    def add_item(self, request):
        customer = get_or_create_customer(request)
        cart = get_active_cart(customer)
        ser = CartItemSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        product = ser.validated_data["product"]
        quantity = int(ser.validated_data.get("quantity") or 1)
        item, created = CartItem.objects.get_or_create(cart=cart, product=product)
        new_quantity = quantity if created else item.quantity + quantity
        validate_product_stock(product, new_quantity)
        if created:
            item.quantity = quantity
        else:
            item.quantity += quantity
        item.unit_price = product.discount_price or product.price
        item.save()
        return Response(fresh_cart_data(cart), status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["patch"], url_path=r"update_item/(?P<item_id>\d+)")
    def update_item(self, request, item_id=None):
        customer = get_or_create_customer(request)
        cart = get_active_cart(customer)
        item = get_object_or_404(CartItem, pk=item_id, cart=cart)
        item.quantity = max(1, int(request.data.get("quantity") or 1))
        validate_product_stock(item.product, item.quantity)
        item.save(update_fields=["quantity"])
        return Response(fresh_cart_data(cart))

    @action(detail=False, methods=["delete"], url_path=r"remove_item/(?P<item_id>\d+)")
    def remove_item(self, request, item_id=None):
        customer = get_or_create_customer(request)
        cart = get_active_cart(customer)
        CartItem.objects.filter(pk=item_id, cart=cart).delete()
        return Response(fresh_cart_data(cart))

    @action(detail=False, methods=["post"])
    def clear(self, request):
        customer = get_or_create_customer(request)
        cart = get_active_cart(customer)
        cart.items.all().delete()
        return Response(fresh_cart_data(cart))


class WishlistViewSet(viewsets.ModelViewSet):
    serializer_class = WishlistItemSerializer
    permission_classes = [AllowAny]
    throttle_scope = "write"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WishlistItem.objects.none()
        customer = get_existing_customer(self.request)
        if not customer:
            return WishlistItem.objects.none()
        return WishlistItem.objects.filter(customer=customer).select_related("product", "product__category")

    def perform_create(self, serializer):
        customer = get_or_create_customer(self.request)
        product = serializer.validated_data["product"]
        item, _ = WishlistItem.objects.get_or_create(customer=customer, product=product)
        serializer.instance = item

    @action(detail=False, methods=["delete"], url_path=r"by-product/(?P<product_id>\d+)")
    def remove_by_product(self, request, product_id=None):
        customer = get_existing_customer(request)
        if not customer:
            return Response(status=status.HTTP_204_NO_CONTENT)
        WishlistItem.objects.filter(customer=customer, product_id=product_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["product"]
    ordering_fields = ["created_at", "rating"]
    throttle_scope = "reviews"

    def get_queryset(self):
        return Review.objects.select_related("customer", "product").all()

    def customer_can_review(self, customer: Customer, product: Product) -> bool:
        return Order.objects.filter(
            customer=customer,
            status__in=[
                OrderStatus.PAID,
                OrderStatus.PACKAGED,
                OrderStatus.SHIPPED,
                OrderStatus.DELIVERED,
            ],
            items__product=product,
        ).exists()

    def perform_create(self, serializer):
        customer = get_or_create_customer(self.request)
        product = serializer.validated_data["product"]
        if not self.customer_can_review(customer, product):
            raise ValidationError({"detail": "You can only review products you have purchased."})
        review, _ = Review.objects.update_or_create(
            customer=customer,
            product=product,
            defaults={
                "rating": serializer.validated_data["rating"],
                "comment": serializer.validated_data["comment"],
            },
        )
        serializer.instance = review

    def destroy(self, request, *args, **kwargs):
        customer = get_or_create_customer(request)
        review = self.get_object()
        if review.customer_id != customer.id:
            raise PermissionDenied("You can only delete your own review.")
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=["get"])
    def eligibility(self, request):
        product_id = request.query_params.get("product")
        product = get_object_or_404(Product, pk=product_id)
        customer = get_existing_customer(request)
        review = Review.objects.filter(customer=customer, product=product).first() if customer else None
        return Response(
            {
                "can_review": self.customer_can_review(customer, product) if customer else False,
                "has_review": bool(review),
                "review_id": review.id if review else None,
            }
        )


class AddressViewSet(viewsets.ModelViewSet):
    serializer_class = AddressSerializer
    permission_classes = [AllowAny]
    throttle_scope = "write"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Address.objects.none()
        customer = get_existing_customer(self.request)
        if not customer:
            return Address.objects.none()
        return Address.objects.filter(customer=customer)

    def perform_create(self, serializer):
        customer = get_or_create_customer(self.request)
        serializer.save(customer=customer)


class AccountDetailViewSet(viewsets.ViewSet):
    serializer_class = AccountDetailSerializer
    permission_classes = [AllowAny]
    throttle_scope = "write"

    def list(self, request):
        customer = get_or_create_customer(request)
        account, _ = AccountDetail.objects.get_or_create(customer=customer)
        return Response(AccountDetailSerializer(account).data)


class CustomerViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [AllowAny]
    throttle_scope = "write"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Customer.objects.none()
        customer = get_or_create_customer(self.request)
        return Customer.objects.filter(pk=customer.pk)

    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        customer = get_or_create_customer(request)
        if request.method.lower() == "patch":
            serializer = CustomerMeSerializer(customer, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        return Response(CustomerMeSerializer(customer).data)

    @action(detail=False, methods=["get"], url_path="session")
    def session(self, request):
        customer = customer_from_session(request)
        if not customer:
            raise PermissionDenied("No active customer session.")
        return Response(CustomerMeSerializer(customer).data)

    @action(detail=False, methods=["post"], url_path="logout")
    def logout(self, request):
        request.session.flush()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [AllowAny]
    throttle_scope = "write"
    lookup_value_regex = r"[^/]+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        customer = get_registered_customer(self.request)
        claim_guest_orders_from_header(self.request, customer)
        return Order.objects.filter(customer=customer).prefetch_related("items", "items__product")

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)
        if lookup and str(lookup).isdigit():
            obj = get_object_or_404(queryset, pk=lookup)
        else:
            obj = get_object_or_404(queryset, code__iexact=lookup)
        self.check_object_permissions(self.request, obj)
        return obj


class ShippingRegionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ShippingRegion.objects.filter(active=True).order_by("position", "name")
    serializer_class = ShippingRegionSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"
    throttle_scope = "catalog"


class ShippingTownViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ShippingTownSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"
    throttle_scope = "catalog"

    def get_queryset(self):
        qs = ShippingTown.objects.filter(active=True, region__active=True).select_related("region")
        region = self.request.query_params.get("region")
        if region:
            qs = qs.filter(region__slug=region)
        return qs

    @action(detail=False, methods=["get"])
    def quote(self, request):
        town_id = request.query_params.get("town_id")
        base = Decimal(str(request.query_params.get("base") or "0"))
        town = get_object_or_404(self.get_queryset(), pk=town_id)
        shipping = Decimal(town.fee)
        charge_percent = CheckoutCharge.current_percentage()
        charge_base = base + shipping
        payment_charge = (charge_base * charge_percent / Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        total = charge_base + payment_charge
        return Response(
            {
                "town": ShippingTownSerializer(town).data,
                "subtotal": str(base),
                "shipping_fee": str(shipping),
                "charge_percent": str(charge_percent),
                "payment_charge": str(payment_charge),
                "total": str(total),
            }
        )

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
