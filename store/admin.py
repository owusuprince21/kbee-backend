# store/admin.py
from __future__ import annotations

import json

from django import forms
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
    ShippingRegion,
    ShippingTown,
    CheckoutCharge,
    Customer,
    Address,
    AccountDetail,
    Cart,
    CartItem,
    WishlistItem,
    Review,
    Order,
    OrderItem,
    Payment,
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


class ShippingTownInline(admin.TabularInline):
    model = ShippingTown
    extra = 1
    fields = ("name", "slug", "fee", "active")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ShippingRegion)
class ShippingRegionAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "position", "active", "town_count")
    list_editable = ("position", "active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ShippingTownInline]
    ordering = ("position", "name")

    @admin.display(description="Towns")
    def town_count(self, obj: ShippingRegion):
        return obj.towns.count()


@admin.register(ShippingTown)
class ShippingTownAdmin(admin.ModelAdmin):
    list_display = ("name", "region", "fee", "active")
    list_filter = ("region", "active")
    search_fields = ("name", "slug", "region__name")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(CheckoutCharge)
class CheckoutChargeAdmin(admin.ModelAdmin):
    list_display = ("name", "percentage", "active", "updated_at")
    list_editable = ("percentage", "active")
    search_fields = ("name",)


# --------------------
# Customers / Guest Customers
# --------------------
class AccountDetailInline(admin.StackedInline):
    model = AccountDetail
    can_delete = True
    extra = 0
    max_num = 1
    fields = ("phone", "bio", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0
    fields = ("full_name", "line1", "line2", "city", "region", "postal_code", "country", "phone", "is_default", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "avatar",
        "full_name_or_email",
        "customer_type",
        "email",
        "phone_number",
        "firebase_uid_short",
        "orders_count",
        "date_joined",
    )
    list_filter = ("is_guest", "date_joined")
    search_fields = ("full_name", "email", "firebase_uid", "guest_key", "account__phone")
    readonly_fields = ("firebase_uid", "guest_key", "is_guest", "date_joined", "avatar_large")
    fieldsets = (
        ("Customer", {"fields": ("avatar_large", "full_name", "email", "photo_url", "is_guest")}),
        ("Identity", {"fields": ("firebase_uid", "guest_key")}),
        ("Timestamps", {"fields": ("date_joined",)}),
    )
    inlines = [AccountDetailInline, AddressInline]
    ordering = ("-date_joined",)

    @admin.display(description="Name / Email", ordering="full_name")
    def full_name_or_email(self, obj: Customer):
        return obj.full_name or obj.email or ("Guest customer" if obj.is_guest else obj.firebase_uid)

    @admin.display(description="Type", ordering="is_guest")
    def customer_type(self, obj: Customer):
        if obj.is_guest:
            return format_html('<span style="font-weight:600;color:#92400e;">Guest</span>')
        return format_html('<span style="font-weight:600;color:#065f46;">Registered</span>')

    @admin.display(description="Firebase UID")
    def firebase_uid_short(self, obj: Customer):
        uid = obj.firebase_uid or ""
        return uid if len(uid) <= 22 else f"{uid[:10]}...{uid[-8:]}"

    @admin.display(description="Phone")
    def phone_number(self, obj: Customer):
        account_phone = getattr(getattr(obj, "account", None), "phone", "")
        if account_phone:
            return account_phone
        address = obj.addresses.order_by("-is_default", "-created_at").first()
        return getattr(address, "phone", "") or "—"

    @admin.display(description="Orders")
    def orders_count(self, obj: Customer):
        return obj.orders.count()

    @admin.display(description="Avatar")
    def avatar(self, obj: Customer):
        if obj.photo_url:
            return format_html(
                '<img src="{}" style="height:32px;width:32px;border-radius:50%;object-fit:cover;" />',
                obj.photo_url,
            )
        return "—"

    @admin.display(description="Google avatar")
    def avatar_large(self, obj: Customer):
        if obj.photo_url:
            return format_html(
                '<img src="{}" style="height:72px;width:72px;border-radius:50%;object-fit:cover;" />',
                obj.photo_url,
            )
        return "—"


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("customer", "customer_type", "full_name", "line1", "city", "region", "phone", "is_default", "created_at")
    list_filter = ("is_default", "region", "city", "country", "customer__is_guest")
    search_fields = ("customer__full_name", "customer__email", "customer__firebase_uid", "full_name", "line1", "city", "region", "phone")
    ordering = ("-is_default", "-created_at")
    list_editable = ("is_default",)

    @admin.display(description="Type")
    def customer_type(self, obj: Address):
        return "Guest" if obj.customer.is_guest else "Registered"


@admin.register(AccountDetail)
class AccountDetailAdmin(admin.ModelAdmin):
    list_display = ("customer", "customer_type", "phone", "created_at", "updated_at")
    list_filter = ("customer__is_guest", "created_at")
    search_fields = ("customer__full_name", "customer__email", "customer__firebase_uid", "phone")
    ordering = ("-created_at",)

    @admin.display(description="Type")
    def customer_type(self, obj: AccountDetail):
        return "Guest" if obj.customer.is_guest else "Registered"


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "customer_type", "items_count", "subtotal_display", "created_at", "updated_at", "checked_out_at")
    list_filter = ("customer__is_guest", "checked_out_at", "created_at")
    search_fields = ("customer__full_name", "customer__email", "customer__firebase_uid")
    ordering = ("-updated_at",)

    @admin.display(description="Type")
    def customer_type(self, obj: Cart):
        return "Guest" if obj.customer.is_guest else "Registered"

    @admin.display(description="Items")
    def items_count(self, obj: Cart):
        return obj.items.count()

    @admin.display(description="Subtotal")
    def subtotal_display(self, obj: Cart):
        return f"GHS {obj.subtotal():,.2f}"


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ("cart", "product", "quantity", "unit_price", "added_at")
    search_fields = ("cart__customer__full_name", "cart__customer__email", "product__name")
    ordering = ("-added_at",)


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ("customer", "customer_type", "product", "added_at")
    list_filter = ("customer__is_guest", "added_at")
    search_fields = ("customer__full_name", "customer__email", "product__name")
    ordering = ("-added_at",)

    @admin.display(description="Type")
    def customer_type(self, obj: WishlistItem):
        return "Guest" if obj.customer.is_guest else "Registered"


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "customer", "customer_type", "rating", "created_at")
    list_filter = ("rating", "customer__is_guest", "created_at")
    search_fields = ("product__name", "customer__full_name", "customer__email", "comment")
    ordering = ("-created_at",)

    @admin.display(description="Type")
    def customer_type(self, obj: Review):
        return "Guest" if obj.customer.is_guest else "Registered"


# --------------------
# Orders / Payments
# --------------------
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "product_name", "product_slug", "image_url", "quantity", "unit_price", "line_total_display")
    fields = ("product", "product_name", "quantity", "unit_price", "line_total_display")

    @admin.display(description="Line total")
    def line_total_display(self, obj: OrderItem):
        try:
            return f"GHS {obj.line_total():,.2f}"
        except Exception:
            return "—"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    class ChangelistForm(forms.ModelForm):
        class Meta:
            model = Order
            fields = "__all__"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if self.instance and self.instance.pk and self.instance.customer.is_guest and "status" in self.fields:
                self.fields["status"].disabled = True

    list_display = (
        "code",
        "customer",
        "customer_type",
        "status",
        "ship_city",
        "ship_region",
        "currency",
        "total",
        "receipt_link",
        "created_at",
    )
    list_filter = ("status", "customer__is_guest", "currency", "ship_region", "ship_city", "created_at")
    list_editable = ("status",)
    search_fields = (
        "code",
        "customer__email",
        "customer__full_name",
        "ship_full_name",
        "ship_phone",
        "ship_line1",
        "ship_city",
        "ship_region",
    )
    readonly_fields = (
        "code",
        "customer",
        "currency",
        "subtotal",
        "shipping",
        "payment_charge",
        "total",
        "receipt_preview",
        "receipt_link",
        "receipt_generated_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Order", {"fields": ("code", "customer", "status", "currency", "subtotal", "shipping", "payment_charge", "total")}),
        ("Shipping", {"fields": ("ship_full_name", "ship_phone", "ship_line1", "ship_line2", "ship_city", "ship_region", "ship_postal", "ship_country")}),
        ("Receipt", {"fields": ("receipt_preview", "receipt_link", "receipt_generated_at")}),
        ("Notes", {"fields": ("notes",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
    inlines = [OrderItemInline]
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_select_related = ("customer",)

    def get_changelist_form(self, request, **kwargs):
        return self.ChangelistForm

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and obj.customer.is_guest and "status" not in readonly:
            readonly.append("status")
        return readonly

    def save_model(self, request, obj, form, change):
        if change and obj.customer.is_guest:
            old_status = Order.objects.filter(pk=obj.pk).values_list("status", flat=True).first()
            if old_status:
                obj.status = old_status
        super().save_model(request, obj, form, change)

    @admin.display(description="Type")
    def customer_type(self, obj: Order):
        if obj.customer.is_guest:
            return format_html('<span style="font-weight:600;color:#92400e;">Guest</span>')
        return format_html('<span style="font-weight:600;color:#065f46;">Registered</span>')

    @admin.display(description="Receipt")
    def receipt_link(self, obj: Order):
        if not obj.receipt_image:
            return "—"
        try:
            url = reverse("order-receipt", args=[obj.code])
            download_url = reverse("order-receipt-download", args=[obj.code])
            return format_html(
                '<a class="button" href="{0}" target="_blank" rel="noopener">View PDF</a> '
                '<a class="button" href="{1}">Download</a>',
                url,
                download_url,
            )
        except Exception:
            return "—"

    @admin.display(description="Receipt preview")
    def receipt_preview(self, obj: Order):
        if not obj.receipt_image:
            return "—"
        try:
            url = reverse("order-receipt", args=[obj.code])
            download_url = reverse("order-receipt-download", args=[obj.code])
            return format_html(
                '<div style="display:grid;gap:10px;">'
                '<iframe src="{0}" style="width:100%;max-width:760px;height:520px;border:1px solid #e5e7eb;border-radius:6px;background:#fff;"></iframe>'
                '<div>'
                '<a class="button" href="{0}" target="_blank" rel="noopener">Open full receipt</a> '
                '<a class="button" href="{1}">Download PDF</a>'
                '</div>'
                '</div>',
                url,
                download_url,
            )
        except Exception:
            return "—"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "tx_ref",
        "order_link",
        "status_badge",
        "amount_fmt",
        "currency",
        "channel",
        "network",
        "provider",
        "created_at",
        "paid_at",
    )
    list_filter = ("provider", "status", "currency", "channel", "network", "created_at", "paid_at")
    search_fields = ("tx_ref", "order__code", "order__id", "order__customer__email", "order__customer__full_name")
    readonly_fields = (
        "order",
        "provider",
        "tx_ref",
        "psk_id",
        "channel",
        "network",
        "status",
        "amount",
        "currency",
        "raw_pretty",
        "paid_at",
        "completed_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("order",)}),
        ("Payment", {"fields": ("provider", "tx_ref", "status", "amount", "currency", "channel", "network", "psk_id")}),
        ("Timestamps", {"fields": ("created_at", "paid_at", "completed_at", "updated_at")}),
        ("Gateway Payload", {"fields": ("raw_pretty",)}),
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_select_related = ("order", "order__customer")

    @admin.display(description="Order")
    def order_link(self, obj: Payment):
        if not obj.order_id:
            return "—"
        url = reverse("admin:store_order_change", args=[obj.order_id])
        code = getattr(obj.order, "code", None) or f"#{obj.order_id}"
        cust = getattr(getattr(obj.order, "customer", None), "full_name", "") or ""
        label = f"{code} — {cust}" if cust else str(code)
        return format_html('<a href="{}">{}</a>', url, label)

    @admin.display(description="Status")
    def status_badge(self, obj: Payment):
        colors = {
            "pending": ("#6b7280", "#f3f4f6"),
            "successful": ("#065f46", "#d1fae5"),
            "failed": ("#991b1b", "#fee2e2"),
            "cancelled": ("#92400e", "#fef3c7"),
        }
        fg, bg = colors.get(obj.status, ("#111827", "#e5e7eb"))
        text = (obj.status or "").title()
        return format_html(
            '<span style="padding:.15rem .5rem;border-radius:.5rem;background:{};color:{};font-weight:600;">{}</span>',
            bg,
            fg,
            text,
        )

    @admin.display(description="Amount")
    def amount_fmt(self, obj: Payment):
        try:
            return f"GHS {obj.amount:,.2f}"
        except Exception:
            return "—"

    @admin.display(description="Raw payload")
    def raw_pretty(self, obj: Payment):
        try:
            pretty = json.dumps(obj.raw or {}, indent=2, ensure_ascii=False)
        except Exception:
            pretty = str(obj.raw)
        return mark_safe(f'<pre style="white-space:pre-wrap;word-wrap:break-word;">{pretty}</pre>')


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
