import os
from pathlib import Path
from dotenv import load_dotenv
import ssl

try:
    import certifi
except Exception:
    certifi = None

BASE_DIR = Path(__file__).resolve().parent.parent

# Подгружаем .env из стандартных мест проекта (с приоритетом ближайшего).
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv()

# SECURITY
SECRET_KEY = os.getenv("SECRET_KEY")
DEBUG = os.getenv("DEBUG") == "True"

ALLOWED_HOSTS = ["*"]

# APPLICATIONS
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

# REST FRAMEWORK
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    )
}
# MIDDLEWARE
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

# URLS / WSGI
ROOT_URLCONF = "rental_service.urls"
WSGI_APPLICATION = "rental_service.wsgi.application"

# TEMPLATES
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

# DATABASE
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'postgres',
        'USER': 'postgres',
        'PASSWORD': os.environ.get("DB_PASSWORD"),
        'HOST': '/cloudsql/ski-rent:europe-west1:mqwmee',
        'PORT': '5432',
    }
}

# AUTH
AUTH_USER_MODEL = "users.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# INTERNATIONALIZATION
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# STATIC
STATIC_URL = '/static/'
STATIC_ROOT = 'static'
STATICFILES_DIRS = []

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ski-rent-contract-otp",
    }
}

SMSC_LOGIN = os.getenv("SMSC_LOGIN", "")
SMSC_PASSWORD = os.getenv("SMSC_PASSWORD", "")
SMS_SENDER = os.getenv("SMS_SENDER", "SkiRent")
SMS_API_URL = os.getenv("SMS_API_URL", "https://smsc.kz/sys/send.php")
# Если True, при ошибках провайдера не подменяем отправку консольным debug-успехом.
SMS_STRICT_REAL_SEND = os.getenv("SMS_STRICT_REAL_SEND", "True") == "True"

OTP_EXPIRE_SECONDS = 120

# EMAIL
# По умолчанию отправляем через SMTP, чтобы письма реально приходили.
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True") == "True"
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False") == "True"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "no-reply@skirent.local")

# На некоторых macOS/Python окружениях нет корректного системного trust store.
# Если certifi доступен, указываем его CA bundle для SMTP TLS.
if certifi is not None:
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

# Дополнительная настройка таймаута подключения к SMTP.
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))
# AI Assistant (Решид)
# Добавьте в .env файл: ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
