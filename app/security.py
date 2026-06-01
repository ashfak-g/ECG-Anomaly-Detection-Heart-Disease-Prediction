"""
security.py — Rate limiting, input validators, and security utilities.
Step 1 & 2 of the production upgrade plan.
"""

import re
import secrets
import logging
import socket
import socketserver
import threading
import os
from urllib.parse import urlparse
from flask import current_app

from redis import Redis as RedisClient
from redis.exceptions import ConnectionError as RedisConnectionError
from redislite import Redis as EmbeddedRedis
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------
# Storage: Redis in production, memory in dev (set RATELIMIT_STORAGE_URI in env)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri=None,  # Overridden by RATELIMIT_STORAGE_URI env var via init_app
)

# Per-endpoint limit decorators (import and apply in auth.py / main.py)
LOGIN_LIMIT       = "5 per minute"     # brute-force protection
REGISTER_LIMIT    = "3 per hour"       # registration spam protection
UPLOAD_LIMIT      = "20 per minute"    # upload spam protection
CHAT_LIMIT        = "30 per minute"    # chatbot abuse protection
API_LIMIT         = "60 per minute"    # general API limit


logger = logging.getLogger(__name__)
_embedded_rate_limit_redis = None
_embedded_rate_limit_proxy = None


def _relay_bytes(source, destination):
    while True:
        chunk = source.recv(4096)
        if not chunk:
            break
        destination.sendall(chunk)


class _RedisProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        backend = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            backend.connect(self.server.backend_socket_path)

            forward = threading.Thread(target=_relay_bytes, args=(self.request, backend), daemon=True)
            backward = threading.Thread(target=_relay_bytes, args=(backend, self.request), daemon=True)
            forward.start()
            backward.start()
            forward.join()
            backward.join()
        finally:
            try:
                backend.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            backend.close()


class _RedisProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

def resolve_rate_limit_storage_uri(storage_uri: str | None) -> str:
    """Keep Redis-backed rate limiting working even when localhost Redis is unavailable."""
    if not storage_uri or storage_uri == "memory://":
        return storage_uri or "memory://"

    try:
        RedisClient.from_url(storage_uri).ping()
        return storage_uri
    except RedisConnectionError:
        parsed = urlparse(storage_uri)
        if parsed.scheme == "redis" and parsed.hostname in {"localhost", "127.0.0.1"}:
            return _start_embedded_rate_limit_redis()
        raise


def _start_embedded_rate_limit_redis() -> str:
    """Start a local Redis-compatible server for development fallback."""
    global _embedded_rate_limit_redis, _embedded_rate_limit_proxy

    if _embedded_rate_limit_redis is None:
        logger.warning("Starting embedded Redis for rate limiting because localhost Redis is unavailable.")
        # Allow an application-configured path for the RDB file so the repository
        # can be reorganized without breaking the embedded Redis fallback.
        rdb_path = None
        try:
            rdb_path = current_app.config.get('RATE_LIMIT_RDB')
        except RuntimeError:
            # current_app may not be available when called outside an application context.
            rdb_path = None
        if not rdb_path:
            rdb_path = os.path.join(os.getcwd(), 'heart-anomalies-rate-limit.rdb')
        _embedded_rate_limit_redis = EmbeddedRedis(dbfilename=rdb_path)

    socket_path = _embedded_rate_limit_redis.socket_file
    if not socket_path:
        raise RuntimeError("Embedded Redis did not expose a Unix socket path.")

    parsed = urlparse("redis://localhost:6379/0")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379

    if _embedded_rate_limit_proxy is None:
        try:
            _embedded_rate_limit_proxy = _RedisProxyServer((host, port), _RedisProxyHandler)
            _embedded_rate_limit_proxy.backend_socket_path = socket_path
            threading.Thread(target=_embedded_rate_limit_proxy.serve_forever, daemon=True).start()
        except OSError:
            logger.warning("Could not bind embedded Redis proxy to %s:%s; reusing an available Redis service if present.", host, port)

    return "redis://localhost:6379/0"


# ---------------------------------------------------------------------------
# Input Validators
# ---------------------------------------------------------------------------

# Allowed image MIME types – enforced by python-magic in utils.py
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}

# Max pixels to prevent decompression-bomb attacks
MAX_IMAGE_PIXELS = 50_000_000  # ~50MP

# Password policy
PASSWORD_MIN_LENGTH = 8
PASSWORD_PATTERN = re.compile(
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$'
)


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message)."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r'\d', password):
        return False, "Password must contain at least one digit."
    return True, ""


def sanitize_text(value: str, max_length: int = 500) -> str:
    """Strip leading/trailing whitespace and truncate."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


# ---------------------------------------------------------------------------
# Security Headers Middleware
# ---------------------------------------------------------------------------

def apply_security_headers(response):
    """
    Add OWASP-recommended security headers to every response.
    Register via: app.after_request(apply_security_headers)
    """
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    # NOTE: Enable Strict-Transport-Security only after HTTPS is confirmed live
    # response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


def generate_numeric_otp(length: int = 6) -> str:
    """Generate a cryptographically secure numeric OTP of a fixed length."""
    if length < 4:
        length = 4
    max_value = 10 ** length
    return f"{secrets.randbelow(max_value):0{length}d}"


def hash_otp(otp: str) -> str:
    """Hash OTP so raw codes are never stored in the database."""
    return generate_password_hash(otp)


def verify_otp_hash(otp_hash: str, otp_input: str) -> bool:
    """Compare user OTP input against the stored hash."""
    return check_password_hash(otp_hash, otp_input)
