# store/serializers.py
from __future__ import annotations

from typing import Any, List, Optional
from django.utils import timezone
from rest_framework import serializers

from .models import (
    Category,
    HotItem,
    Product,
    ProductGalleryImage,
    HeroItem,
    CountdownDeal,

    # NOTE:
    # The models below were part of the old e-commerce checkout + login flow.
    # They are intentionally NOT imported now because you commented them out in models.py.
    # Keeping these imports would crash Django at import time.
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

# =============================================================================
# ACTIVE SERIALIZERS (Needed now)
# - Category/Product catalog
# - Hero/Countdown/HotItem (homepage marketing sections)
# =============================================================================

# --- Helpers ----------------------------------------------------------------

class CloudinaryURLField(serializers.Field):
    def to_representation(self, value) -> str | None:
        try:
            return value.url
        except Exception:
            return None


def _safe_url(val) -> Optional[str]:
    """
    Best-effort to turn a CloudinaryField/ImageField/str into a usable https URL.
    Returns None if empty.
    """
    if not val:
        return None
    try:
        u = getattr(val, "url", None) or str(val) or ""
    except Exception:
        u = str(val) or ""
    u = u.strip()
    if not u:
        return None
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("http://"):
        u = u.replace("http://", "https://", 1)
    return u


# --- Category ---------------------------------------------------------------

class CategorySerializer(serializers.ModelSerializer):
    image_url = CloudinaryURLField(source="image", read_only=True)

    class Meta:
        model = Category
        fields = ("id", "name", "slug", "image_url", "description")


# --- Product & Gallery ------------------------------------------------------

class ProductGalleryImageSerializer(serializers.ModelSerializer):
    image_url = CloudinaryURLField(source="gallery_image", read_only=True)

    class Meta:
        model = ProductGalleryImage
        fields = ("id", "image_url", "order")


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)

    # Only needed if you create/update products through API.
    # If your API is read-only for products, you can remove category_id entirely.
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        write_only=True,
        source="category",
        required=False,
    )

    main_image_url = CloudinaryURLField(source="main_image", read_only=True)
    gallery = ProductGalleryImageSerializer(many=True, read_only=True)

    final_price = serializers.SerializerMethodField()
    discount_percent = serializers.SerializerMethodField()
    brand_display = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "price",
            "discount_price",
            "final_price",
            "discount_percent",
            "category",
            "category_id",
            "stock_quantity",
            "is_in_stock",
            "condition",
            "brand",
            "brand_display",
            "main_image_url",
            "gallery",
            "images",
            "specifications",
            "is_featured",
            "is_new_arrival",
            "is_best_seller",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("is_in_stock", "created_at", "updated_at")

    def get_final_price(self, obj: Product) -> str:
        return str(obj.discount_price or obj.price)

    def get_discount_percent(self, obj: Product) -> int:
        if obj.discount_price and obj.price:
            try:
                return int(round((float(obj.price - obj.discount_price) / float(obj.price)) * 100))
            except Exception:
                return 0
        return 0

    def get_brand_display(self, obj: Product) -> str:
        try:
            return obj.get_brand_display()
        except Exception:
            return obj.brand or ""

    def get_images(self, obj: Product) -> List[dict[str, Any]]:
        """
        Combined images list (main + gallery), compatible with your frontend.
        """
        imgs: List[dict[str, Any]] = []

        # main image
        u = _safe_url(getattr(obj, "main_image", None))
        if u:
            imgs.append({"id": 0, "image": u, "is_primary": True})

        # gallery images
        try:
            for g in obj.gallery.all():
                gu = _safe_url(getattr(g, "gallery_image", None))
                if gu:
                    imgs.append({"id": g.id, "image": gu, "is_primary": False})
        except Exception:
            pass

        return imgs


# --- Hero & Countdown -------------------------------------------------------

class HeroItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        write_only=True,
        source="product",
        required=False,
    )

    class Meta:
        model = HeroItem
        fields = ("id", "product", "product_id", "position", "headline", "subheadline", "active")


class CountdownDealSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        write_only=True,
        source="product",
        required=False,
    )
    image_url = serializers.SerializerMethodField()   # fallback if no explicit image is set
    is_running = serializers.SerializerMethodField()

    class Meta:
        model = CountdownDeal
        fields = (
            "id",
            "product",
            "product_id",
            "kicker",
            "headline",
            "subheadline",
            "cta_text",
            "cta_href",
            "image_url",
            "starts_at",
            "ends_at",
            "active",
            "is_running",
        )

    def get_image_url(self, obj) -> str | None:
        # 1) Countdown's own image
        u = _safe_url(getattr(obj, "image", None))
        if u:
            return u

        # 2) Product main image
        p = getattr(obj, "product", None)
        u = _safe_url(getattr(p, "main_image", None)) if p else None
        if u:
            return u

        # 3) First product gallery image
        try:
            g = p.gallery.first() if p else None
            return _safe_url(getattr(g, "gallery_image", None)) if g else None
        except Exception:
            return None

    def get_is_running(self, obj) -> bool:
        now = timezone.now()
        try:
            return bool(obj.active and obj.starts_at <= now <= obj.ends_at)
        except Exception:
            return False


# --- Hot Items / Banners ----------------------------------------------------

class HotItemSerializer(serializers.ModelSerializer):
    # Write-only: let clients set the product via id (admin can do it too)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), write_only=True, source="product", required=False
    )

    # Resolved fields for the banner
    cta_href   = serializers.SerializerMethodField()
    is_running = serializers.SerializerMethodField()
    image_url  = serializers.SerializerMethodField()

    # Product snapshot (flat)
    product_name        = serializers.SerializerMethodField()
    product_description = serializers.SerializerMethodField()
    product_slug        = serializers.SerializerMethodField()
    category_name       = serializers.SerializerMethodField()
    category_slug       = serializers.SerializerMethodField()
    brand               = serializers.SerializerMethodField()  # only for laptops category

    # Pricing snapshot
    price            = serializers.SerializerMethodField()  # final price to show
    discount_price   = serializers.SerializerMethodField()  # product discount price (if any)
    compare_at_price = serializers.SerializerMethodField()  # crossed-out price

    # Images
    main_image_url = serializers.SerializerMethodField()
    gallery_images = serializers.SerializerMethodField()  # [{id, image_url, is_primary}]

    class Meta:
        model  = HotItem
        fields = (
            "id",
            "title",
            "product_title",
            "specs",

            "cta_text",
            "cta_href",

            "image_url",

            # ordering/visibility (NOT a countdown)
            "slot",
            "position",
            "starts_at",
            "ends_at",
            "active",
            "is_running",

            # write-only
            "product_id",

            # product snapshot
            "product_name",
            "product_description",
            "product_slug",
            "category_name",
            "category_slug",
            "brand",

            # pricing
            "price",
            "discount_price",
            "compare_at_price",

            # images
            "main_image_url",
            "gallery_images",
        )

    # ---------- helpers ----------
    def _p(self, obj: HotItem) -> Optional[Product]:
        return getattr(obj, "product", None)

    # ---------- CTA / visibility ----------
    def get_cta_href(self, obj: HotItem) -> str:
        return obj.get_cta_href()

    def get_is_running(self, obj: HotItem) -> bool:
        return obj.is_running()

    # ---------- product snapshot ----------
    def get_product_name(self, obj: HotItem) -> Optional[str]:
        p = self._p(obj)
        return getattr(p, "name", None)

    def get_product_description(self, obj: HotItem) -> Optional[str]:
        p = self._p(obj)
        return getattr(p, "description", None)

    def get_product_slug(self, obj: HotItem) -> Optional[str]:
        p = self._p(obj)
        return getattr(p, "slug", None)

    def get_category_name(self, obj: HotItem) -> Optional[str]:
        p = self._p(obj)
        c = getattr(p, "category", None)
        return getattr(c, "name", None)

    def get_category_slug(self, obj: HotItem) -> Optional[str]:
        p = self._p(obj)
        c = getattr(p, "category", None)
        return getattr(c, "slug", None)

    def get_brand(self, obj: HotItem) -> Optional[str]:
        """
        Only surface brand for laptops.
        If Product.brand is a choice field, use its display method.
        """
        p = self._p(obj)
        if not p:
            return None
        c = getattr(p, "category", None)
        cname = (getattr(c, "name", "") or "").lower()
        if "laptop" in cname:
            try:
                return p.get_brand_display()
            except Exception:
                return getattr(p, "brand", None)
        return None

    # ---------- pricing ----------
    def get_price(self, obj: HotItem) -> str:
        """
        Final price that should be shown prominently:
        - price_override if provided
        - else product.discount_price if present
        - else product.price
        """
        p = self._p(obj)
        if obj.price_override is not None:
            return str(obj.price_override)
        if p and getattr(p, "discount_price", None) not in (None, ""):
            return str(p.discount_price)
        return str(getattr(p, "price", ""))

    def get_discount_price(self, obj: HotItem) -> Optional[str]:
        p = self._p(obj)
        dp = getattr(p, "discount_price", None)
        return str(dp) if dp not in (None, "") else None

    def get_compare_at_price(self, obj: HotItem) -> Optional[str]:
        """
        Crossed-out price logic:
        - if HotItem.compare_at is set -> use that
        - else if product has a discount -> use product.price
        - else if price_override is set -> also use product.price as the anchor
        - else None
        """
        if obj.compare_at is not None:
            return str(obj.compare_at)
        p = self._p(obj)
        if not p:
            return None
        if getattr(p, "discount_price", None):
            return str(getattr(p, "price", ""))
        if obj.price_override is not None:
            return str(getattr(p, "price", ""))
        return None

    # ---------- images ----------
    def get_main_image_url(self, obj: HotItem) -> Optional[str]:
        p = self._p(obj)
        return _safe_url(getattr(p, "main_image", None))

    def get_image_url(self, obj: HotItem) -> Optional[str]:
        """
        Banner image priority:
        1) Explicit HotItem.image
        2) Product.main_image
        3) First gallery image
        """
        # explicit banner image
        u = _safe_url(getattr(obj, "image", None))
        if u:
            return u

        # product main image
        p = self._p(obj)
        u = _safe_url(getattr(p, "main_image", None))
        if u:
            return u

        # first gallery image
        try:
            g = getattr(p, "gallery", None)
            first = g.first() if g else None
            return _safe_url(getattr(first, "gallery_image", None)) if first else None
        except Exception:
            return None

    def get_gallery_images(self, obj: HotItem) -> List[dict]:
        """
        Array of images combining main image (marked primary) and gallery images.
        """
        p = self._p(obj)
        items: List[dict] = []

        # main image (primary)
        mu = _safe_url(getattr(p, "main_image", None)) if p else None
        if mu:
            items.append({"id": 0, "image_url": mu, "is_primary": True})

        # gallery
        try:
            gal = getattr(p, "gallery", None)
            if gal:
                for g in gal.all():
                    url = _safe_url(getattr(g, "gallery_image", None))
                    if url:
                        items.append({"id": g.id, "image_url": url, "is_primary": False})
        except Exception:
            pass

        return items


# =============================================================================
# INACTIVE / FUTURE SERIALIZERS (Commented out intentionally)
# These match the old e-commerce checkout + login flow.
# Keep them here for later reuse, but do not import/use them now.
# =============================================================================

# --- Customer / Profile -----------------------------------------------------
#
# class CustomerSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Customer
#         fields = ("id", "firebase_uid", "email", "full_name", "photo_url", "date_joined")
#
#
# class AddressSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Address
#         fields = (
#             "id",
#             "full_name",
#             "line1",
#             "line2",
#             "city",
#             "region",
#             "postal_code",
#             "country",
#             "phone",
#             "is_default",
#             "created_at",
#             "updated_at",
#         )
#         read_only_fields = ("id", "created_at", "updated_at")
#
#     def create(self, validated_data):
#         customer = self.context.get("customer")
#         if customer is not None:
#             return Address.objects.create(customer=customer, **validated_data)
#         return super().create(validated_data)
#
#
# class AccountDetailSerializer(serializers.ModelSerializer):
#     customer = CustomerSerializer(read_only=True)
#
#     class Meta:
#         model = AccountDetail
#         fields = ("id", "customer", "bio", "phone", "created_at", "updated_at")
#         read_only_fields = ("id", "customer", "created_at", "updated_at")
#
#
# class CustomerMeSerializer(serializers.ModelSerializer):
#     phone = serializers.CharField(required=False, allow_blank=True)
#     bio = serializers.CharField(required=False, allow_blank=True)
#
#     class Meta:
#         model = Customer
#         fields = (
#             "id",
#             "firebase_uid",
#             "email",
#             "full_name",
#             "photo_url",
#             "phone",
#             "bio",
#             "date_joined",
#         )
#         read_only_fields = ("id", "firebase_uid", "date_joined")
#
#     def to_representation(self, instance: Customer) -> dict[str, Any]:
#         data = super().to_representation(instance)
#         acc = getattr(instance, "account", None)
#         data["phone"] = getattr(acc, "phone", "") or ""
#         data["bio"] = getattr(acc, "bio", "") or ""
#         return data
#
#     def update(self, instance: Customer, validated_data: dict[str, Any]) -> Customer:
#         phone = validated_data.pop("phone", None)
#         bio = validated_data.pop("bio", None)
#
#         for field, value in validated_data.items():
#             setattr(instance, field, value)
#         instance.save()
#
#         acc, _ = AccountDetail.objects.get_or_create(customer=instance)
#         changed = False
#         if phone is not None and phone != acc.phone:
#             acc.phone = phone
#             changed = True
#         if bio is not None and bio != acc.bio:
#             acc.bio = bio
#             changed = True
#         if changed:
#             acc.save()
#
#         return instance
#
#
# --- Cart & Items -----------------------------------------------------------
#
# class ProductMiniSerializer(serializers.ModelSerializer):
#     main_image_url = CloudinaryURLField(source="main_image", read_only=True)
#     images = serializers.SerializerMethodField()
#
#     class Meta:
#         model = Product
#         fields = ("id", "name", "slug", "price", "discount_price", "main_image_url", "images")
#
#     def get_images(self, obj: Product) -> List[dict[str, Any]]:
#         imgs: List[dict[str, Any]] = []
#         u = _safe_url(getattr(obj, "main_image", None))
#         if u:
#             imgs.append({"id": 0, "image": u, "is_primary": True})
#         try:
#             for g in obj.gallery.all():
#                 gu = _safe_url(getattr(g, "gallery_image", None))
#                 if gu:
#                     imgs.append({"id": g.id, "image": gu, "is_primary": False})
#         except Exception:
#             pass
#         return imgs
#
#
# class CartItemSerializer(serializers.ModelSerializer):
#     product = ProductMiniSerializer(read_only=True)
#     product_id = serializers.PrimaryKeyRelatedField(
#         queryset=Product.objects.all(),
#         write_only=True,
#         source="product",
#         required=False,
#     )
#     quantity = serializers.IntegerField(min_value=1, required=False, default=1)
#     subtotal = serializers.SerializerMethodField()
#
#     class Meta:
#         model = CartItem
#         fields = ("id", "product", "product_id", "quantity", "unit_price", "added_at", "subtotal")
#         read_only_fields = ("unit_price", "added_at", "subtotal")
#
#     def to_internal_value(self, data):
#         if isinstance(data, dict) and "product" in data and "product_id" not in data:
#             data = {**data, "product_id": data.get("product")}
#         return super().to_internal_value(data)
#
#     def validate(self, attrs):
#         if "product" not in attrs:
#             raise serializers.ValidationError({"product": "Provide product or product_id."})
#         return attrs
#
#     def get_subtotal(self, obj: "CartItem") -> str:
#         try:
#             return str(obj.subtotal())
#         except Exception:
#             unit = obj.unit_price or 0
#             qty = obj.quantity or 0
#             return str(unit * qty)
#
#
# class CartSerializer(serializers.ModelSerializer):
#     items = CartItemSerializer(many=True, read_only=True)
#     subtotal = serializers.SerializerMethodField()
#     is_active = serializers.ReadOnlyField()
#
#     class Meta:
#         model = Cart
#         fields = (
#             "id", "customer", "created_at", "updated_at", "checked_out_at",
#             "is_active", "items", "subtotal",
#         )
#         read_only_fields = ("customer", "created_at", "updated_at", "checked_out_at", "is_active", "subtotal")
#
#     def get_subtotal(self, obj: "Cart") -> str:
#         try:
#             return str(obj.subtotal())
#         except Exception:
#             total = 0
#             for it in obj.items.all():
#                 total += (it.unit_price or 0) * (it.quantity or 0)
#             return str(total)
#
#
# --- Wishlist ---------------------------------------------------------------
#
# class WishlistItemSerializer(serializers.ModelSerializer):
#     product = ProductSerializer(read_only=True)
#     product_id = serializers.PrimaryKeyRelatedField(
#         queryset=Product.objects.all(),
#         write_only=True,
#         source="product",
#         required=False,
#     )
#
#     class Meta:
#         model = WishlistItem
#         fields = ("id", "product", "product_id", "added_at")
#         read_only_fields = ("added_at",)
#
#     def to_internal_value(self, data):
#         if isinstance(data, dict) and "product" in data and "product_id" not in data:
#             data = {**data, "product_id": data.get("product")}
#         return super().to_internal_value(data)
#
#     def validate(self, attrs):
#         if "product" not in attrs:
#             raise serializers.ValidationError({"product": "Provide product or product_id."})
#         return attrs
#
#
# --- Reviews ----------------------------------------------------------------
#
# class CustomerSlimSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Customer
#         fields = ("id", "full_name", "email", "photo_url", "firebase_uid")
#
#
# class ReviewSerializer(serializers.ModelSerializer):
#     customer = CustomerSlimSerializer(read_only=True)
#     customer_name = serializers.SerializerMethodField()
#     product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
#     created_at = serializers.DateTimeField(read_only=True)
#     updated_at = serializers.DateTimeField(read_only=True)
#
#     class Meta:
#         model = Review
#         fields = (
#             "id",
#             "product",
#             "customer",
#             "customer_name",
#             "rating",
#             "comment",
#             "created_at",
#             "updated_at",
#             "customer_id",
#         )
#         read_only_fields = ("customer", "customer_id", "created_at", "updated_at", "customer_name")
#
#     def get_customer_name(self, obj: "Review") -> str:
#         return obj.customer.full_name or obj.customer.email or "Customer"
#
#
# --- Orders & Payments ------------------------------------------------------
#
# class OrderItemSlimSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = OrderItem
#         fields = ("id", "product", "product_name", "product_slug", "image_url", "quantity", "unit_price")
#
#
# class OrderSerializer(serializers.ModelSerializer):
#     items = OrderItemSlimSerializer(many=True, read_only=True)
#
#     class Meta:
#         model = Order
#         fields = (
#             "id", "code", "status", "currency",
#             "subtotal", "shipping", "total",
#             "ship_full_name", "ship_phone", "ship_line1", "ship_line2",
#             "ship_city", "ship_region", "ship_postal", "ship_country",
#             "notes", "created_at", "updated_at",
#             "items",
#         )
#
#
# class PaymentSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Payment
#         fields = (
#             "id", "provider", "tx_ref",
#             "psk_id", "channel", "network",
#             "status", "amount", "currency",
#             "raw", "paid_at", "completed_at", "created_at",
#         )
#         read_only_fields = (
#             "provider", "psk_id", "channel", "network",
#             "status", "amount", "currency",
#             "raw", "paid_at", "completed_at", "created_at",
#         )
