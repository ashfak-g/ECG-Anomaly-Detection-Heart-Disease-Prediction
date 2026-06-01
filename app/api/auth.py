"""
app/api/auth.py — JWT authentication endpoints for mobile/API clients.
"""

from flask import request, jsonify
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
)
from werkzeug.security import check_password_hash

from app.api import api
from app.models import User, AuditLog
from app import db
from app.security import API_LIMIT, limiter


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------
@api.route('/auth/login', methods=['POST'])
@limiter.limit(API_LIMIT)
def api_login():
    """
    Authenticate and receive JWT tokens.

    Request body (JSON):
        { "email": "...", "password": "..." }

    Response (200):
        { "access_token": "...", "refresh_token": "...", "user": {...} }
    """
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify(error="Email and password are required."), 400

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify(error="Invalid email or password."), 401

    # Doctor must be verified
    if user.role == 'doctor' and user.doctor_verification_status != 'approved':
        return jsonify(error="Doctor account is pending admin approval."), 403

    identity = {'id': user.id, 'role': user.role}
    access_token = create_access_token(identity=identity)
    refresh_token = create_refresh_token(identity=identity)

    # Audit log
    try:
        db.session.add(AuditLog(
            user_id=user.id,
            action='api.login',
            resource_type='user',
            resource_id=user.id,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            'id': user.id,
            'name': user.name,
            'email': user.email,
            'role': user.role,
        }
    ), 200


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------
@api.route('/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def api_refresh():
    """Exchange a valid refresh token for a new access token."""
    identity = get_jwt_identity()
    new_access = create_access_token(identity=identity)
    return jsonify(access_token=new_access), 200


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------
@api.route('/auth/me', methods=['GET'])
@jwt_required()
def api_me():
    """Return the authenticated user's profile."""
    identity = get_jwt_identity()
    user = User.query.get(identity['id'])
    if not user:
        return jsonify(error="User not found."), 404

    return jsonify(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        doctor_verification_status=getattr(user, 'doctor_verification_status', None),
    ), 200
