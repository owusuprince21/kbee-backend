# store/models.py
from __future__ import annotations

from decimal import Decimal
import uuid

from django.db import models
from django.db.models import UniqueConstraint
from django.utils.text import slugify
from django.utils import timezone
from django.core.validators import RegexValidator
from django.db.models.signals import post_save
from django.dispatch import receiver
from cloudinary.models import CloudinaryField # type: ignore
from cloudinary_storage.storage import RawMediaCloudinaryStorage


# =============================================================================
# ACTIVE MODELS (Needed now)
# - Category/Product catalog
# - Gallery images
# - Homepage/marketing sections (Hero, Countdown, HotItem)
# =============================================================================

# ---- Categories / Brands ----------------------------------------------------

class MainCategory(models.TextChoices):
    LAPTOPS = "laptops", "Laptops"
    CHARGERS = "laptop-chargers", "Laptop Chargers"
    ROUTERS = "wifi-routers", "WiFi Routers"
    EXTERNAL_DRIVES = "external-drives", "External Drives"


class LaptopBrand(models.TextChoices):
    APPLE = "apple", "Apple (MacBook)"
    DELL = "dell", "Dell"
    HP = "hp", "HP (Hewlett-Packard)"
    LENOVO = "lenovo", "Lenovo"
    ASUS = "asus", "ASUS"
    ACER = "acer", "Acer"
    MICROSOFT = "microsoft", "Microsoft (Surface)"
    SAMSUNG = "samsung", "Samsung"
    MSI = "msi", "MSI (Micro-Star International)"
    RAZER = "razer", "Razer"
    LG = "lg", "LG (Gram)"
    TOSHIBA = "toshiba", "Toshiba / Dynabook"
    HUAWEI = "huawei", "Huawei"
    XIAOMI = "xiaomi", "Xiaomi"
    ACCESSORIES = "accessories", "Accessories"  # for non-laptop categories


class Category(models.Model):
    name = models.CharField(max_length=64, choices=MainCategory.choices, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    image = CloudinaryField("image", blank=True, null=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def __str__(self) -> str:
        return dict(MainCategory.choices).get(self.name, self.name)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


# ---- Products ---------------------------------------------------------------

class Product(models.Model):
    CONDITION_CHOICES = (("New", "New"), ("UK Used", "UK Used"))

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    description = models.TextField(blank=True)

    price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    stock_quantity = models.PositiveIntegerField(default=0)
    is_in_stock = models.BooleanField(default=True)

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default="UK Used")
    brand = models.CharField(
        max_length=40,
        choices=LaptopBrand.choices,
        default=LaptopBrand.ACCESSORIES,
    )

    # Images
    main_image = CloudinaryField("image")

    # Flags
    is_featured = models.BooleanField(default=False)
    is_new_arrival = models.BooleanField(default=False)
    is_best_seller = models.BooleanField(default=False)

    # Free-text specs
    specifications = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        from django.core.exceptions import ValidationError

        # For non-laptop categories, keep brand as "Accessories"
        if self.category and self.category.name != MainCategory.LAPTOPS and self.brand != LaptopBrand.ACCESSORIES:
            raise ValidationError("Brand must be 'Accessories' for non-laptop categories.")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        self.is_in_stock = self.stock_quantity > 0
        super().save(*args, **kwargs)


class ProductGalleryImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="gallery")
    gallery_image = CloudinaryField("image")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.product.name} gallery #{self.pk}"


# ---- Hero slider ------------------------------------------------------------

class HeroItem(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="hero_items")
    position = models.PositiveIntegerField(default=0)
    headline = models.CharField(max_length=200, blank=True)
    subheadline = models.CharField(max_length=300, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            UniqueConstraint(fields=["position"], name="unique_hero_position"),
            UniqueConstraint(fields=["product"], name="unique_product_in_hero"),
        ]

    def __str__(self) -> str:
        return f"Hero: {self.product.name} (pos {self.position})"


# ---- Countdown deal ---------------------------------------------------------

class CountdownDeal(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="countdown_deals")
    kicker = models.CharField(max_length=120, blank=True)
    headline = models.CharField(max_length=200)
    subheadline = models.CharField(max_length=300, blank=True)
    cta_text = models.CharField(max_length=80, default="Shop Now")
    cta_href = models.CharField(max_length=255, blank=True)
    image = CloudinaryField("image", blank=True, null=True)

    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_at"]
        indexes = [models.Index(fields=["active", "starts_at", "ends_at"])]

    def __str__(self) -> str:
        return f"Deal: {self.product.name}"

    @property
    def is_running(self) -> bool:
        now = timezone.now()
        return self.active and self.starts_at <= now <= self.ends_at

    def clean(self):
        super().clean()
        if not self.cta_href and self.product_id:
            self.cta_href = f"/product/{self.product.slug}"

    def get_cta_href(self) -> str:
        if self.cta_href:
            if not self.cta_href.startswith(("http://", "https://", "/")):
                return f"/product/{self.cta_href}"
            return self.cta_href
        if self.product_id:
            return f"/product/{self.product.slug}"
        return "/shop"


# ---- Hot Items / Banners ----------------------------------------------------

class HotItem(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="hot_items")

    # Content for the banner
    title = models.CharField(max_length=120, blank=True)                 # e.g. "External Drives" / "Laptop Chargers"
    product_title = models.CharField(max_length=200, blank=True)         # override product.name in the banner
    specs = models.TextField(blank=True)                                  # short blurb/spec lines

    # Pricing (optional overrides — fall back to product fields)
    price_override = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    compare_at = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)

    # CTA + media
    cta_text = models.CharField(max_length=80, default="Shop Now")
    cta_href = models.CharField(max_length=255, blank=True)              # can be absolute, /path, or bare slug
    image = CloudinaryField("image", blank=True, null=True)

    # Display / scheduling (NOT a countdown; just visibility)
    slot = models.CharField(
        max_length=10, blank=True,
        choices=[("left", "Left"), ("right", "Right")]
    )
    position = models.PositiveIntegerField(default=0)          # for ordering
    starts_at = models.DateTimeField(blank=True, null=True)
    ends_at = models.DateTimeField(blank=True, null=True)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "-created_at"]
        indexes = [models.Index(fields=["active", "position"])]

    def __str__(self) -> str:
        try:
            base = self.product.name
        except Exception:
            base = ""
        return f"HotItem: {self.title or base or f'#{self.pk}'}"

    # If author leaves fields blank, auto-populate from product
    def save(self, *args, **kwargs):
        p = self.product
        if p:
            # Title defaults to category name (if available) or product name
            if not self.title:
                self.title = (getattr(getattr(p, "category", None), "name", None) or p.name or "").strip()

            # Product title defaults to product.name
            if not self.product_title:
                self.product_title = (p.name or "").strip()

            # CTA defaults to product slug (resolved later to /product/slug)
            if not self.cta_href and getattr(p, "slug", None):
                self.cta_href = p.slug

            # If product has a discount and merchant didn’t set compare_at, show product.price as compare_at
            if self.compare_at is None and getattr(p, "discount_price", None):
                self.compare_at = p.price
        super().save(*args, **kwargs)

    def get_cta_href(self) -> str:
        raw = (self.cta_href or "").strip()
        if raw:
            if raw.startswith(("http://", "https://", "/")):
                return raw
            return f"/product/{raw}"
        if self.product_id and getattr(self.product, "slug", None):
            return f"/product/{self.product.slug}"
        return "/shop"

    def is_running(self) -> bool:
        """Visibility flag (no countdown)."""
        now = timezone.now()
        if not self.active:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.ends_at and self.ends_at < now:
            return False
        return True





# =============================================================================
# INACTIVE / FUTURE MODELS (Commented out intentionally)
# These were for e-commerce checkout + login.
# Keep them here for later reuse, but DO NOT migrate/run them now.
# =============================================================================

# ---- Customers --------------------------------------------------------------
#
# class Customer(models.Model):
#     firebase_uid = models.CharField(max_length=128, unique=True)
#     email = models.EmailField(unique=True)
#     full_name = models.CharField(max_length=150, blank=True)
#     photo_url = models.URLField(blank=True)
#     date_joined = models.DateTimeField(default=timezone.now)
#
#     def __str__(self) -> str:
#         return self.full_name or self.email


# ---- Cart / Wishlist / Reviews ---------------------------------------------
#
# class Cart(models.Model):
#     customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="carts")
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
#     checked_out_at = models.DateTimeField(blank=True, null=True)
#
#     class Meta:
#         ordering = ["-updated_at"]
#
#     def __str__(self) -> str:
#         return f"Cart #{self.pk} for {self.customer}"
#
#     @property
#     def is_active(self) -> bool:
#         return self.checked_out_at is None
#
#     def subtotal(self) -> float:
#         return sum(item.subtotal() for item in self.items.all())
#
#
# class CartItem(models.Model):
#     cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
#     product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="cart_items")
#     quantity = models.PositiveIntegerField(default=1)
#     unit_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
#     added_at = models.DateTimeField(auto_now_add=True)
#
#     class Meta:
#         constraints = [UniqueConstraint(fields=["cart", "product"], name="unique_product_per_cart")]
#
#     def __str__(self) -> str:
#         return f"{self.quantity} × {self.product.name}"
#
#     def save(self, *args, **kwargs):
#         if self.unit_price is None:
#             self.unit_price = self.product.discount_price or self.product.price
#         super().save(*args, **kwargs)
#
#     def subtotal(self) -> float:
#         return float(self.unit_price) * self.quantity
#
#
# class WishlistItem(models.Model):
#     customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="wishlist_items")
#     product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="wishlisted_by")
#     added_at = models.DateTimeField(default=timezone.now)
#
#     class Meta:
#         ordering = ["-added_at"]
#         constraints = [UniqueConstraint(fields=["customer", "product"], name="unique_wishlist_per_customer_product")]
#
#     def __str__(self) -> str:
#         return f"{self.customer} ♥ {self.product.name}"
#
#
# def validate_rating(value: int):
#     if not (1 <= value <= 5):
#         from django.core.exceptions import ValidationError
#         raise ValidationError("Rating must be between 1 and 5.")
#
#
# class Review(models.Model):
#     product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
#     customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="reviews")
#     rating = models.PositiveSmallIntegerField(validators=[validate_rating])
#     comment = models.TextField()
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now_add=True)
#
#     class Meta:
#         ordering = ["-created_at"]
#         constraints = [UniqueConstraint(fields=["product", "customer"], name="unique_review_per_customer_product")]
#
#     def __str__(self) -> str:
#         return f"Review {self.rating}★ by {self.customer} on {self.product.name}"


# ---- Address ----------------------------------------------------------------
#
# class Address(models.Model):
#     customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="addresses")
#
#     full_name = models.CharField(max_length=255, blank=True, null=True)
#     line1 = models.CharField("Address line 1", max_length=255)
#     line2 = models.CharField("Address line 2", max_length=255, blank=True, null=True)
#     city = models.CharField(max_length=100, blank=True, null=True)
#     region = models.CharField("Region / State", max_length=100, blank=True, null=True)
#     postal_code = models.CharField(max_length=20, blank=True, null=True)
#     country = models.CharField(max_length=60, blank=True, null=True, default="Ghana")
#     phone = models.CharField(
#         max_length=32, blank=True, null=True,
#         validators=[RegexValidator(r"^[\d+\-\s()]+$", "Invalid phone number.")]
#     )
#     is_default = models.BooleanField(default=False)
#
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
#
#     class Meta:
#         ordering = ["-is_default", "-created_at"]
#
#     def __str__(self) -> str:
#         who = self.full_name or self.customer.full_name or self.customer.email or "Recipient"
#         return f"{who}: {self.line1}, {self.city or ''}".strip()
#
#     def save(self, *args, **kwargs):
#         super().save(*args, **kwargs)
#         if self.is_default:
#             Address.objects.filter(customer=self.customer).exclude(pk=self.pk).update(is_default=False)


# ---- Account Details --------------------------------------------------------
#
# class AccountDetail(models.Model):
#     customer = models.OneToOneField("Customer", on_delete=models.CASCADE, related_name="account")
#     bio = models.TextField(blank=True)
#     phone = models.CharField(
#         max_length=32, blank=True,
#         validators=[RegexValidator(r"^[\d+\-\s()]+$", "Invalid phone number.")]
#     )
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
#
#     class Meta:
#         verbose_name = "Account detail"
#         verbose_name_plural = "Account details"
#
#     def __str__(self) -> str:
#         return f"Account for {self.customer.full_name or self.customer.email}"
#
#
# @receiver(post_save, sender=Customer)
# def ensure_account_detail(sender, instance: "Customer", created: bool, **kwargs):
#     if created:
#         AccountDetail.objects.get_or_create(customer=instance)


# ---- Orders, OrderItems, Payment integration --------------------------------
#
# class OrderStatus(models.TextChoices):
#     PENDING   = "pending", "Pending"
#     PAID      = "paid", "Paid"
#     FAILED    = "failed", "Failed"
#     CANCELLED = "cancelled", "Cancelled"
#     PACKAGED  = "packaged", "Packaged"
#     SHIPPED   = "shipped", "Shipped"
#     DELIVERED = "delivered", "Delivered"
#
#
# def _order_code() -> str:
#     return f"KB-{uuid.uuid4().hex[:8].upper()}"
#
#
# class Order(models.Model):
#     customer = models.ForeignKey("Customer", on_delete=models.CASCADE, related_name="orders")
#
#     ship_full_name = models.CharField(max_length=255, blank=True)
#     ship_line1     = models.CharField(max_length=255)
#     ship_line2     = models.CharField(max_length=255, blank=True)
#     ship_city      = models.CharField(max_length=100, blank=True)
#     ship_region    = models.CharField(max_length=100, blank=True)
#     ship_postal    = models.CharField(max_length=20, blank=True)
#     ship_country   = models.CharField(max_length=60, default="Ghana")
#     ship_phone     = models.CharField(max_length=32, blank=True)
#
#     code      = models.CharField(max_length=20, unique=True, default=_order_code, editable=False)
#     status    = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING)
#     currency  = models.CharField(max_length=8, default="GHS")
#     subtotal  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
#     shipping  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
#     total     = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
#
#     notes     = models.TextField(blank=True)
#
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
#
#     class Meta:
#         ordering = ["-created_at"]
#         indexes = [models.Index(fields=["code"]), models.Index(fields=["status", "-created_at"])]
#
#     def __str__(self):
#         return f"Order {self.code} ({self.get_status_display()})"
#
#     def recalc_totals(self):
#         sub = sum((it.unit_price * it.quantity for it in self.items.all()), Decimal("0.00"))
#         self.subtotal = sub
#         self.total = (self.subtotal or Decimal("0.00")) + (self.shipping or Decimal("0.00"))
#
#
# class OrderItem(models.Model):
#     order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
#     product = models.ForeignKey("Product", on_delete=models.PROTECT, related_name="order_items")
#
#     product_name = models.CharField(max_length=200)
#     product_slug = models.SlugField(max_length=220, blank=True)
#     image_url    = models.URLField(blank=True)
#
#     quantity   = models.PositiveIntegerField(default=1)
#     unit_price = models.DecimalField(max_digits=12, decimal_places=2)
#
#     class Meta:
#         ordering = ["id"]
#
#     def __str__(self):
#         return f"{self.quantity} × {self.product_name}"
#
#     def line_total(self) -> Decimal:
#         return self.unit_price * self.quantity
#
#
# class MoMoNetwork(models.TextChoices):
#     MTN       = "mtn", "MTN MoMo"
#     TGO       = "tgo", "AirtelTigo Money"
#     VODAFONE  = "vodafone", "Telecel/Vodafone"
#
#
# class PaymentStatus(models.TextChoices):
#     PENDING     = "pending", "Pending"
#     SUCCESSFUL  = "successful", "Successful"
#     FAILED      = "failed", "Failed"
#     CANCELLED   = "cancelled", "Cancelled"
#
#
# class Payment(models.Model):
#     order = models.ForeignKey(
#         "store.Order",
#         on_delete=models.SET_NULL,
#         related_name="payments",
#         null=True, blank=True,
#     )
#
#     provider   = models.CharField(max_length=20, default="paystack")
#     tx_ref     = models.CharField(max_length=64, unique=True)
#
#     psk_id     = models.BigIntegerField(blank=True, null=True)
#     channel    = models.CharField(max_length=32, default="mobile_money")
#     network    = models.CharField(max_length=20, choices=MoMoNetwork.choices, blank=True, default="")
#
#     status     = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
#     amount     = models.DecimalField(max_digits=12, decimal_places=2)
#     currency   = models.CharField(max_length=8, default="GHS")
#
#     raw        = models.JSONField(default=dict, blank=True)
#     paid_at    = models.DateTimeField(blank=True, null=True)
#     completed_at = models.DateTimeField(blank=True, null=True)
#
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
#
#     class Meta:
#         ordering = ["-created_at"]
#         indexes  = [
#             models.Index(fields=["tx_ref"]),
#             models.Index(fields=["provider", "psk_id"]),
#             models.Index(fields=["status", "-created_at"]),
#         ]
#
#     def __str__(self):
#         return f"{self.provider} {self.tx_ref} ({self.status})"
#
#     def mark_success(self, raw_payload: dict | None = None, paid_time: timezone.datetime | None = None):
#         self.status = PaymentStatus.SUCCESSFUL
#         self.paid_at = paid_time or timezone.now()
#         self.completed_at = self.paid_at
#         if raw_payload:
#             self.raw = {**(self.raw or {}), **raw_payload}
#             try:
#                 self.psk_id = raw_payload.get("data", {}).get("id") or self.psk_id
#             except Exception:
#                 pass
#         self.save(update_fields=["status", "paid_at", "completed_at", "raw", "psk_id", "updated_at"])
#
#     def mark_failed(self, raw_payload: dict | None = None):
#         self.status = PaymentStatus.FAILED
#         if raw_payload:
#             self.raw = {**(self.raw or {}), **raw_payload}
#         self.save(update_fields=["status", "raw", "updated_at"])


# =============================================================================
# ACTIVE COMMERCE MODELS
# =============================================================================

class Customer(models.Model):
    firebase_uid = models.CharField(max_length=160, unique=True)
    email = models.EmailField(blank=True)
    full_name = models.CharField(max_length=150, blank=True)
    photo_url = models.URLField(blank=True)
    is_guest = models.BooleanField(default=False)
    guest_key = models.CharField(max_length=160, unique=True, blank=True, null=True)
    date_joined = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-date_joined"]
        indexes = [models.Index(fields=["firebase_uid"]), models.Index(fields=["guest_key"])]

    def __str__(self) -> str:
        return self.full_name or self.email or self.firebase_uid


class Cart(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="carts")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    checked_out_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"Cart #{self.pk} for {self.customer}"

    @property
    def is_active(self) -> bool:
        return self.checked_out_at is None

    def subtotal(self) -> Decimal:
        return sum((item.subtotal() for item in self.items.all()), Decimal("0.00"))


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="cart_items")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [UniqueConstraint(fields=["cart", "product"], name="unique_product_per_cart")]
        ordering = ["-added_at"]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.product.name}"

    def save(self, *args, **kwargs):
        if self.unit_price is None:
            self.unit_price = self.product.discount_price or self.product.price
        super().save(*args, **kwargs)

    def subtotal(self) -> Decimal:
        return Decimal(self.unit_price or 0) * self.quantity


class WishlistItem(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="wishlist_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="wishlisted_by")
    added_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-added_at"]
        constraints = [UniqueConstraint(fields=["customer", "product"], name="unique_wishlist_per_customer_product")]

    def __str__(self) -> str:
        return f"{self.customer} wishlist {self.product.name}"


def validate_rating(value):
    rating = Decimal(str(value))
    if not (Decimal("0.5") <= rating <= Decimal("5.0")):
        from django.core.exceptions import ValidationError
        raise ValidationError("Rating must be between 0.5 and 5.")
    if (rating * Decimal("2")) % Decimal("1") != 0:
        from django.core.exceptions import ValidationError
        raise ValidationError("Rating must use half-star steps, like 3.5 or 4.0.")


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="reviews")
    rating = models.DecimalField(max_digits=2, decimal_places=1, validators=[validate_rating])
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [UniqueConstraint(fields=["product", "customer"], name="unique_review_per_customer_product")]

    def __str__(self) -> str:
        return f"Review {self.rating} by {self.customer} on {self.product.name}"


class Address(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="addresses")
    full_name = models.CharField(max_length=255, blank=True, null=True)
    line1 = models.CharField("Address line 1", max_length=255)
    line2 = models.CharField("Address line 2", max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    region = models.CharField("Region / State", max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=60, blank=True, null=True, default="Ghana")
    phone = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        validators=[RegexValidator(r"^[\d+\-\s()]+$", "Invalid phone number.")],
    )
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]

    def __str__(self) -> str:
        who = self.full_name or self.customer.full_name or self.customer.email or "Recipient"
        return f"{who}: {self.line1}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Address.objects.filter(customer=self.customer).exclude(pk=self.pk).update(is_default=False)


class AccountDetail(models.Model):
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name="account")
    bio = models.TextField(blank=True)
    phone = models.CharField(
        max_length=32,
        blank=True,
        validators=[RegexValidator(r"^[\d+\-\s()]+$", "Invalid phone number.")],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Account detail"
        verbose_name_plural = "Account details"

    def __str__(self):
        return f"Account for {self.customer}"


@receiver(post_save, sender=Customer)
def ensure_account_detail(sender, instance: Customer, created: bool, **kwargs):
    if created:
        AccountDetail.objects.get_or_create(customer=instance)


class ShippingRegion(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class ShippingTown(models.Model):
    region = models.ForeignKey(ShippingRegion, on_delete=models.CASCADE, related_name="towns")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=150)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["region__position", "region__name", "name"]
        constraints = [UniqueConstraint(fields=["region", "slug"], name="unique_shipping_town_per_region")]

    def __str__(self) -> str:
        return f"{self.name}, {self.region.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class CheckoutCharge(models.Model):
    name = models.CharField(max_length=80, default="Paystack charge")
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.98"))
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Checkout charge"
        verbose_name_plural = "Checkout charges"

    def __str__(self) -> str:
        state = "active" if self.active else "inactive"
        return f"{self.name}: {self.percentage}% ({state})"

    @classmethod
    def current_percentage(cls) -> Decimal:
        charge = cls.objects.filter(active=True).order_by("-updated_at", "-id").first()
        return Decimal(charge.percentage) if charge else Decimal("1.98")


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    PACKAGED = "packaged", "Packaged"
    SHIPPED = "shipped", "Shipped"
    DELIVERED = "delivered", "Delivered"


def _order_code() -> str:
    return f"KB-{uuid.uuid4().hex[:8].upper()}"


class Order(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="orders")
    ship_full_name = models.CharField(max_length=255, blank=True)
    ship_line1 = models.CharField(max_length=255)
    ship_line2 = models.CharField(max_length=255, blank=True)
    ship_city = models.CharField(max_length=100, blank=True)
    ship_region = models.CharField(max_length=100, blank=True)
    ship_postal = models.CharField(max_length=20, blank=True)
    ship_country = models.CharField(max_length=60, default="Ghana")
    ship_phone = models.CharField(max_length=32, blank=True)
    code = models.CharField(max_length=20, unique=True, default=_order_code, editable=False)
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING)
    currency = models.CharField(max_length=8, default="GHS")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    shipping = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    payment_charge = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    receipt_image = models.FileField(
        upload_to="receipts/",
        storage=RawMediaCloudinaryStorage(),
        blank=True,
        null=True,
    )
    receipt_generated_at = models.DateTimeField(blank=True, null=True)
    receipt_emailed_at = models.DateTimeField(blank=True, null=True)
    stock_deducted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["code"]), models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"Order {self.code} ({self.status})"

    def recalc_totals(self):
        self.subtotal = sum((it.line_total() for it in self.items.all()), Decimal("0.00"))
        self.total = (
            (self.subtotal or Decimal("0.00"))
            + (self.shipping or Decimal("0.00"))
            + (self.payment_charge or Decimal("0.00"))
        )


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    product_name = models.CharField(max_length=200)
    product_slug = models.SlugField(max_length=220, blank=True)
    image_url = models.URLField(blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"

    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


class MoMoNetwork(models.TextChoices):
    MTN = "mtn", "MTN MoMo"
    AIRTELTIGO = "airteltigo", "AirtelTigo Money"
    TELECEL = "telecel", "Telecel"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCESSFUL = "successful", "Successful"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class Payment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, related_name="payments", null=True, blank=True)
    provider = models.CharField(max_length=20, default="paystack")
    tx_ref = models.CharField(max_length=64, unique=True)
    psk_id = models.CharField(max_length=120, blank=True, null=True)
    channel = models.CharField(max_length=32, default="card")
    network = models.CharField(max_length=20, choices=MoMoNetwork.choices, blank=True, default="")
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default="GHS")
    raw = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tx_ref"]),
            models.Index(fields=["provider", "psk_id"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.provider} {self.tx_ref} ({self.status})"

    def mark_success(self, raw_payload: dict | None = None, paid_time: timezone.datetime | None = None):
        self.status = PaymentStatus.SUCCESSFUL
        self.paid_at = paid_time or timezone.now()
        self.completed_at = self.paid_at
        if raw_payload:
            self.raw = {**(self.raw or {}), **raw_payload}
            try:
                self.psk_id = raw_payload.get("data", {}).get("id") or self.psk_id
            except Exception:
                pass
        self.save(update_fields=["status", "paid_at", "completed_at", "raw", "psk_id", "updated_at"])

    def mark_failed(self, raw_payload: dict | None = None):
        self.status = PaymentStatus.FAILED
        if raw_payload:
            self.raw = {**(self.raw or {}), **raw_payload}
        self.save(update_fields=["status", "raw", "updated_at"])
