from __future__ import annotations

import logging
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import Order

log = logging.getLogger(__name__)


def _money(value, currency: str = "GHS") -> str:
    try:
        amount = Decimal(str(value or "0.00"))
    except Exception:
        amount = Decimal("0.00")
    return f"{currency} {amount:,.2f}"


def _local_dt(value) -> str:
    if not value:
        return ""
    return timezone.localtime(value).strftime("%d %b %Y, %I:%M %p")


def _receipt_order(order: Order) -> Order:
    return (
        Order.objects
        .select_related("customer")
        .prefetch_related("items", "payments")
        .get(pk=order.pk)
    )


def build_order_receipt_pdf(order: Order) -> bytes:
    order = _receipt_order(order)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Kbee receipt {order.code}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Brand", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=colors.HexColor("#111827")))
    styles.add(ParagraphStyle(name="Muted", fontName="Helvetica", fontSize=9, leading=13, textColor=colors.HexColor("#6b7280")))
    styles.add(ParagraphStyle(name="Small", fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#111827")))
    styles.add(ParagraphStyle(name="SmallWhite", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white))
    styles.add(ParagraphStyle(name="Section", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#111827")))

    currency = order.currency or "GHS"
    paid = order.payments.filter(status="successful").order_by("-paid_at", "-created_at").first()
    paid_at = paid.paid_at if paid and paid.paid_at else order.updated_at
    customer_name = order.ship_full_name or order.customer.full_name or order.customer.email or "Customer"
    customer_email = order.customer.email or "Guest customer"

    story = [
        Table(
            [
                [
                    Paragraph("Kbee Computers", styles["Brand"]),
                    Paragraph(f"<b>Receipt</b><br/>{order.code}<br/>{_local_dt(paid_at)}", styles["Small"]),
                ]
            ],
            colWidths=[105 * mm, 58 * mm],
        ),
        Spacer(1, 9 * mm),
    ]

    story[-2].setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#e5e7eb")),
    ]))

    ship_lines = [
        order.ship_line1,
        order.ship_line2,
        ", ".join(part for part in [order.ship_city, order.ship_region, order.ship_postal] if part),
        order.ship_country,
        order.ship_phone,
    ]
    story.append(Table(
        [
            [Paragraph("Customer", styles["Section"]), Paragraph("Ship To", styles["Section"])],
            [
                Paragraph("<br/>".join(filter(None, [customer_name, customer_email, order.ship_phone])), styles["Small"]),
                Paragraph("<br/>".join(line for line in ship_lines if line), styles["Small"]),
            ],
        ],
        colWidths=[81 * mm, 82 * mm],
    ))
    story[-1].setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f9fafb")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e5e7eb")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(Spacer(1, 8 * mm))

    item_rows = [[
        Paragraph("Item", styles["SmallWhite"]),
        Paragraph("Qty", styles["SmallWhite"]),
        Paragraph("Price", styles["SmallWhite"]),
        Paragraph("Total", styles["SmallWhite"]),
    ]]
    for item in order.items.all():
        item_rows.append([
            Paragraph(item.product_name or "Item", styles["Small"]),
            str(item.quantity),
            _money(item.unit_price, currency),
            _money(item.line_total(), currency),
        ])

    story.append(Table(item_rows, colWidths=[80 * mm, 18 * mm, 32 * mm, 33 * mm], repeatRows=1))
    story[-1].setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(Spacer(1, 8 * mm))

    totals = [
        ("Subtotal", order.subtotal),
        ("Shipping", order.shipping),
        ("Charge", order.payment_charge),
        ("Total Paid", order.total),
    ]
    story.append(Table(
        [[label, _money(amount, currency)] for label, amount in totals],
        colWidths=[125 * mm, 38 * mm],
        hAlign="RIGHT",
    ))
    story[-1].setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#111827")),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("Thank you for shopping with Kbee Computers. Keep this receipt and order code for support or pickup verification.", styles["Muted"]))

    doc.build(story)
    return buffer.getvalue()


def generate_order_receipt(order: Order, *, force: bool = False) -> str:
    if order.receipt_image and not force:
        try:
            return order.receipt_image.url
        except Exception:
            return ""

    order = _receipt_order(order)
    pdf_bytes = build_order_receipt_pdf(order)
    filename = f"receipts/{order.code}.pdf"

    try:
        order.receipt_image.save(filename, ContentFile(pdf_bytes), save=False)
        order.receipt_generated_at = timezone.now()
        order.save(update_fields=["receipt_image", "receipt_generated_at", "updated_at"])
        return order.receipt_image.url
    except Exception:
        log.exception("Failed to generate PDF receipt for order %s", order.pk)
        return ""


def order_receipt_url(order: Order, request=None, *, download: bool = False) -> str:
    route = "order-receipt-download" if download else "order-receipt"
    path = reverse(route, args=[order.code])
    if request is not None:
        return request.build_absolute_uri(path)
    base_url = getattr(settings, "SITE_BASE_URL", "").rstrip("/")
    return f"{base_url}{path}" if base_url else path


def send_order_receipt_email(order: Order, *, force: bool = False) -> bool:
    order = _receipt_order(order)
    if order.receipt_emailed_at and not force:
        return False
    if not order.customer.email:
        return False

    generate_order_receipt(order)
    receipt_url = order_receipt_url(order)
    pdf_bytes = build_order_receipt_pdf(order)
    context = {
        "order": order,
        "customer_name": order.ship_full_name or order.customer.full_name or "Customer",
        "receipt_url": receipt_url,
        "frontend_base_url": getattr(settings, "FRONTEND_BASE_URL", ""),
    }
    html_body = render_to_string("store/emails/order_receipt.html", context)
    text_body = render_to_string("store/emails/order_receipt.txt", context) or strip_tags(html_body)
    subject = f"Your Kbee Computers receipt for order {order.code}"

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[order.customer.email],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.attach(f"kbee-receipt-{order.code}.pdf", pdf_bytes, "application/pdf")

    try:
        msg.send(fail_silently=False)
    except Exception:
        log.exception("Failed to email receipt for order %s", order.pk)
        return False

    Order.objects.filter(pk=order.pk, receipt_emailed_at__isnull=True).update(receipt_emailed_at=timezone.now())
    return True
