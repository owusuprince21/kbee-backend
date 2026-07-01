from __future__ import annotations

import base64
from io import BytesIO

import qrcode
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice


MFA_SESSION_USER_KEY = "admin_mfa_user_id"
MFA_SESSION_NEXT_KEY = "admin_mfa_next"
DEVICE_NAME = "Microsoft Authenticator"


def _safe_next(request: HttpRequest) -> str:
    value = request.POST.get("next") or request.GET.get("next") or reverse("admin:index")
    if url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return value
    return reverse("admin:index")


def _otp_digits(request: HttpRequest) -> str:
    token = request.POST.get("otp_token", "")
    if token:
        return "".join(ch for ch in token if ch.isdigit())[:6]
    return "".join((request.POST.get(f"otp_{i}", "") or "")[:1] for i in range(1, 7))


def _qr_data_uri(config_url: str) -> str:
    image = qrcode.make(config_url)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _pending_user(request: HttpRequest):
    user_id = request.session.get(MFA_SESSION_USER_KEY)
    if not user_id:
        return None
    User = get_user_model()
    return User.objects.filter(pk=user_id, is_active=True, is_staff=True).first()


def _confirmed_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).order_by("id").first()


def _setup_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=False, name=DEVICE_NAME).order_by("-id").first() or TOTPDevice.objects.create(
        user=user,
        name=DEVICE_NAME,
        confirmed=False,
    )


def _render_mfa(request: HttpRequest, user, *, setup: bool, error: str = "") -> HttpResponse:
    device = _setup_device(user) if setup else _confirmed_device(user)
    if device is None:
        return _render_mfa(request, user, setup=True, error=error)

    return render(
        request,
        "admin/mfa_login.html",
        {
            "title": "Kbee Admin MFA",
            "site_header": "Kbee Computers",
            "site_title": "Kbee Admin",
            "username": user.get_username(),
            "setup": setup,
            "qr_data_uri": _qr_data_uri(device.config_url) if setup else "",
            "manual_setup_key": device.config_url if setup else "",
            "next": request.session.get(MFA_SESSION_NEXT_KEY) or reverse("admin:index"),
            "error": error,
        },
    )


def _complete_login(request: HttpRequest, user, device) -> HttpResponse:
    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    otp_login(request, device)
    request.session.pop(MFA_SESSION_USER_KEY, None)
    next_url = request.session.pop(MFA_SESSION_NEXT_KEY, None) or reverse("admin:index")
    return redirect(next_url)


@never_cache
@csrf_protect
def admin_login(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated and request.user.is_staff and request.user.is_verified():
        return redirect(_safe_next(request))

    pending_user = _pending_user(request)
    if pending_user and request.method == "POST" and request.POST.get("stage") == "otp":
        setup = not bool(_confirmed_device(pending_user))
        device = _setup_device(pending_user) if setup else _confirmed_device(pending_user)
        token = _otp_digits(request)
        if len(token) != 6 or not device or not device.verify_token(token):
            return _render_mfa(request, pending_user, setup=setup, error="Enter the valid 6-digit code from your authenticator app.")
        if setup and not device.confirmed:
            device.confirmed = True
            device.save(update_fields=["confirmed"])
        return _complete_login(request, pending_user, device)

    if pending_user and request.method == "GET":
        return _render_mfa(request, pending_user, setup=not bool(_confirmed_device(pending_user)))

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is None or not user.is_active or not user.is_staff:
            messages.error(request, "Please enter the correct admin username and password.")
            return render(request, "admin/password_login.html", {"next": _safe_next(request)})

        request.session[MFA_SESSION_USER_KEY] = user.pk
        request.session[MFA_SESSION_NEXT_KEY] = _safe_next(request)
        return _render_mfa(request, user, setup=not bool(_confirmed_device(user)))

    logout(request)
    return render(request, "admin/password_login.html", {"next": _safe_next(request)})


def index_page(request: HttpRequest) -> HttpResponse:
    return render(request, "index.html")
