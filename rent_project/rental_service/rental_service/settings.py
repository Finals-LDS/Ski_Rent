import os
from pathlib import Path

from dotenv import load_dotenv

try:
    import certifi
except Exception:
    certifi = None


BASE_DIR = Path(__file__).resolve().parent.parent

# Подгружаем .env из стандартных мест проекта (с приоритетом ближайшего).
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv()


# ─────────────────────────────────────────
#  SECURITY
# ─────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY")
DEBUG = os.getenv("DEBUG") == "True"
ALLOWED_HOSTS = ["*"]


# ─────────────────────────────────────────
#  APPLICATIONS
# ─────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # apps
    "clients",
    "equipment",
    "rentals",
    "web",
    "payments",
    "users",

    # third-party
    "rest_framework",
    "corsheaders",
]


# ─────────────────────────────────────────
#  REST FRAMEWORK
# ─────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}


# ─────────────────────────────────────────
#  MIDDLEWARE
# ─────────────────────────────────────────
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",

    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CORS_ALLOW_ALL_ORIGINS = True


# ─────────────────────────────────────────
#  URLS / WSGI
# ─────────────────────────────────────────
ROOT_URLCONF = "rental_service.urls"
WSGI_APPLICATION = "rental_service.wsgi.application"


# ─────────────────────────────────────────
#  TEMPLATES
# ─────────────────────────────────────────
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


# ─────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────
DB_ENGINE = os.getenv("DB_ENGINE", "django.db.backends.sqlite3")

if DB_ENGINE == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": BASE_DIR / os.getenv("DB_NAME", "db.sqlite3"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": os.getenv("DB_NAME", "postgres"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }


# ─────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────
AUTH_USER_MODEL = "users.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ─────────────────────────────────────────
#  INTERNATIONALIZATION
# ─────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# ─────────────────────────────────────────
#  STATIC
# ─────────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = 'static'
STATICFILES_DIRS = []


# ─────────────────────────────────────────
#  CACHE (используется для OTP и cooldown)
# ─────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ski-rent-contract-otp",
    },
}


# ─────────────────────────────────────────
#  SMS (smsc.kz)
# ─────────────────────────────────────────
SMSC_LOGIN    = os.getenv("SMSC_LOGIN", "")
SMSC_PASSWORD = os.getenv("SMSC_PASSWORD", "")
SMS_SENDER    = os.getenv("SMS_SENDER", "SkiRent")
SMS_API_URL   = os.getenv("SMS_API_URL", "https://smsc.kz/sys/send.php")
# Если True, при ошибках провайдера не подменяем отправку консольным debug-успехом.
SMS_STRICT_REAL_SEND = os.getenv("SMS_STRICT_REAL_SEND", "True") == "True"

OTP_EXPIRE_SECONDS = 120


# ─────────────────────────────────────────
#  EMAIL
# ─────────────────────────────────────────
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)

EMAIL_HOST          = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT          = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS       = os.getenv("EMAIL_USE_TLS", "True") == "True"
EMAIL_USE_SSL       = os.getenv("EMAIL_USE_SSL", "False") == "True"
EMAIL_HOST_USER     = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL  = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "no-reply@skirent.local")
EMAIL_TIMEOUT       = int(os.getenv("EMAIL_TIMEOUT", "20"))

# На некоторых macOS/Python окружениях нет корректного системного trust store.
# Если certifi доступен, указываем его CA bundle для SMTP TLS.
if certifi is not None:
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

# ─────────────────────────────────────────
#  AI Assistant (OpenRouter)
# ─────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")

OPENROUTER_MODELS = [
    "mistralai/mistral-7b-instruct:free",
    "meta-llama/llama-3.1-8b-instruct",
    "gryphe/mythomax-l2-13b",
]