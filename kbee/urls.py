from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView  # optional but recommended

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("store.urls")),  # <-- app routes
    # OpenAPI / Swagger (optional)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
