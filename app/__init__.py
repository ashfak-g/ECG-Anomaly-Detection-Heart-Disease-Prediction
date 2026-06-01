"""
Heart Anomalies — Flask application factory.
Initialises: SQLAlchemy, Flask-Login, rate limiter, security headers, request timing.
"""

import os
import time
import logging

from flask import Flask, g, request as flask_request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_jwt_extended import JWTManager
from flask_mail import Mail
from config import Config

# ---------------------------------------------------------------------------
# Extensions (created here, initialised in create_app)
# ---------------------------------------------------------------------------
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'
jwt = JWTManager()
mail = Mail()

logger = logging.getLogger(__name__)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # ------------------------------------------------------------------
    # Initialise extensions
    # ------------------------------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)
    jwt.init_app(app)
    mail.init_app(app)

    # Rate limiter
    from app.security import limiter, apply_security_headers, resolve_rate_limit_storage_uri
    app.config['RATELIMIT_STORAGE_URI'] = resolve_rate_limit_storage_uri(
        app.config.get('RATELIMIT_STORAGE_URI')
    )
    limiter.init_app(app)

    # Security headers on every response
    app.after_request(apply_security_headers)

    # ------------------------------------------------------------------
    # Request timing middleware (Step 10)
    # ------------------------------------------------------------------
    @app.before_request
    def _start_timer():
        g.start_time = time.time()

    @app.after_request
    def _log_request(response):
        if hasattr(g, 'start_time'):
            elapsed = time.time() - g.start_time
            logger.info(
                "%s %s %s %.3fs",
                flask_request.method,
                flask_request.path,
                response.status_code,
                elapsed,
            )
        return response

    # ------------------------------------------------------------------
    # Register blueprints
    # ------------------------------------------------------------------
    from app.auth import auth as auth_blueprint
    from app.main import main as main_blueprint
    from app.api import api as api_blueprint

    app.register_blueprint(auth_blueprint)
    app.register_blueprint(main_blueprint)
    app.register_blueprint(api_blueprint)

    # ------------------------------------------------------------------
    # Ensure upload folder exists
    # ------------------------------------------------------------------
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # ------------------------------------------------------------------
    # Create tables & apply migrations
    # ------------------------------------------------------------------
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            # Continue app startup even if this DB user cannot create tables.
            db.session.rollback()

        # Ensure password reset OTP storage exists for forgot-password flow.
        try:
            from sqlalchemy import text
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS password_reset_otp (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL UNIQUE,
                    otp_hash VARCHAR(255) NOT NULL,
                    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                    attempts_left INTEGER NOT NULL DEFAULT 5,
                    resend_after TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                    consumed_at TIMESTAMP WITHOUT TIME ZONE,
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                    CONSTRAINT fk_password_reset_otp_user
                        FOREIGN KEY (user_id)
                        REFERENCES "user" (id)
                        ON DELETE CASCADE
                )
            """))
            db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_password_reset_otp_user_id ON password_reset_otp (user_id)"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Ensure `role` column exists on `user` table for RBAC (adds column if missing)
        try:
            db.session.execute(text("ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'patient'"))
            db.session.execute(text("ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS doctor_verification_status VARCHAR(20) DEFAULT 'not_requested'"))
            db.session.execute(text("ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS doctor_verified_at TIMESTAMP"))
            db.session.execute(text("ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS doctor_designation VARCHAR(120)"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    return app
