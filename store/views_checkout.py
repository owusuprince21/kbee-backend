# store/views_checkout.py
from __future__ import annotations

import json
import uuid
import hmac
import hashlib
import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import ValidationError, PermissionDenied

from .models import (
    Cart,
    Customer,
    Address,
    Order,
    OrderItem,
    Payment,
    OrderStatus,
    PaymentStatus,
)
from .serializers import CartSerializer  # optional snapshot/debug
from .views import get_or_create_customer  # reuse the helper from views.py

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


def _pick_phone(customer: Customer, address: Address | None) -> str:
    """Prefer shipping address phone; else account.phone if present; else empty"""
    if address and address.phone:
        return address.phone
    acct = getattr(customer, "account", None)
    if acct and getattr(acct, "phone", None):
        return acct.phone
    return ""


# -------------------------------------------------------------------
# Build an Order snapshot from the current active cart
# -------------------------------------------------------------------
def _create_order_from_cart(
    customer: Customer,
    addr: Address,
    note: str,
    shipping_fee: Decimal,
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

    subtotal = Decimal("0.00")
    for it in cart.items.select_related("product"):
        unit = _money(it.unit_price or it.product.discount_price or it.product.price)
        subtotal += (unit * it.quantity)

    total = subtotal + _money(shipping_fee)

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

    # Clear/close cart
    cart.items.all().delete()
    cart.checked_out_at = timezone.now()
    cart.save(update_fields=["checked_out_at", "updated_at"])

    return order


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
        shipping_fee = _money(request.data.get("shipping_fee") or 0)
        currency = (request.data.get("currency") or "GHS").upper()

        order = _create_order_from_cart(customer, addr, note, shipping_fee, currency)

        return Response(
            {
                "id": order.id,
                "code": order.code,
                "status": order.status,
                "currency": order.currency,
                "subtotal": str(order.subtotal),
                "shipping": str(order.shipping),
                "total": str(order.total),
                "created_at": order.created_at,
            },
            status=201,
        )


# -------------------------------------------------------------------
# 1) INITIALIZE PAYMENT (MoMo via /charge) — NO ORDER YET
# -------------------------------------------------------------------
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

        shipping_fee = _money(request.data.get("shipping_fee") or 50)
        currency = (request.data.get("currency") or "GHS").upper()

        # compute total from active cart (do not mutate cart here)
        cart = Cart.objects.filter(customer=customer, checked_out_at=None).first()
        if not cart or cart.items.count() == 0:
            raise ValidationError("Your cart is empty.")

        subtotal = Decimal("0.00")
        for it in cart.items.select_related("product"):
            unit = _money(it.unit_price or it.product.discount_price or it.product.price)
            subtotal += (unit * it.quantity)
        total = subtotal + shipping_fee
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

        shipping_fee = _money(request.data.get("shipping_fee") or 50)
        currency = (request.data.get("currency") or "GHS").upper()
        email = (request.data.get("email") or customer.email or f"user-{customer.id}@example.invalid").strip()

        cart = Cart.objects.filter(customer=customer, checked_out_at=None).first()
        if not cart or cart.items.count() == 0:
            raise ValidationError("Your cart is empty.")

        subtotal = Decimal("0.00")
        for it in cart.items.select_related("product"):
            unit = _money(it.unit_price or it.product.discount_price or it.product.price)
            subtotal += (unit * it.quantity)
        total = subtotal + shipping_fee
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

        # Ownership check if order already exists
        if payment.order and payment.order.customer_id != customer.id:
            raise PermissionDenied("Not your order.")

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
            # Create order from cart if not already linked
            if not payment.order:
                md = (d.get("metadata") or {})
                init = (payment.raw or {}).get("init", {})
                address_id = md.get("address_id") or init.get("address_id")
                shipping_fee = _money(md.get("shipping_fee") or init.get("shipping_fee") or 50)
                note = init.get("note") or ""
                addr = Address.objects.filter(pk=address_id, customer=customer).first()
                if not addr:
                    return Response({"detail": "Address missing for order creation."}, status=400)
                order = _create_order_from_cart(customer, addr, note, shipping_fee, currency)
                payment.order = order

            # Mark success (also store Paystack transaction id if present)
            psk_id = d.get("id")
            if psk_id:
                payment.psk_id = psk_id
            payment.mark_success({"verify": data})

            # Mark order paid
            if payment.order and payment.order.status != OrderStatus.PAID:
                payment.order.status = OrderStatus.PAID
                payment.order.save(update_fields=["status"])

            return Response(
                {"detail": "Payment verified", "order_status": payment.order.status, "payment_status": payment.status}
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
                customer_id = md.get("customer_id")
                address_id = md.get("address_id")
                shipping_fee = _money(md.get("shipping_fee") or 50)
                note = ""
                customer = Customer.objects.filter(pk=customer_id).first()
                if customer and address_id:
                    addr = Address.objects.filter(pk=address_id, customer=customer).first()
                    if addr:
                        order = _create_order_from_cart(customer, addr, note, shipping_fee, currency)
                        payment.order = order

            # Mark success
            try:
                psk_id = data.get("id")
                if psk_id:
                    payment.psk_id = psk_id
            except Exception:
                pass
            payment.mark_success({"webhook": payload})

            if payment.order and payment.order.status != OrderStatus.PAID:
                payment.order.status = OrderStatus.PAID
                payment.order.save(update_fields=["status"])

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
