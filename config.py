import os
from datetime import timedelta
from dotenv import load_dotenv


load_dotenv()


DEFAULT_SECRET_KEY = "stokcari-secret-key-2024"
DEFAULT_PASSWORD_SALT = "stokcari-password-reset"
UNSAFE_PLATFORM_ADMIN_EMAILS = {"change_me@example.com"}
UNSAFE_PLATFORM_ADMIN_PASSWORDS = {"CHANGE_ME_TO_A_STRONG_PASSWORD"}


def bool_from_env(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class AppConfig:
    APP_ENV = os.environ.get("APP_ENV", os.environ.get("FLASK_ENV", "development")).lower()
    IS_PRODUCTION = APP_ENV in {"production", "prod"}

    DEBUG = bool_from_env("FLASK_DEBUG", False)
    RUN_HOST = os.environ.get("FLASK_RUN_HOST", "0.0.0.0")
    RUN_PORT = int(os.environ.get("FLASK_RUN_PORT", "5000"))

    SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")
    SITE_NAME = os.environ.get("SITE_NAME", "Esstok")
    SITE_DESCRIPTION = os.environ.get(
        "SITE_DESCRIPTION",
        "Küçük işletmeler için bulut tabanlı stok, cari, POS ve personel yönetimi.",
    )
    SITE_OG_IMAGE = os.environ.get("SITE_OG_IMAGE", "").strip()

    TURNSTILE_ENABLED = bool_from_env("TURNSTILE_ENABLED", False)
    TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
    TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
    TURNSTILE_VERIFY_URL = os.environ.get(
        "TURNSTILE_VERIFY_URL",
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    ).strip()

    # SMTP (password reset, notifications)
    SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_USE_TLS = bool_from_env("SMTP_USE_TLS", True)
    SMTP_USE_SSL = bool_from_env("SMTP_USE_SSL", False)
    SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", SITE_NAME).strip()

    SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)
    SECURITY_PASSWORD_SALT = os.environ.get("SECURITY_PASSWORD_SALT", DEFAULT_PASSWORD_SALT)
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///stokcari.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    WTF_CSRF_ENABLED = bool_from_env("WTF_CSRF_ENABLED", True)
    WTF_CSRF_TIME_LIMIT = int(os.environ.get("WTF_CSRF_TIME_LIMIT", "3600"))

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = bool_from_env("SESSION_COOKIE_SECURE", IS_PRODUCTION)
    SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "esstok_session")
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get("SESSION_HOURS", "12")))

    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_SAMESITE = SESSION_COOKIE_SAMESITE

    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))
    JSON_AS_ASCII = False

    SECURITY_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }


def validate_runtime_config(app):
    if app.config.get("IS_PRODUCTION") and app.config.get("SECRET_KEY") == DEFAULT_SECRET_KEY:
        raise RuntimeError("Production must set a unique SECRET_KEY environment variable.")

    if app.config.get("IS_PRODUCTION") and app.config.get("SECURITY_PASSWORD_SALT") == DEFAULT_PASSWORD_SALT:
        raise RuntimeError("Production must set a unique SECURITY_PASSWORD_SALT environment variable.")

    if app.config.get("IS_PRODUCTION"):
        platform_admin_emails = (os.environ.get("PLATFORM_ADMIN_EMAILS") or "").strip()
        configured_admin_emails = {
            email.strip().lower()
            for email in platform_admin_emails.split(",")
            if email.strip()
        }
        if not configured_admin_emails or configured_admin_emails & UNSAFE_PLATFORM_ADMIN_EMAILS:
            raise RuntimeError(
                "Production must set PLATFORM_ADMIN_EMAILS to a non-default, comma-separated list of admin emails."
            )

        platform_admin_password = os.environ.get("PLATFORM_ADMIN_PASSWORD")
        if not platform_admin_password or platform_admin_password in UNSAFE_PLATFORM_ADMIN_PASSWORDS:
            raise RuntimeError(
                "Production must set PLATFORM_ADMIN_PASSWORD to a strong, non-default password."
            )

        allow_sqlite = bool_from_env("ALLOW_SQLITE_IN_PROD", False)
        db_uri = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").lower()
        if not allow_sqlite and db_uri.startswith("sqlite:"):
            raise RuntimeError("Production must not use SQLite. Set DATABASE_URL to PostgreSQL/MySQL or set ALLOW_SQLITE_IN_PROD=1 for demos.")
