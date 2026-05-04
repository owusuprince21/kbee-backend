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

    # ❌ Old e-commerce flow (kept for future — do NOT import now)
    # CartViewSet,
    # WishlistViewSet,
    # ReviewViewSet,
    # CustomerViewSet,
    # AddressViewSet,
    # AccountDetailViewSet,
    # OrderViewSet,
)

# ❌ Old checkout/payments flow (kept for future — do NOT import now)
# from .views_checkout import (
#     CheckoutView,
#     InitializeCardFromCartView,
#     InitializeMoMoFromCartView,
#     VerifyPaymentView,
#     PaystackWebhookView,
# )

router = DefaultRouter()

# ✅ Active routes
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"products", ProductViewSet, basename="product")
router.register(r"hero", HeroItemViewSet, basename="hero")
router.register(r"countdown", CountdownDealViewSet, basename="countdown")
router.register(r"hot-items", HotItemViewSet, basename="hot-items")

# ❌ Old routes (commented for future)
# router.register(r"reviews", ReviewViewSet, basename="review")
# router.register(r"customers", CustomerViewSet, basename="customer")
# router.register(r"addresses", AddressViewSet, basename="address")
# router.register(r"account", AccountDetailViewSet, basename="account")
# router.register(r"orders", OrderViewSet, basename="order")


# ---------------------------------------------------------------------------
# Old Cart/Wishlist endpoints (commented out)
# ---------------------------------------------------------------------------
# Cart (custom actions on a ViewSet without pk)
# cart_list   = CartViewSet.as_view({"get": "list"})
# cart_clear  = CartViewSet.as_view({"post": "clear"})
# cart_add    = CartViewSet.as_view({"post": "add_item"})
# cart_update = CartViewSet.as_view({"patch": "update_item"})
# cart_remove = CartViewSet.as_view({"delete": "remove_item"})
#
# Wishlist (list/create + delete and delete-by-product)
# wishlist_list              = WishlistViewSet.as_view({"get": "list", "post": "create"})
# wishlist_detail            = WishlistViewSet.as_view({"delete": "destroy"})
# wishlist_remove_by_product = WishlistViewSet.as_view({"delete": "remove_by_product"})


urlpatterns = [
    # ✅ Keep the router endpoints (all read-only browsing + homepage data)
    path("api/", include(router.urls)),

    # ❌ Cart endpoints (future)
    # path("api/cart/", cart_list, name="cart-list"),
    # path("api/cart/clear/", cart_clear, name="cart-clear"),
    # path("api/cart/add_item/", cart_add, name="cart-add-item"),
    # path("api/cart/update_item/<int:item_id>/", cart_update, name="cart-update-item"),
    # path("api/cart/remove_item/<int:item_id>/", cart_remove, name="cart-remove-item"),

    # ❌ Wishlist endpoints (future)
    # path("api/wishlist/", wishlist_list, name="wishlist-list"),
    # path("api/wishlist/<int:pk>/", wishlist_detail, name="wishlist-delete"),
    # path("api/wishlist/by-product/<int:product_id>/", wishlist_remove_by_product, name="wishlist-remove-by-product"),

    # ❌ Checkout / Payments (future)
    # path("api/checkout/", CheckoutView.as_view(), name="checkout"),
    # path("api/payments/initialize_from_cart/", InitializeMoMoFromCartView.as_view()),
    # path("api/payments/initialize_card_from_cart/", InitializeCardFromCartView.as_view()),
    # path("api/payments/verify/<str:tx_ref>/", VerifyPaymentView.as_view()),
    # path("api/payments/webhook/paystack/", PaystackWebhookView.as_view()),
]
