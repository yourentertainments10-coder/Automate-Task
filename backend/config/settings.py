"""CarTrends CRM - Django settings.

Fully independent project. All external services (WhatsApp Cloud API, Gmail
API, the AI provider, Neon Postgres) are configured ONLY via environment
variables and stay inert until credentials are provided. Nothing is shared
with any other project.
"""
import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# The test suite must never reach a real integration. .env holds working
# WhatsApp/Gmail/AI credentials, and without this the suite would send live
# messages, spend AI quota, and fail whenever a model worded something
# differently. Individual tests that DO want the enabled path still switch it
# on themselves with mock.patch.dict.
TESTING = "test" in sys.argv
if TESTING:
    for flag in ("AI_ENABLED", "WHATSAPP_ENABLED", "GMAIL_ENABLED"):
        os.environ[flag] = "false"
    os.environ["WHATSAPP_APP_SECRET"] = ""      # webhook tests post unsigned

def env(name, default=""):
    """Env lookup where a BLANK value in .env means 'unset' -- the
    .env.example ships with empty placeholders on purpose."""
    return os.environ.get(name, "").strip() or default


SECRET_KEY = env("SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env("DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [h for h in env("ALLOWED_HOSTS", "automatetask.onrender.com").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "accounts",
    "crm",
    "notifications",
    "intake",
    "workspace",
    "webforms",
    "hr",
    "directory",
    "payroll",
    "mistakes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # static + SPA on Render
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


def _database_from_env():
    """SQLite locally; any postgres:// DATABASE_URL (e.g. the new Neon DB,
    to be provided later) switches to Postgres without code changes."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith(("postgres://", "postgresql://")):
        parsed = urlparse(url)
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username,
            "PASSWORD": parsed.password,
            "HOST": parsed.hostname,
            "PORT": parsed.port or 5432,
            "OPTIONS": {"sslmode": os.environ.get("DB_SSLMODE", "require")},
            "CONN_MAX_AGE": 60,
        }
    return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}


DATABASES = {"default": _database_from_env()}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "config.pagination.DefaultPagination",
    "PAGE_SIZE": 25,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

CORS_ALLOWED_ORIGINS = [
    o for o in env(
        "CORS_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174"
    ).split(",") if o
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"          # collectstatic target (admin css)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Uploads: S3 when a bucket is configured, the local disk otherwise.
#
# This matters more than it looks. A container's own disk is WIPED on every
# deploy and restart, so task attachments, leave documents and form uploads
# were disappearing while their database rows stayed behind. S3 keeps them.
# Set AWS_STORAGE_BUCKET_NAME (plus keys and region) to switch it on; leave
# it blank and everything behaves exactly as before.
# ---------------------------------------------------------------------------
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
USE_S3 = bool(AWS_STORAGE_BUCKET_NAME) and not TESTING

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

if USE_S3:
    AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
    AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", "ap-south-1")   # Mumbai
    AWS_S3_FILE_OVERWRITE = False        # two invoice.pdf uploads stay separate
    AWS_DEFAULT_ACL = None               # bucket owner keeps control
    AWS_QUERYSTRING_AUTH = True          # links are signed and expire
    AWS_QUERYSTRING_EXPIRE = int(env("AWS_LINK_EXPIRY_SECONDS", "3600"))
    AWS_S3_CUSTOM_DOMAIN = env("AWS_S3_CUSTOM_DOMAIN") or None     # optional CDN
    STORAGES["default"] = {"BACKEND": "storages.backends.s3.S3Storage"}

# Single-service deploy: WhiteNoise serves the built React app (frontend/dist)
# at the URL root — /assets/*, sw.js, manifest, face models and / itself.
# Locally dist may not exist; dev uses the Vite server instead.
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None
WHITENOISE_INDEX_FILE = True                    # "/" -> index.html

# --- production hardening (all inert while DEBUG=true locally) -------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # behind Render's proxy
CSRF_TRUSTED_ORIGINS = [o for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# Render injects the service's REAL hostname — trust it automatically so a
# renamed service (or a mistyped ALLOWED_HOSTS env var) can never cause the
# every-request-400 DisallowedHost failure again.
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _render_host:
    if _render_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_render_host)
    if f"https://{_render_host}" not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(f"https://{_render_host}")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
