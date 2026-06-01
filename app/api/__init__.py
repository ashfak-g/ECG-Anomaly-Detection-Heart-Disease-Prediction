"""
app/api/__init__.py — REST API blueprint for mobile/external clients.
Uses JWT authentication via Flask-JWT-Extended.
"""

from flask import Blueprint

api = Blueprint('api', __name__, url_prefix='/api')

from app.api import auth as api_auth_module      # noqa: F401, E402
from app.api import predictions as api_pred_module  # noqa: F401, E402
