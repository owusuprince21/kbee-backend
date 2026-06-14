# store/views_checkout.py
from __future__ import annotations

import json
import uuid
import hmac
import hashlib
import logging
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import ValidationError, PermissionDenied

from .models import (
    Cart,
    Customer,
    Address,
    Product,
    Order,
    OrderItem,
    Payment,
    OrderStatus,
    PaymentStatus,
    CheckoutCharge,
    ShippingTown,
)
from .serializers import CartSerializer  # optional snapshot/debug
from .views import get_or_create_customer  # reuse the helper from views.py
from .receipts import build_order_receipt_pdf, generate_order_receipt, order_receipt_url, send_order_receipt_email

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Paystack config
# -------------------------------------------------------------------
PS_BASE = getattr(settings, "PAYSTACK_BASE_URL", "https://api.paystack.co")
PS_SECRET = getattr(settings, "PAYSTACK_SECRET_KEY", None)
# Optional: where Paystack redirects the user after Card checkout
PS_CALLBACK_URL = getattr(settings, "PAYSTACK_CALLBACK_URL", None)
# If you keep a separate webhook secret, define PAYSTACK_WEBHOOK_SECRET; otherwise, default to secret key
PS_WEBHOOK_SECRET = getattr(settings, "PAYSTACK_WEBHOOK_SECRET", None) or PS_SECRET

if not PS_SECRET:
    log.warning("PAYSTACK_SECRET_KEY not set in settings! Payment initialize/verify/webhook will fail.")


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _money(v) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0.00")


def _to_pesewas(amount: Decimal | int | str) -> int:
    """Paystack amounts are in the lowest currency unit (GHS -> pesewas)."""
    return int(_money(amount) * 100)


def _payment_charge(base: Decimal) -> tuple[Decimal, Decimal]:
    percent = CheckoutCharge.current_percentage()
    charge = (base * percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return percent, charge


def _resolve_shipping(request, customer: Customer, addr: Address) -> tuple[Decimal, ShippingTown | None]:
    town_id = request.data.get("shipping_town_id") or request.data.get("town_id")
    if town_id:
        town = ShippingTown.objects.filter(pk=town_id, active=True, region__active=True).select_related("region").first()
        if not town:
            raise ValidationError({"shipping_town_id": "Invalid shipping town."})
        if addr.city != town.name or addr.region != town.region.name:
            addr.city = town.name
            addr.region = town.region.name
            addr.save(update_fields=["city", "region", "updated_at"])
        return _money(town.fee), town
    return _money(request.data.get("shipping_fee") or 0), None


def _normalize_provider(net: str) -> str:
    """
    Map user-friendly names to Paystack GH providers.
    Paystack valid values (GH): 'mtn', 'tgo', 'vodafone'
    """
    if not net:
        return ""
    n = net.strip().upper().replace(" ", "").replace("-", "")
    if n in {"MTN"}:
        return "mtn"
    if n in {"AIRTELTIGO", "AIRTEL", "TIGO", "AIRTELTIGOGH", "AIRTEL_TIGO", "AIRTELTI-GO"}:
        return "tgo"
    if n in {"TELECEL", "VODAFONE", "VODA", "VODAFONEGH"}:
        return "vodafone"
    return n.lower()


def _model_network_from_provider(provider: str) -> str:
    """
    Convert Paystack provider -> your model's choices.
    Paystack: mtn | tgo | vodafone
    Model:    mtn | airteltigo | telecel
    """
    p = (provider or "").lower()
    if p == "tgo":
        return "airteltigo"
    if p == "vodafone":
        return "telecel"
    return "mtn" if p == "mtn" else p


def _ps_headers() -> dict:
    return {
        "Authorization": f"Bearer {PS_SECRET}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _paystack_error_response(data: dict, fallback: str = "Payment gateway rejected the request.") -> str:
    if not isinstance(data, dict):
        return fallback
    message = data.get("message") or data.get("detail")
    if message:
        return str(message)
    errors = data.get("errors")
    if errors:
        return str(errors)
    return fallback


def _pick_phone(customer: Customer, address: Address | None) -> str:
    """Prefer shipping address phone; else account.phone if present; else empty"""
    if address and address.phone:
        return address.phone
    acct = getattr(customer, "account", None)
    if acct and getattr(acct, "phone", None):
        return acct.phone
    return ""


def _payment_init(payment: Payment) -> dict:
    raw = payment.raw or {}
    init = raw.get("init") if isinstance(raw, dict) else {}
    return init if isinstance(init, dict) else {}


def _payment_cart_snapshot(payment: Payment) -> dict:
    raw = payment.raw or {}
    snapshot = raw.get("cart_snapshot") if isinstance(raw, dict) else {}
    return snapshot if isinstance(snapshot, dict) else {}


def _payment_customer_id(payment: Payment, metadata: dict | None = None):
    metadata = metadata or {}
    init = _payment_init(payment)
    snapshot = _payment_cart_snapshot(payment)
    return metadata.get("customer_id") or init.get("customer_id") or snapshot.get("customer")


def _stock_error(product: Product, requested: int) -> str:
    available = int(product.stock_quantity or 0)
    if available <= 0:
        return f"{product.name} is out of stock."
    return f"Only {available} unit(s) of {product.name} available. You requested {requested}."


def _validate_cart_stock(cart: Cart) -> None:
    errors: list[str] = []
    for item in cart.items.select_related("product"):
        product = item.product
        available = int(product.stock_quantity or 0)
        if not product.is_in_stock or available <= 0 or item.quantity > available:
            errors.append(_stock_error(product, item.quantity))
    if errors:
        raise ValidationError({"stock": errors})


def _validate_snapshot_stock(items: list[dict]) -> None:
    errors: list[str] = []
    for item in items:
        product = item["product"]
        quantity = int(item["quantity"] or 1)
        available = int(product.stock_quantity or 0)
        if not product.is_in_stock or available <= 0 or quantity > available:
            errors.append(_stock_error(product, quantity))
    if errors:
        raise ValidationError({"stock": errors})


def _deduct_order_stock(order: Order) -> None:
    locked_order = Order.objects.select_for_update().get(pk=order.pk)
    if locked_order.stock_deducted_at:
        return

    items = list(locked_order.items.select_related("product"))
    _validate_snapshot_stock(
        [
            {
                "product": item.product,
                "quantity": item.quantity,
            }
            for item in items
        ]
    )

    for item in items:
        product = Product.objects.select_for_update().get(pk=item.product_id)
        product.stock_quantity = max(0, int(product.stock_quantity or 0) - int(item.quantity or 0))
        product.is_in_stock = product.stock_quantity > 0
        product.save(update_fields=["stock_quantity", "is_in_stock", "updated_at"])

    locked_order.stock_deducted_at = timezone.now()
    locked_order.save(update_fields=["stock_deducted_at", "updated_at"])
    order.stock_deducted_at = locked_order.stock_deducted_at


# -------------------------------------------------------------------
# Build an Order snapshot from the current active cart
# -------------------------------------------------------------------
def _create_order_from_cart(
    customer: Customer,
    addr: Address,
    note: str,
    shipping_fee: Decimal,
    payment_charge: Decimal = Decimal("0.00"),
    currency: str = "GHS",
) -> Order:
    cart = (
        Cart.objects
        .filter(customer=customer, checked_out_at=None)
        .prefetch_related("items__product__gallery")
        .first()
    )
    if not cart or cart.items.count() == 0:
        raise ValidationError("Your cart is empty.")
    _validate_cart_stock(cart)

    subtotal = Decimal("0.00")
    for it in cart.items.select_related("product"):
        unit = _money(it.unit_price or it.product.discount_price or it.product.price)
        subtotal += (unit * it.quantity)

    total = subtotal + _money(shipping_fee) + _money(payment_charge)

    order = Order.objects.create(
        customer=customer,
        ship_full_name=addr.full_name or customer.full_name or customer.email or "",
        ship_line1=addr.line1,
        ship_line2=addr.line2 or "",
        ship_city=addr.city or "",
        ship_region=addr.region or "",
        ship_postal=addr.postal_code or "",
        ship_country=addr.country or "Ghana",
        ship_phone=addr.phone or "",
        status=OrderStatus.PENDING,
        currency=(currency or "GHS").upper(),
        subtotal=subtotal,
        shipping=_money(shipping_fee),
        payment_charge=_money(payment_charge),
        total=total,
        notes=note or "",
    )

    # Copy items snapshot
    for it in cart.items.select_related("product"):
        p = it.product
        unit = _money(it.unit_price or p.discount_price or p.price)
        img_url = ""
        try:
            if p.main_image:
                img_url = p.main_image.url
        except Exception:
            pass

        OrderItem.objects.create(
            order=order,
            product=p,
            product_name=p.name,
            product_slug=p.slug,
            image_url=img_url,
            quantity=it.quantity,
            unit_price=unit,
        )

    _deduct_order_stock(order)

    # Clear/close cart
    cart.items.all().delete()
    cart.checked_out_at = timezone.now()
    cart.save(update_fields=["checked_out_at", "updated_at"])

    return order


def _create_order_from_snapshot(
    customer: Customer,
    addr: Address,
    note: str,
    shipping_fee: Decimal,
    payment_charge: Decimal = Decimal("0.00"),
    currency: str = "GHS",
    snapshot: dict | None = None,
) -> Order:
    snapshot = snapshot or {}
    items = snapshot.get("items") if isinstance(snapshot, dict) else []
    if not isinstance(items, list) or not items:
        raise ValidationError("Your cart is empty.")

    subtotal = Decimal("0.00")
    parsed_items: list[dict] = []
    for item in items:
        product_data = item.get("product") or {}
        product_id = product_data.get("id") or item.get("product_id")
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            continue
        quantity = int(item.get("quantity") or 1)
        unit_price = _money(item.get("unit_price") or product.discount_price or product.price)
        subtotal += unit_price * quantity
        parsed_items.append(
            {
                "product": product,
                "product_name": product_data.get("name") or product.name,
                "product_slug": product_data.get("slug") or product.slug,
                "image_url": product_data.get("main_image_url") or "",
                "quantity": quantity,
                "unit_price": unit_price,
            }
        )

    if not parsed_items:
        raise ValidationError("Your cart is empty.")
    _validate_snapshot_stock(parsed_items)

    order = Order.objects.create(
        customer=customer,
        ship_full_name=addr.full_name or customer.full_name or customer.email or "",
        ship_line1=addr.line1,
        ship_line2=addr.line2 or "",
        ship_city=addr.city or "",
        ship_region=addr.region or "",
        ship_postal=addr.postal_code or "",
        ship_country=addr.country or "Ghana",
        ship_phone=addr.phone or "",
        status=OrderStatus.PENDING,
        currency=(currency or "GHS").upper(),
        subtotal=subtotal,
        shipping=_money(shipping_fee),
        payment_charge=_money(payment_charge),
        total=subtotal + _money(shipping_fee) + _money(payment_charge),
        notes=note or "",
    )

    for item in parsed_items:
        OrderItem.objects.create(order=order, **item)

    _deduct_order_stock(order)

    Cart.objects.filter(customer=customer, checked_out_at=None).update(checked_out_at=timezone.now())
    return order


def _create_order_from_payment(
    payment: Payment,
    customer: Customer,
    addr: Address,
    note: str,
    shipping_fee: Decimal,
    payment_charge: Decimal,
    currency: str,
) -> Order:
    try:
        return _create_order_from_cart(customer, addr, note, shipping_fee, payment_charge, currency)
    except ValidationError:
        return _create_order_from_snapshot(
            customer,
            addr,
            note,
            shipping_fee,
            payment_charge,
            currency,
            snapshot=_payment_cart_snapshot(payment),
        )


def _ensure_receipt(order: Order | None, request=None) -> str:
    if not order:
        return ""
    generate_order_receipt(order)
    return order_receipt_url(order, request=request)


def _email_receipt_after_commit(order: Order | None) -> None:
    if not order:
        return
    if not getattr(settings, "SEND_ORDER_RECEIPT_EMAIL", False):
        return
    order_id = order.id

    def _send():
        try:
            fresh_order = Order.objects.get(pk=order_id)
            send_order_receipt_email(fresh_order)
        except Exception:
            log.exception("Failed to queue receipt email for order %s", order_id)

    transaction.on_commit(_send)


# -------------------------------------------------------------------
# 0) (Optional legacy) CHECKOUT: create order immediately
# -------------------------------------------------------------------
class CheckoutView(APIView):
    """
    POST /api/checkout/
    Creates an Order immediately from the active cart.
    For MoMo/Card flows that should NOT create orders before payment,
    use the initialize-from-cart flows below.
    """
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        customer = get_or_create_customer(request)

        cart = Cart.objects.filter(customer=customer, checked_out_at=None).first()
        if not cart or cart.items.count() == 0:
            raise ValidationError("Your cart is empty.")

        address_id = request.data.get("address_id")
        if not address_id:
            raise ValidationError({"address_id": "This field is required."})

        try:
            addr = Address.objects.get(pk=address_id, customer=customer)
        except Address.DoesNotExist:
            raise ValidationError("Invalid address.")

        note = request.data.get("note", "") or ""
        shipping_fee, _town = _resolve_shipping(request, customer, addr)
        _percent, payment_charge = _payment_charge(cart.subtotal() + shipping_fee)
        currency = (request.data.get("currency") or "GHS").upper()

        order = _create_order_from_cart(customer, addr, note, shipping_fee, payment_charge, currency)
        receipt_url = _ensure_receipt(order, request=request)

        return Response(
            {
                "id": order.id,
                "code": order.code,
                "status": order.status,
                "currency": order.currency,
                "subtotal": str(order.subtotal),
                "shipping": str(order.shipping),
                "payment_charge": str(order.payment_charge),
                "total": str(order.total),
                "receipt_url": receipt_url,
                "created_at": order.created_at,
            },
            status=201,
        )


# -------------------------------------------------------------------
# 1) INITIALIZE PAYMENT (MoMo via /charge) — NO ORDER YET
# -------------------------------------------------------------------
def _initialize_hosted_checkout_from_cart(request, preferred_channel: str = "checkout") -> Response:
    if not PS_SECRET:
        raise ValidationError("Payment is not configured. Missing PAYSTACK_SECRET_KEY in settings.")

    customer = get_or_create_customer(request)

    address_id = request.data.get("address_id")
    if not address_id:
        raise ValidationError({"address_id": "This field is required."})
    try:
        addr = Address.objects.get(pk=address_id, customer=customer)
    except Address.DoesNotExist:
        raise ValidationError("Invalid address.")

    shipping_fee, shipping_town = _resolve_shipping(request, customer, addr)
    currency = (request.data.get("currency") or "GHS").upper()
    email = (request.data.get("email") or customer.email or f"user-{customer.id}@example.invalid").strip()

    cart = Cart.objects.filter(customer=customer, checked_out_at=None).first()
    if not cart or cart.items.count() == 0:
        raise ValidationError("Your cart is empty.")
    _validate_cart_stock(cart)

    subtotal = Decimal("0.00")
    for it in cart.items.select_related("product"):
        unit = _money(it.unit_price or it.product.discount_price or it.product.price)
        subtotal += (unit * it.quantity)
    charge_percent, payment_charge = _payment_charge(subtotal + shipping_fee)
    total = subtotal + shipping_fee + payment_charge
    if total <= 0:
        raise ValidationError("Invalid amount.")

    tx_ref = uuid.uuid4().hex
    channels = ["card", "mobile_money"]
    payment = Payment.objects.create(
        order=None,
        provider="paystack",
        tx_ref=tx_ref,
        status=PaymentStatus.PENDING,
        amount=total,
        currency=currency,
        network="",
        channel=preferred_channel,
        raw={
            "init": {
                "customer_id": customer.id,
                "address_id": address_id,
                "note": request.data.get("note") or "",
                "shipping_fee": str(shipping_fee),
                "shipping_town_id": getattr(shipping_town, "id", None),
                "payment_charge": str(payment_charge),
                "charge_percent": str(charge_percent),
                "currency": currency,
                "preferred_channel": preferred_channel,
                "channels": channels,
            },
            "cart_snapshot": CartSerializer(cart).data,
        },
    )

    payload = {
        "email": email,
        "amount": _to_pesewas(total),
        "currency": "GHS",
        "reference": tx_ref,
        "callback_url": PS_CALLBACK_URL or "",
        "channels": channels,
        "metadata": {
            "payment_id": payment.id,
            "customer_id": customer.id,
            "address_id": address_id,
            "shipping_fee": str(shipping_fee),
            "shipping_town_id": getattr(shipping_town, "id", None),
            "payment_charge": str(payment_charge),
            "charge_percent": str(charge_percent),
            "currency": currency,
            "channel": preferred_channel,
            "channels": channels,
        },
    }

    try:
        r = requests.post(f"{PS_BASE}/transaction/initialize", headers=_ps_headers(), json=payload, timeout=60)
        data = r.json() if r.content else {}
    except Exception as e:
        log.exception("Paystack hosted checkout init error")
        payment.mark_failed({"exception": str(e)})
        return Response({"detail": "Failed to connect to payment gateway."}, status=502)

    if not r.ok or (isinstance(data, dict) and data.get("status") is False):
        payment.mark_failed({"init_gateway": data})
        return Response({"detail": _paystack_error_response(data)}, status=400)

    try:
        payment.raw = {"init_gateway": data, **(payment.raw or {})}
        d = data.get("data") or {}
        access_code = d.get("access_code")
        if access_code:
            payment.psk_id = access_code
        payment.save(update_fields=["raw", "psk_id"])
    except Exception:
        pass

    auth_url = (data.get("data") or {}).get("authorization_url") or (data.get("data") or {}).get("authorizationURL")

    return Response(
        {
            "tx_ref": tx_ref,
            "payment_id": payment.id,
            "channel": preferred_channel,
            "channels": channels,
            "next_url": auth_url,
            "gateway": data,
        },
        status=200,
    )


class InitializeCheckoutFromCartView(APIView):
    """
    POST /api/payments/initialize_checkout_from_cart/

    Creates a Paystack hosted checkout transaction from the active cart.
    Checkout exposes both card and mobile money channels on Paystack.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        preferred_channel = (request.data.get("preferred_channel") or "checkout").strip() or "checkout"
        return _initialize_hosted_checkout_from_cart(request, preferred_channel=preferred_channel)


class InitializeMoMoFromCartView(APIView):
    """
    POST /api/payments/initialize_from_cart/
    Body:
      {
        "address_id": <int>,                # required
        "note": "optional",
        "shipping_fee": 50,                 # optional (defaults 50)
        "currency": "GHS",                  # optional (defaults GHS)
        "network": "mtn" | "airteltigo" | "telecel",
        "phone_number": "0... or +233..."
      }

    Returns:
      {
        "tx_ref": "...",
        "payment_id": 123,
        "channel": "mobile_money",
        "next_url": "<optional redirect page>",
        "gateway": { ... raw paystack response ... }
      }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        return _initialize_hosted_checkout_from_cart(request, preferred_channel="mobile_money")

        if not PS_SECRET:
            raise ValidationError("Payment is not configured. Missing PAYSTACK_SECRET_KEY in settings.")

        customer = get_or_create_customer(request)

        address_id = request.data.get("address_id")
        if not address_id:
            raise ValidationError({"address_id": "This field is required."})
        try:
            addr = Address.objects.get(pk=address_id, customer=customer)
        except Address.DoesNotExist:
            raise ValidationError("Invalid address.")

        # user input network -> paystack provider
        raw_network = (request.data.get("network") or "").strip()
        ps_provider = _normalize_provider(raw_network)
        if ps_provider not in {"mtn", "tgo", "vodafone"}:
            raise ValidationError({"network": "Use mtn, airteltigo (tgo) or telecel/vodafone."})
        model_network = _model_network_from_provider(ps_provider)

        phone_number = (request.data.get("phone_number") or "").strip()
        if not phone_number:
            phone_number = _pick_phone(customer, addr)
        if not phone_number:
            raise ValidationError({"phone_number": "Phone number required."})

        shipping_fee, shipping_town = _resolve_shipping(request, customer, addr)
        currency = (request.data.get("currency") or "GHS").upper()

        # compute total from active cart (do not mutate cart here)
        cart = Cart.objects.filter(customer=customer, checked_out_at=None).first()
        if not cart or cart.items.count() == 0:
            raise ValidationError("Your cart is empty.")
        _validate_cart_stock(cart)

        subtotal = Decimal("0.00")
        for it in cart.items.select_related("product"):
            unit = _money(it.unit_price or it.product.discount_price or it.product.price)
            subtotal += (unit * it.quantity)
        charge_percent, payment_charge = _payment_charge(subtotal + shipping_fee)
        total = subtotal + shipping_fee + payment_charge
        if total <= 0:
            raise ValidationError("Invalid amount.")

        # create a payment first (no order yet)
        tx_ref = uuid.uuid4().hex
        payment = Payment.objects.create(
            order=None,
            provider="paystack",
            tx_ref=tx_ref,
            status=PaymentStatus.PENDING,
            amount=total,
            currency=currency,
            network=model_network,             # store model-friendly network
            channel="mobile_money",
            raw={
                "init": {
                    "address_id": address_id,
                    "note": request.data.get("note") or "",
                    "shipping_fee": str(shipping_fee),
                    "shipping_town_id": getattr(shipping_town, "id", None),
                    "payment_charge": str(payment_charge),
                    "charge_percent": str(charge_percent),
                    "currency": currency,
                },
                "cart_snapshot": CartSerializer(cart).data,  # optional/debug
            },
        )

        payload = {
            "email": customer.email or f"user-{customer.id}@example.invalid",
            "amount": _to_pesewas(total),   # pesewas
            "currency": "GHS",
            "reference": tx_ref,
            "mobile_money": {
                "phone": phone_number,
                "provider": ps_provider,    # 'mtn' | 'airteltigo' | 'vodafone'
            },
            "metadata": {
                "payment_id": payment.id,
                "customer_id": customer.id,
                "address_id": address_id,
                "shipping_fee": str(shipping_fee),
                "shipping_town_id": getattr(shipping_town, "id", None),
                "payment_charge": str(payment_charge),
                "charge_percent": str(charge_percent),
                "currency": currency,
                "network": ps_provider,    
                "channel": "mobile_money",
            },
        }

        try:
            r = requests.post(f"{PS_BASE}/charge", headers=_ps_headers(), json=payload, timeout=60)
            data = r.json() if r.content else {}
        except Exception as e:
            log.exception("Paystack init error")
            payment.mark_failed({"exception": str(e)})
            return Response({"detail": "Failed to connect to payment gateway."}, status=502)

        if not r.ok or (isinstance(data, dict) and data.get("status") is False):
            payment.mark_failed({"init_gateway": data})
            return Response({"detail": _paystack_error_response(data)}, status=400)

        # Persist raw response and psk_id if present
        try:
            payment.raw = {"init_gateway": data, **(payment.raw or {})}
            psk_id = (data.get("data") or {}).get("id")
            if psk_id:
                payment.psk_id = psk_id
            payment.save(update_fields=["raw", "psk_id"])
        except Exception:
            pass

        # Some MoMo providers (e.g. Vodafone) return a page to open
        d = (data.get("data") or {}) if isinstance(data, dict) else {}
        redirect_url = (
            d.get("authorization_url")
            or d.get("authorizationURL")
            or d.get("redirecturl")
            or d.get("redirect_url")
            or d.get("url")
        )

        return Response(
            {
                "tx_ref": tx_ref,
                "payment_id": payment.id,
                "channel": "mobile_money",
                "next_url": redirect_url,   # page to open in new tab (if present)
                "gateway": data,
            },
            status=200,
        )


# -------------------------------------------------------------------
# 1b) INITIALIZE PAYMENT (CARD via /transaction/initialize) — NO ORDER YET
# -------------------------------------------------------------------
class InitializeCardFromCartView(APIView):
    """
    POST /api/payments/initialize_card_from_cart/
    Body:
      {
        "address_id": <int>,         # required
        "note": "optional",
        "shipping_fee": 50,          # optional (defaults 50)
        "currency": "GHS",           # optional (defaults GHS)
        "email": "buyer@example.com" # optional (defaults to user's email)
      }

    Returns { tx_ref, payment_id, channel, next_url, gateway } where next_url
    is the Paystack hosted checkout URL to redirect the customer to.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        return _initialize_hosted_checkout_from_cart(request, preferred_channel="card")

        if not PS_SECRET:
            raise ValidationError("Payment is not configured. Missing PAYSTACK_SECRET_KEY in settings.")

        customer = get_or_create_customer(request)

        address_id = request.data.get("address_id")
        if not address_id:
            raise ValidationError({"address_id": "This field is required."})
        try:
            addr = Address.objects.get(pk=address_id, customer=customer)
        except Address.DoesNotExist:
            raise ValidationError("Invalid address.")

        shipping_fee, shipping_town = _resolve_shipping(request, customer, addr)
        currency = (request.data.get("currency") or "GHS").upper()
        email = (request.data.get("email") or customer.email or f"user-{customer.id}@example.invalid").strip()

        cart = Cart.objects.filter(customer=customer, checked_out_at=None).first()
        if not cart or cart.items.count() == 0:
            raise ValidationError("Your cart is empty.")
        _validate_cart_stock(cart)

        subtotal = Decimal("0.00")
        for it in cart.items.select_related("product"):
            unit = _money(it.unit_price or it.product.discount_price or it.product.price)
            subtotal += (unit * it.quantity)
        charge_percent, payment_charge = _payment_charge(subtotal + shipping_fee)
        total = subtotal + shipping_fee + payment_charge
        if total <= 0:
            raise ValidationError("Invalid amount.")

        tx_ref = uuid.uuid4().hex
        payment = Payment.objects.create(
            order=None,
            provider="paystack",
            tx_ref=tx_ref,
            status=PaymentStatus.PENDING,
            amount=total,
            currency=currency,
            network="",                # not applicable for cards
            channel="card",
            raw={
                "init": {
                    "address_id": address_id,
                    "note": request.data.get("note") or "",
                    "shipping_fee": str(shipping_fee),
                    "shipping_town_id": getattr(shipping_town, "id", None),
                    "payment_charge": str(payment_charge),
                    "charge_percent": str(charge_percent),
                    "currency": currency,
                },
                "cart_snapshot": CartSerializer(cart).data,
            },
        )

        payload = {
            "email": email,
            "amount": _to_pesewas(total),
            "currency": "GHS",
            "reference": tx_ref,
            "callback_url": PS_CALLBACK_URL or "",
            "metadata": {
                "payment_id": payment.id,
                "customer_id": customer.id,
                "address_id": address_id,
                "shipping_fee": str(shipping_fee),
                "shipping_town_id": getattr(shipping_town, "id", None),
                "payment_charge": str(payment_charge),
                "charge_percent": str(charge_percent),
                "currency": currency,
                "channel": "card",
            },
        }

        try:
            r = requests.post(f"{PS_BASE}/transaction/initialize", headers=_ps_headers(), json=payload, timeout=60)
            data = r.json() if r.content else {}
        except Exception as e:
            log.exception("Paystack init error (card)")
            payment.mark_failed({"exception": str(e)})
            return Response({"detail": "Failed to connect to payment gateway."}, status=502)

        if not r.ok or (isinstance(data, dict) and data.get("status") is False):
            payment.mark_failed({"init_gateway": data})
            return Response({"detail": _paystack_error_response(data)}, status=400)

        # Save raw + access_code/authorization_url if present
        try:
            payment.raw = {"init_gateway": data, **(payment.raw or {})}
            d = data.get("data") or {}
            access_code = d.get("access_code")
            if access_code:
                payment.psk_id = access_code  # optional: store something we can reference
            payment.save(update_fields=["raw", "psk_id"])
        except Exception:
            pass

        auth_url = (data.get("data") or {}).get("authorization_url") or (data.get("data") or {}).get("authorizationURL")

        return Response(
            {
                "tx_ref": tx_ref,
                "payment_id": payment.id,
                "channel": "card",
                "next_url": auth_url,  
                "gateway": data,
            },
            status=200,
        )


# -------------------------------------------------------------------
# 2) VERIFY PAYMENT (client polling/callback)
# -------------------------------------------------------------------
class VerifyPaymentView(APIView):
    """
    GET /api/payments/verify/<tx_ref>/
    Verifies via Paystack: GET /transaction/verify/{reference}
    On success: creates Order from cart (if missing), links Payment, marks as paid.
    """
    permission_classes = [AllowAny]

    @transaction.atomic
    def get(self, request, tx_ref: str):
        if not PS_SECRET:
            raise ValidationError("Payment is not configured. Missing PAYSTACK_SECRET_KEY in settings.")

        customer = get_or_create_customer(request)

        # Find payment by our tx_ref (we used tx_ref as Paystack reference)
        payment = (
            Payment.objects.select_for_update()
            .filter(tx_ref=tx_ref, provider="paystack")
            .first()
        )
        if not payment:
            return Response({"detail": "Payment record not found."}, status=404)

        # Verify with Paystack
        try:
            r = requests.get(f"{PS_BASE}/transaction/verify/{tx_ref}", headers=_ps_headers(), timeout=45)
            data = r.json() if r.content else {}
        except Exception:
            return Response({"detail": "Gateway verification failed."}, status=502)

        # Save raw verification result
        payment.raw = {"verify": data, **(payment.raw or {})}

        ok = bool(data.get("status") is True)
        d = (data.get("data") or {})
        pay_status = (d.get("status") or "").lower()  # 'success' when paid
        currency = (d.get("currency") or "GHS").upper()
        # amount returned is in pesewas; convert to GHS (not strictly needed here)
        # amount = _money(Decimal(d.get("amount") or 0) / Decimal(100))

        if ok and pay_status == "success" and currency == "GHS":
            md = (d.get("metadata") or {})
            init = (payment.raw or {}).get("init", {})
            owner_customer_id = _payment_customer_id(payment, md)
            owner_customer = Customer.objects.filter(pk=owner_customer_id).first() if owner_customer_id else None
            if not owner_customer:
                owner_customer = payment.order.customer if payment.order else customer

            # Ownership check after we know the original payment owner. Guest callbacks can
            # arrive on a different localhost/127.0.0.1 origin, so request customer may differ.
            if payment.order and payment.order.customer_id != owner_customer.id:
                raise PermissionDenied("Not your order.")

            # Create order from cart if not already linked
            if not payment.order:
                address_id = md.get("address_id") or init.get("address_id")
                shipping_fee = _money(md.get("shipping_fee") or init.get("shipping_fee") or 0)
                payment_charge = _money(md.get("payment_charge") or init.get("payment_charge") or 0)
                note = init.get("note") or ""
                addr = Address.objects.filter(pk=address_id, customer=owner_customer).first()
                if not addr:
                    return Response({"detail": "Address missing for order creation."}, status=400)
                order = _create_order_from_payment(payment, owner_customer, addr, note, shipping_fee, payment_charge, currency)
                payment.order = order
                payment.save(update_fields=["order", "raw", "updated_at"])

            # Mark success (also store Paystack transaction id if present)
            psk_id = d.get("id")
            if psk_id:
                payment.psk_id = psk_id
            actual_channel = d.get("channel")
            if actual_channel:
                payment.channel = actual_channel
                payment.save(update_fields=["channel", "psk_id", "raw", "updated_at"])
            payment.mark_success({"verify": data})

            # Mark order paid
            if payment.order and payment.order.status != OrderStatus.PAID:
                payment.order.status = OrderStatus.PAID
                payment.order.save(update_fields=["status"])
            receipt_url = _ensure_receipt(payment.order, request=request)
            _email_receipt_after_commit(payment.order)

            return Response(
                {
                    "detail": "Payment verified",
                    "order_id": payment.order.id if payment.order else None,
                    "order_code": payment.order.code if payment.order else "",
                    "receipt_url": receipt_url,
                    "customer_is_guest": payment.order.customer.is_guest if payment.order else True,
                    "order_status": payment.order.status if payment.order else "",
                    "payment_status": payment.status,
                }
            )

        # Not successful yet or failed
        if pay_status in {"abandoned", "failed", "reversed", "cancelled"}:
            payment.mark_failed({"verify": data})
            if payment.order and payment.order.status == OrderStatus.PENDING:
                payment.order.status = OrderStatus.FAILED
                payment.order.save(update_fields=["status"])
            return Response(
                {"detail": "Payment not successful", "payment_status": payment.status},
                status=400,
            )

        # Still pending
        payment.status = PaymentStatus.PENDING
        payment.save(update_fields=["status", "raw"])
        return Response({"detail": "Payment pending", "payment_status": payment.status}, status=202)


# -------------------------------------------------------------------
# 3) PAYSTACK WEBHOOK
# -------------------------------------------------------------------
class PaystackWebhookView(APIView):
    """
    POST /api/payments/webhook/paystack/
    Verify signature with 'x-paystack-signature' header (HMAC-SHA512 of raw body using secret).
    On success: creates Order from cart (if missing), links Payment, marks as paid.
    """
    permission_classes = [AllowAny]  # signature validation is our auth

    @transaction.atomic
    def post(self, request):
        if not PS_WEBHOOK_SECRET:
            log.warning("PAYSTACK_WEBHOOK_SECRET (or PAYSTACK_SECRET_KEY) not set; refusing webhook.")
            return Response(status=401)

        signature = request.headers.get("x-paystack-signature") or request.headers.get("X-Paystack-Signature")
        raw_body = request.body or b""
        computed = hmac.new(
            bytes(PS_WEBHOOK_SECRET, "utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        if not signature or signature != computed:
            log.warning("Invalid Paystack webhook signature.")
            return Response(status=401)

        try:
            payload = request.data if isinstance(request.data, dict) else json.loads(raw_body.decode("utf-8"))
        except Exception:
            return Response(status=400)

        data = payload.get("data") or {}
        reference = data.get("reference")
        status_val = (data.get("status") or "").lower()  # 'success' on success
        currency = (data.get("currency") or "GHS").upper()
        amount = _money(Decimal(data.get("amount") or 0) / Decimal(100))
        md = data.get("metadata") or {}

        payment = (
            Payment.objects.select_for_update()
            .filter(tx_ref=reference, provider="paystack")
            .first()
        )
        if not payment:
            # No payment record? Create a minimal one so we still track it.
            payment = Payment.objects.create(
                order=None,
                provider="paystack",
                tx_ref=reference or uuid.uuid4().hex,
                status=PaymentStatus.PENDING,
                amount=amount,
                currency=currency,
                network=_model_network_from_provider(md.get("network") or ""),
                channel=(md.get("channel") or data.get("channel") or "card"),
                raw={"webhook": payload},
            )
        else:
            # Merge/append raw
            payment.raw = {"webhook": payload, **(payment.raw or {})}

        # Handle success
        if status_val == "success" and currency == "GHS":
            # Create order from cart if missing (use metadata customer/address)
            if not payment.order:
                init = _payment_init(payment)
                customer_id = _payment_customer_id(payment, md)
                address_id = md.get("address_id") or init.get("address_id")
                shipping_fee = _money(md.get("shipping_fee") or init.get("shipping_fee") or 0)
                payment_charge = _money(md.get("payment_charge") or init.get("payment_charge") or 0)
                note = init.get("note") or ""
                customer = Customer.objects.filter(pk=customer_id).first()
                if customer and address_id:
                    addr = Address.objects.filter(pk=address_id, customer=customer).first()
                    if addr:
                        order = _create_order_from_payment(payment, customer, addr, note, shipping_fee, payment_charge, currency)
                        payment.order = order
                        payment.save(update_fields=["order", "raw", "updated_at"])

            # Mark success
            try:
                psk_id = data.get("id")
                if psk_id:
                    payment.psk_id = psk_id
            except Exception:
                pass
            payment.mark_success({"webhook": payload})

            if payment.order:
                if payment.order.status != OrderStatus.PAID:
                    payment.order.status = OrderStatus.PAID
                    payment.order.save(update_fields=["status"])
                _ensure_receipt(payment.order)
                _email_receipt_after_commit(payment.order)

            return Response({"detail": "ok"}, status=200)

        # Failures
        if status_val in {"failed", "reversed", "cancelled"}:
            payment.mark_failed({"webhook": payload})
            if payment.order and payment.order.status == OrderStatus.PENDING:
                payment.order.status = OrderStatus.FAILED
                payment.order.save(update_fields=["status"])
            return Response({"detail": "ok"}, status=200)

        # Pending or other events: just store payload
        payment.save(update_fields=["raw"])
        return Response({"detail": "ok"}, status=200)


class OrderReceiptView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, code: str, download: bool = False):
        order = Order.objects.filter(code=code).select_related("customer").first()
        if not order:
            return Response({"detail": "Receipt not found."}, status=404)
        pdf = build_order_receipt_pdf(order)
        disposition = "attachment" if download else "inline"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'{disposition}; filename="kbee-receipt-{order.code}.pdf"'
        return response
