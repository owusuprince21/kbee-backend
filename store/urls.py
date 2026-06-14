# store/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    # ✅ Needed now (public browsing + homepage sections)
    CategoryViewSet,
    ProductViewSet,
    HeroItemViewSet,
    CountdownDealViewSet,
    HotItemViewSet,

    CartViewSet,
    WishlistViewSet,
    ReviewViewSet,
    CustomerViewSet,
    AddressViewSet,
    AccountDetailViewSet,
    OrderViewSet,
    ShippingRegionViewSet,
    ShippingTownViewSet,
)

from .views_checkout import (
    CheckoutView,
    InitializeCardFromCartView,
    InitializeCheckoutFromCartView,
    InitializeMoMoFromCartView,
    OrderReceiptView,
    VerifyPaymentView,
    PaystackWebhookView,
)

router = DefaultRouter()

# ✅ Active routes
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"products", ProductViewSet, basename="product")
router.register(r"hero", HeroItemViewSet, basename="hero")
router.register(r"countdown", CountdownDealViewSet, basename="countdown")
router.register(r"hot-items", HotItemViewSet, basename="hot-items")

router.register(r"reviews", ReviewViewSet, basename="review")
router.register(r"wishlist", WishlistViewSet, basename="wishlist")
router.register(r"customers", CustomerViewSet, basename="customer")
router.register(r"addresses", AddressViewSet, basename="address")
router.register(r"account", AccountDetailViewSet, basename="account")
router.register(r"orders", OrderViewSet, basename="order")
router.register(r"shipping/regions", ShippingRegionViewSet, basename="shipping-region")
router.register(r"shipping/towns", ShippingTownViewSet, basename="shipping-town")


# ---------------------------------------------------------------------------
# Old Cart/Wishlist endpoints (commented out)
# ---------------------------------------------------------------------------
cart_list   = CartViewSet.as_view({"get": "list"})
cart_clear  = CartViewSet.as_view({"post": "clear"})
cart_add    = CartViewSet.as_view({"post": "add_item"})
cart_update = CartViewSet.as_view({"patch": "update_item"})
cart_remove = CartViewSet.as_view({"delete": "remove_item"})


urlpatterns = [
    path("api/orders/receipt/<str:code>/", OrderReceiptView.as_view(), name="order-receipt"),
    path("api/orders/receipt/<str:code>/download/", OrderReceiptView.as_view(), {"download": True}, name="order-receipt-download"),

    # ✅ Keep the router endpoints (all read-only browsing + homepage data)
    path("api/", include(router.urls)),

    path("api/cart/", cart_list, name="cart-list"),
    path("api/cart/clear/", cart_clear, name="cart-clear"),
    path("api/cart/add_item/", cart_add, name="cart-add-item"),
    path("api/cart/update_item/<int:item_id>/", cart_update, name="cart-update-item"),
    path("api/cart/remove_item/<int:item_id>/", cart_remove, name="cart-remove-item"),

    path("api/checkout/", CheckoutView.as_view(), name="checkout"),
    path("api/payments/initialize_checkout_from_cart/", InitializeCheckoutFromCartView.as_view()),
    path("api/payments/initialize_from_cart/", InitializeMoMoFromCartView.as_view()),
    path("api/payments/initialize_card_from_cart/", InitializeCardFromCartView.as_view()),
    path("api/payments/verify/<str:tx_ref>/", VerifyPaymentView.as_view()),
    path("api/payments/webhook/paystack/", PaystackWebhookView.as_view()),
]
