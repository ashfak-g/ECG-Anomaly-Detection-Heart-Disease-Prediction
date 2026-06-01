"""
config.py — Application configuration.
Hardened with session security, cookie flags, connection pooling, and rate-limit settings.
"""

import os
from datetime import timedelta
from dotenv import load_dotenv


# Load variables from local .env file (important for SMTP config in dev/prod).
load_dotenv()


class Config:
    # -----------------------------------------------------------------------
    # Core
    # -----------------------------------------------------------------------
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-prod'

    # -----------------------------------------------------------------------
    # PostgreSQL  (required — no SQLite fallback)
    # -----------------------------------------------------------------------
    _db_url = os.environ.get('DATABASE_URL', '')
    _db_url = _db_url.strip()
    if (_db_url.startswith('"') and _db_url.endswith('"')) or \
       (_db_url.startswith("'") and _db_url.endswith("'")):
        _db_url = _db_url[1:-1].strip()
    DATABASE_URL = _db_url
    if not DATABASE_URL:
        raise ValueError(
            'DATABASE_URL environment variable not set. '
            'Please configure PostgreSQL connection.'
        )
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Connection pooling — prevents stale connections in production
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,      # detect stale connections before use
        "pool_recycle": 1800,        # recycle connections every 30 min
    }

    # -----------------------------------------------------------------------
    # File Uploads
    # -----------------------------------------------------------------------
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'app/static/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

    # -----------------------------------------------------------------------
    # Session & Cookie Security (HIPAA-like controls)
    # -----------------------------------------------------------------------
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    SESSION_COOKIE_HTTPONLY = True        # no JavaScript access to session cookie
    SESSION_COOKIE_SAMESITE = 'Lax'      # CSRF protection

    # -----------------------------------------------------------------------
    # CSRF (via Flask-WTF)
    # -----------------------------------------------------------------------
    WTF_CSRF_ENABLED = True

    # -----------------------------------------------------------------------
    # Gemini AI Key
    # -----------------------------------------------------------------------
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

    # (No third-party fallback configured — Gemini is the supported provider)

    # -----------------------------------------------------------------------
    # Rate Limiting (via Flask-Limiter)
    # -----------------------------------------------------------------------
    # If Redis is available, use it; otherwise fall back to in-memory.
    RATELIMIT_STORAGE_URI = os.environ.get(
        'RATELIMIT_STORAGE_URI', 'memory://'
    )
    RATELIMIT_STRATEGY = 'fixed-window'

    # -----------------------------------------------------------------------
    # JWT (for future API layer)
    # -----------------------------------------------------------------------
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or SECRET_KEY
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # -----------------------------------------------------------------------
    # Email Configuration (Flask-Mail)
    # -----------------------------------------------------------------------
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = (
        os.environ.get('MAIL_DEFAULT_SENDER')
        or os.environ.get('MAIL_USERNAME')
        or 'noreply@heartanomalies.com'
    )
    MAIL_SENDER_NAME = os.environ.get('MAIL_SENDER_NAME', 'Heart Anomalies Team')

    # -----------------------------------------------------------------------
    # Password Reset OTP
    # -----------------------------------------------------------------------
    OTP_LENGTH = int(os.environ.get('OTP_LENGTH', 6))
    OTP_EXPIRY_SECONDS = int(os.environ.get('OTP_EXPIRY_SECONDS', 600))
    OTP_MAX_ATTEMPTS = int(os.environ.get('OTP_MAX_ATTEMPTS', 5))
    OTP_RESEND_COOLDOWN_SECONDS = int(os.environ.get('OTP_RESEND_COOLDOWN_SECONDS', 60))
    # Path to the rate-limit Redis RDB file used by the embedded Redis fallback.
    # By default it lives under ops/redis so repo reorganizations don't break runtime.
    RATE_LIMIT_RDB = os.environ.get(
        'RATE_LIMIT_RDB'
    ) or os.path.join(os.getcwd(), 'ops', 'redis', 'heart-anomalies-rate-limit.rdb')
