from django.contrib import admin
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView  # optional but recommended


def admin_logout_compat(request):
    logout(request)
    return redirect("admin:login")


urlpatterns = [
    path("admin/logout/", admin_logout_compat, name="admin-logout-compat"),
    path("admin/", admin.site.urls),
    path("", include("store.urls")),  # <-- app routes
    # OpenAPI / Swagger (optional)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
