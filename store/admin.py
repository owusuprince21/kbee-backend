# store/admin.py
from __future__ import annotations

import json

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    # ✅ Needed now (catalog + homepage banners)
    Category,
    Product,
    ProductGalleryImage,
    HeroItem,
    CountdownDeal,
    HotItem,

    # ❌ Old e-commerce flow (kept for future — don't import/register now)
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

admin.site.site_header = "Kbee Computers"
admin.site.site_title = "Kbee Admin"
admin.site.index_title = "Dashboard"


# =============================================================================
# ACTIVE ADMIN (Needed now)
# =============================================================================

# --------------------
# Product & Gallery
# --------------------
class ProductGalleryInline(admin.TabularInline):
    model = ProductGalleryImage
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "brand",
        "price",
        "discount_price",
        "is_in_stock",
        "stock_quantity",
        "created_at",
    )
    list_filter = ("category", "brand", "is_featured", "is_new_arrival", "is_best_seller", "is_in_stock")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductGalleryInline]
    ordering = ("-created_at",)


# --------------------
# Category / Hero / Countdown
# --------------------
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")
    ordering = ("name",)


@admin.register(HeroItem)
class HeroItemAdmin(admin.ModelAdmin):
    list_display = ("product", "position", "active")
    list_editable = ("position", "active")
    search_fields = ("product__name",)
    ordering = ("position",)


@admin.register(CountdownDeal)
class CountdownDealAdmin(admin.ModelAdmin):
    list_display = ("product", "headline", "starts_at", "ends_at", "active", "is_running_display")
    list_filter = ("active",)
    search_fields = ("product__name", "headline", "subheadline")
    ordering = ("-starts_at",)

    @admin.display(description="Running?", boolean=True)
    def is_running_display(self, obj: CountdownDeal):
        return obj.is_running


# --------------------
# Hot Items / Banners
# --------------------
@admin.register(HotItem)
class HotItemAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "product",
        "slot",
        "position",
        "active",
        "is_running_display",
        "starts_at",
        "ends_at",
    )
    list_editable = ("position", "active")
    list_filter = ("active", "slot")
    search_fields = ("title", "product_title", "specs", "product__name")
    ordering = ("position", "-created_at")
    fieldsets = (
        (None, {"fields": ("product", "title", "product_title", "specs")}),
        ("Pricing", {"fields": ("price_override", "compare_at")}),
        ("CTA", {"fields": ("cta_text", "cta_href")}),
        ("Media", {"fields": ("image",)}),
        ("Display", {"fields": ("slot", "position", "starts_at", "ends_at", "active")}),
    )

    @admin.display(description="Running?", boolean=True)
    def is_running_display(self, obj: HotItem):
        return obj.is_running()


# =============================================================================
# INACTIVE / FUTURE ADMIN (Commented out intentionally)
# Old login/cart/checkout/payments admin panels
# =============================================================================

# --------------------
# Customer + inlines (AccountDetail & Address)
# --------------------
# class AccountDetailInline(admin.StackedInline):
#     model = AccountDetail
#     can_delete = True
#     extra = 0
#     max_num = 1
#     fieldsets = ((None, {"fields": ("phone", "bio")}),)
#
#
# class AddressInline(admin.TabularInline):
#     model = Address
#     extra = 0
#     fields = ("full_name", "line1", "line2", "city", "region", "postal_code", "country", "phone", "is_default")
#     show_change_link = True
#
#
# @admin.register(Customer)
# class CustomerAdmin(admin.ModelAdmin):
#     list_display = ("full_name_or_email", "email", "firebase_uid", "date_joined", "avatar")
#     search_fields = ("full_name", "email", "firebase_uid")
#     ordering = ("-date_joined",)
#     inlines = [AccountDetailInline, AddressInline]
#
#     @admin.display(description="Name / Email")
#     def full_name_or_email(self, obj: Customer):
#         return obj.full_name or obj.email
#
#     @admin.display(description="Avatar")
#     def avatar(self, obj: Customer):
#         if obj.photo_url:
#             return format_html(
#                 '<img src="{}" style="height:32px;width:32px;border-radius:50%;object-fit:cover;" />',
#                 obj.photo_url,
#             )
#         return "-"
#
#
# --------------------
# Address (standalone)
# --------------------
# @admin.register(Address)
# class AddressAdmin(admin.ModelAdmin):
#     list_display = ("customer", "full_name", "line1", "city", "region", "phone", "is_default", "created_at")
#     list_filter = ("is_default", "region", "city", "country")
#     search_fields = ("customer__full_name", "customer__email", "full_name", "line1", "city", "region", "phone")
#     ordering = ("-is_default", "-created_at")
#     list_editable = ("is_default",)
#     actions = ["make_default"]
#
#     @admin.action(description="Mark selected address(es) as default for their customer")
#     def make_default(self, request, queryset):
#         for addr in queryset:
#             if not addr.is_default:
#                 addr.is_default = True
#                 addr.save()
#
#
# --------------------
# Account Detail (standalone)
# --------------------
# @admin.register(AccountDetail)
# class AccountDetailAdmin(admin.ModelAdmin):
#     list_display = ("customer", "phone", "created_at", "updated_at")
#     search_fields = ("customer__full_name", "customer__email", "phone")
#     ordering = ("-created_at",)
#
#
# --------------------
# Carts / Wishlist / Reviews
# --------------------
# @admin.register(Cart)
# class CartAdmin(admin.ModelAdmin):
#     list_display = ("id", "customer", "created_at", "updated_at", "checked_out_at")
#     search_fields = ("customer__full_name", "customer__email")
#     ordering = ("-updated_at",)
#
#
# @admin.register(CartItem)
# class CartItemAdmin(admin.ModelAdmin):
#     list_display = ("cart", "product", "quantity", "unit_price", "added_at")
#     search_fields = ("cart__customer__full_name", "product__name")
#     ordering = ("-added_at",)
#
#
# @admin.register(WishlistItem)
# class WishlistItemAdmin(admin.ModelAdmin):
#     list_display = ("customer", "product", "added_at")
#     search_fields = ("customer__full_name", "product__name")
#     ordering = ("-added_at",)
#
#
# @admin.register(Review)
# class ReviewAdmin(admin.ModelAdmin):
#     list_display = ("product", "customer", "rating", "created_at")
#     list_filter = ("rating",)
#     search_fields = ("product__name", "customer__full_name", "comment")
#     ordering = ("-created_at",)
#
#
# --------------------
# Orders / OrderItems / Payment
# --------------------
# class OrderItemInline(admin.TabularInline):
#     model = OrderItem
#     extra = 0
#     can_delete = False
#     readonly_fields = ("product_name", "product_slug", "image_url", "quantity", "unit_price")
#
#
# @admin.register(Order)
# class OrderAdmin(admin.ModelAdmin):
#     list_display = ("code", "customer", "status", "currency", "total", "created_at")
#     list_filter = ("status", "currency", "created_at")
#     search_fields = ("code", "customer__email", "customer__full_name")
#     readonly_fields = ("code", "subtotal", "shipping", "total", "created_at", "updated_at")
#     inlines = [OrderItemInline]
#     ordering = ("-created_at",)
#
#
# @admin.register(Payment)
# class PaymentAdmin(admin.ModelAdmin):
#     list_display = (
#         "tx_ref",
#         "order_link",
#         "status_badge",
#         "amount_fmt",
#         "currency",
#         "network",
#         "provider",
#         "created_at",
#         "paid_at",
#     )
#     list_filter = ("provider", "status", "currency", "network", "created_at", "paid_at")
#     search_fields = ("tx_ref", "order__code", "order__id", "order__customer__email", "order__customer__full_name")
#     readonly_fields = (
#         "order",
#         "provider",
#         "tx_ref",
#         "psk_id",
#         "channel",
#         "network",
#         "status",
#         "amount",
#         "currency",
#         "raw_pretty",
#         "paid_at",
#         "completed_at",
#         "created_at",
#         "updated_at",
#     )
#     fieldsets = (
#         (None, {"fields": ("order",)}),
#         (
#             "Payment",
#             {"fields": ("provider", "tx_ref", "status", "amount", "currency", "network", "channel", "psk_id")},
#         ),
#         ("Timestamps", {"fields": ("created_at", "paid_at", "completed_at", "updated_at")}),
#         ("Gateway Payload (raw)", {"fields": ("raw_pretty",)}),
#     )
#     ordering = ("-created_at",)
#     date_hierarchy = "created_at"
#     list_select_related = ("order", "order__customer")
#
#     @admin.display(description="Order")
#     def order_link(self, obj: Payment):
#         if not obj.order_id:
#             return "—"
#         url = reverse("admin:store_order_change", args=[obj.order_id])
#         code = getattr(obj.order, "code", None) or f"#{obj.order_id}"
#         cust = getattr(getattr(obj.order, "customer", None), "full_name", "") or ""
#         label = f"{code} — {cust}" if cust else str(code)
#         return format_html('<a href="{}">{}</a>', url, label)
#
#     @admin.display(description="Status")
#     def status_badge(self, obj: Payment):
#         colors = {
#             "pending": ("#6b7280", "#f3f4f6"),
#             "successful": ("#065f46", "#d1fae5"),
#             "failed": ("#991b1b", "#fee2e2"),
#             "cancelled": ("#92400e", "#fef3c7"),
#         }
#         fg, bg = colors.get(obj.status, ("#111827", "#e5e7eb"))
#         text = (obj.status or "").title()
#         return format_html(
#             '<span style="padding:.15rem .5rem;border-radius:.5rem;background:{};color:{};font-weight:600;">{}</span>',
#             bg,
#             fg,
#             text,
#         )
#
#     @admin.display(description="Amount")
#     def amount_fmt(self, obj: Payment):
#         try:
#             return f"GHS {obj.amount:,.2f}"
#         except Exception:
#             return "—"
#
#     @admin.display(description="Raw payload", ordering="id")
#     def raw_pretty(self, obj: Payment):
#         try:
#             pretty = json.dumps(obj.raw or {}, indent=2, ensure_ascii=False)
#         except Exception:
#             pretty = str(obj.raw)
#         return mark_safe(f'<pre style="white-space:pre-wrap;word-wrap:break-word;">{pretty}</pre>')
