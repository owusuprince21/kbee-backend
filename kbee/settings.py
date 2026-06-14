# kbee/settings.py
import os
from pathlib import Path
from datetime import timedelta

import certifi
from decouple import config
from django.core.exceptions import ImproperlyConfigured
from corsheaders.defaults import default_headers, default_methods

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

# -----------------------------------------------------------------------------
# Core
# -----------------------------------------------------------------------------
SECRET_KEY = config("SECRET_KEY", default="django-insecure-change-this-in-production")
DEBUG = config("DJANGO_DEBUG", default=config("DEBUG", default=True), cast=env_bool)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1",
    cast=lambda v: [h.strip() for h in v.split(",")],
)

# -----------------------------------------------------------------------------
# Cloudinary
# -----------------------------------------------------------------------------
# Expect CLOUDINARY_URL in .env like: cloudinary://<api_key>:<api_secret>@<cloud_name>
CLOUDINARY_URL = config("CLOUDINARY_URL", default="")
if not CLOUDINARY_URL and not DEBUG:
    # Only enforce in non-debug environments
    raise ImproperlyConfigured("CLOUDINARY_URL is missing in .env for production.")
if CLOUDINARY_URL:
    os.environ["CLOUDINARY_URL"] = CLOUDINARY_URL

# -----------------------------------------------------------------------------
# Applications
# -----------------------------------------------------------------------------
INSTALLED_APPS = [
    # Admin UI
    "jazzmin",

    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "corsheaders",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "cloudinary",
    "cloudinary_storage",

    # Local
    "store.apps.StoreConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # keep high, before CommonMiddleware
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "kbee.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "kbee.wsgi.application"

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# -----------------------------------------------------------------------------
# Static & Media
# -----------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {  # media
        "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
    },
    "staticfiles": {  # static
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -----------------------------------------------------------------------------
# CORS / CSRF
# -----------------------------------------------------------------------------
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://127.0.0.1:3000",
    cast=lambda v: [s.strip() for s in v.split(",")],
)
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:3000,http://127.0.0.1:3000",
    cast=lambda v: [s.strip() for s in v.split(",")],
)

CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-firebase-uid",
    "x-user-email",
    "x-user-name",
    "x-user-photo",
    "x-guest-id",
]
CORS_ALLOW_METHODS = list(default_methods)
CORS_PREFLIGHT_MAX_AGE = 86400

# -----------------------------------------------------------------------------
# DRF / Filters / Schema
# -----------------------------------------------------------------------------
REST_FRAMEWORK = {
    # ✅ For the current “catalog + banners” APIs, AllowAny is fine.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,

    # ❌ Auth classes (Customer/Cart/Orders flow) — keep for later, but disabled now
    # If you keep these enabled while Customer is commented in models.py,
    # you can still run into confusion/unused config.
    # "DEFAULT_AUTHENTICATION_CLASSES": [
    #     "rest_framework_simplejwt.authentication.JWTAuthentication",
    #     "kbee.auth.firebase.FirebaseHeaderAuthentication",
    # ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Kbee Computers API",
    "VERSION": "1.0.0",
}

# -----------------------------------------------------------------------------
# JWT (Optional / Future)
# -----------------------------------------------------------------------------
# SIMPLE_JWT = {
#     "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
#     "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
# }

# -----------------------------------------------------------------------------
# Payments (Optional / Future)
# -----------------------------------------------------------------------------
PAYMENT_PROVIDER = "paystack"
PAYSTACK_SECRET_KEY = config("PAYSTACK_SECRET_KEY", default="")
PAYSTACK_PUBLIC_KEY = config("PAYSTACK_PUBLIC_KEY", default="")
PAYSTACK_WEBHOOK_SECRET = config("PAYSTACK_WEBHOOK_SECRET", default="", cast=str)
PAYSTACK_CURRENCY = config("PAYSTACK_CURRENCY", default="GHS")
PAYSTACK_ALLOWED_NETWORKS = config(
    "PAYSTACK_ALLOWED_NETWORKS",
    default="mtn,airteltigo,telecel",
    cast=lambda v: [s.strip().lower() for s in v.split(",") if s.strip()],
)
SITE_BASE_URL = config("SITE_BASE_URL", default="http://127.0.0.1:8000")
FRONTEND_BASE_URL = config("FRONTEND_BASE_URL", default="http://localhost:3000")
PAYSTACK_CALLBACK_URL = config("PAYSTACK_CALLBACK_URL", default=f"{FRONTEND_BASE_URL}/checkout/success")

# -----------------------------------------------------------------------------
# Email
# -----------------------------------------------------------------------------
EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default=(
        "django.core.mail.backends.smtp.EmailBackend"
        if config("EMAIL_HOST", default="")
        else "django.core.mail.backends.console.EmailBackend"
    ),
)
EMAIL_CA_BUNDLE = config("EMAIL_CA_BUNDLE", default=certifi.where())
os.environ.setdefault("SSL_CERT_FILE", EMAIL_CA_BUNDLE)
os.environ.setdefault("REQUESTS_CA_BUNDLE", EMAIL_CA_BUNDLE)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=env_bool)
EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=env_bool)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Kbee Computers <no-reply@kbee.local>")
SEND_ORDER_RECEIPT_EMAIL = config("SEND_ORDER_RECEIPT_EMAIL", default=False, cast=env_bool)

# -----------------------------------------------------------------------------
# JAZZMIN SETTINGS
# -----------------------------------------------------------------------------
JAZZMIN_SETTINGS = {
    "site_title": "Kbee Admin",
    "site_header": "Kbee Computers",
    "site_brand": "Kbee Admin",
    "site_logo": None,
    "login_logo": None,
    "login_logo_dark": None,
    "welcome_sign": "Welcome to Kbee Computers Admin",
    "copyright": "Kbee Computers",

    # Include models that are active in store/admin.py.
    "search_model": [
        "auth.User",
        "auth.Group",
        "store.Product",
        "store.Category",
        "store.HeroItem",
        "store.CountdownDeal",
        "store.HotItem",
        "store.ShippingRegion",
        "store.ShippingTown",
        "store.Customer",
        "store.Order",
        "store.Payment",
    ],

    "user_avatar": None,

    "usermenu_links": [
        {"model": "auth.user"},
        {"name": "API Docs", "url": "/api/schema/swagger-ui/", "new_window": True},
    ],

    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "hide_models": [],

    # Keep ordering aligned with the models registered in admin.py.
    "order_with_respect_to": [
        "store", "auth",
        "store.product",
        "store.category",
        "store.productgalleryimage",
        "store.heroitem",
        "store.countdowndeal",
        "store.hotitem",
        "store.shippingregion",
        "store.shippingtown",
        "store.checkoutcharge",
        "store.customer",
        "store.address",
        "store.accountdetail",
        "store.cart",
        "store.cartitem",
        "store.wishlistitem",
        "store.review",
        "store.order",
        "store.payment",
    ],

    "custom_links": {
        "store": [
            {
                "name": "Open Frontend",
                "url": "http://localhost:3000",
                "icon": "fas fa-external-link-alt",
                "new_window": True,
            }
        ]
    },

    # Icons (Font Awesome 5 free)
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.group": "fas fa-users",

        "store": "fas fa-store",
        "store.category": "fas fa-tags",
        "store.product": "fas fa-box-open",
        "store.productgalleryimage": "fas fa-images",
        "store.heroitem": "fas fa-bullhorn",
        "store.countdowndeal": "fas fa-hourglass-half",
        "store.hotitem": "fas fa-fire",
        "store.shippingregion": "fas fa-map-marked-alt",
        "store.shippingtown": "fas fa-map-marker-alt",
        "store.checkoutcharge": "fas fa-percentage",
        "store.customer": "fas fa-user-check",
        "store.address": "fas fa-address-book",
        "store.accountdetail": "fas fa-id-card",
        "store.cart": "fas fa-shopping-cart",
        "store.cartitem": "fas fa-shopping-basket",
        "store.wishlistitem": "fas fa-heart",
        "store.review": "fas fa-star",
        "store.order": "fas fa-file-invoice",
        "store.orderitem": "fas fa-list-ol",
        "store.payment": "fas fa-money-check-alt",
    },

    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",

    "related_modal_active": True,
    "use_google_fonts_cdn": True,
    "show_ui_builder": False,

    "changeform_format": "horizontal_tabs",
    "changeform_format_overrides": {
        # "store.order": "vertical_tabs",  # future
        "auth.user": "collapsible",
    },

    "language_chooser": False,
}

JAZZMIN_UI_TWEAKS = {
    "theme": "simplex",
    "navbar": "navbar-dark",
    "sidebar": "sidebar-dark-primary",
    "sidebar_fixed": True,
    "footer_fixed": False,
    "theme_appearance": "auto",
    "brand_colour": "navbar-primary",
}
