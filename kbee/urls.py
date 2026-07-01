from django.contrib import admin
from django.contrib.auth import logout
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import path, include
from django_otp.admin import OTPAdminSite
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView  # optional but recommended
from .admin_auth import admin_login, index_page

admin.site.__class__ = OTPAdminSite


def admin_logout_compat(request):
    logout(request)
    return redirect("admin:login")


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", index_page, name="index"),
    path("admin/login/", admin_login, name="admin-login"),
    path("admin/logout/", admin_logout_compat, name="admin-logout-compat"),
    path("admin/", admin.site.urls),
    path("api/health/", health_check, name="health-check"),
    path("", include("store.urls")),  # <-- app routes
]

if settings.ENABLE_API_DOCS:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
        path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="schema-swagger-ui"),
    ]
