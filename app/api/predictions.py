"""
app/api/predictions.py — REST API endpoints for ECG upload and prediction history.
"""

import os
import numpy as np

from flask import request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.api import api
from app.models import Prediction, AuditLog
from app import db
from app.utils import save_picture
from app.ai import predict_image, predict_signal, get_model_status
from app.security import UPLOAD_LIMIT, limiter


# ---------------------------------------------------------------------------
# POST /api/predictions — Upload ECG + run inference
# ---------------------------------------------------------------------------
@api.route('/predictions', methods=['POST'])
@jwt_required()
@limiter.limit(UPLOAD_LIMIT)
def api_create_prediction():
    """
    Upload an ECG image and get an AI prediction.

    Request: multipart/form-data with field 'image'.

    Response (201):
        {
            "id": 1,
            "result": "Normal",
            "confidence": 0.92,
            "image_url": "/static/uploads/abc.png",
            "timestamp": "2026-05-03T12:00:00"
        }
    """
    identity = get_jwt_identity()
    user_id = identity['id']

    if 'image' not in request.files:
        return jsonify(error="No image file provided."), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify(error="Empty filename."), 400

    try:
        picture_file = save_picture(file)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], picture_file)
    result, confidence, metadata = predict_image(full_path)

    prediction = Prediction(
        image_path=picture_file,
        result=result,
        confidence=confidence,
        user_id=user_id,
    )
    db.session.add(prediction)
    db.session.commit()

    # Audit log with extended metadata
    try:
        db.session.add(AuditLog(
            user_id=user_id,
            action='api.prediction.create',
            resource_type='prediction',
            resource_id=prediction.id,
            details={
                'result': result,
                'confidence': float(confidence) if confidence else None,
                'method': metadata.get('method'),
                'class_name': metadata.get('class_name'),
                'processing_time_ms': metadata.get('processing_time_ms')
            }
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify(
        id=prediction.id,
        result=prediction.result,
        confidence=prediction.confidence,
        image_url=f"/static/uploads/{prediction.image_path}",
        timestamp=prediction.timestamp.isoformat(),
        method=metadata.get('method'),
        class_name=metadata.get('class_name'),
        class_probabilities=metadata.get('all_probabilities'),
        processing_time_ms=metadata.get('processing_time_ms'),
    ), 201


# ---------------------------------------------------------------------------
# POST /api/predictions/signal — Direct ECG signal inference
# ---------------------------------------------------------------------------
@api.route('/predictions/signal', methods=['POST'])
@jwt_required()
@limiter.limit(UPLOAD_LIMIT)
def api_create_signal_prediction():
    """Predict from a raw ECG signal array of length 187."""
    identity = get_jwt_identity()
    user_id = identity['id']

    payload = request.get_json(silent=True) or {}
    signal = payload.get('signal')

    if not isinstance(signal, list):
        return jsonify(error="Field 'signal' must be a JSON array."), 400

    if len(signal) != 187:
        return jsonify(error="Signal length must be exactly 187."), 400

    try:
        signal_np = np.asarray(signal, dtype=np.float32)
    except Exception:
        return jsonify(error="Signal contains non-numeric values."), 400

    result, confidence, metadata = predict_signal(signal_np)

    prediction = Prediction(
        image_path='signal-input',
        result=result,
        confidence=confidence,
        user_id=user_id,
    )
    db.session.add(prediction)
    db.session.commit()

    try:
        db.session.add(AuditLog(
            user_id=user_id,
            action='api.prediction.signal.create',
            resource_type='prediction',
            resource_id=prediction.id,
            details={
                'result': result,
                'confidence': float(confidence) if confidence else None,
                'method': metadata.get('method'),
                'class_name': metadata.get('class_name'),
                'processing_time_ms': metadata.get('processing_time_ms')
            }
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify(
        id=prediction.id,
        result=prediction.result,
        confidence=prediction.confidence,
        timestamp=prediction.timestamp.isoformat(),
        method=metadata.get('method'),
        class_name=metadata.get('class_name'),
        class_probabilities=metadata.get('all_probabilities'),
        processing_time_ms=metadata.get('processing_time_ms'),
    ), 201


# ---------------------------------------------------------------------------
# GET /api/model/status — Model health/status endpoint
# ---------------------------------------------------------------------------
@api.route('/model/status', methods=['GET'])
@jwt_required()
def api_model_status():
    """Return model health and metadata for operational checks."""
    status = get_model_status()
    code = 200 if status.get('status') == 'healthy' else 503
    return jsonify(status), code


# ---------------------------------------------------------------------------
# GET /api/predictions — List user's prediction history
# ---------------------------------------------------------------------------
@api.route('/predictions', methods=['GET'])
@jwt_required()
def api_list_predictions():
    """
    List the authenticated user's ECG prediction history.

    Query params:
        page (int, default 1)
        per_page (int, default 20, max 100)

    Response (200):
        { "predictions": [...], "total": N, "page": 1, "per_page": 20 }
    """
    identity = get_jwt_identity()
    user_id = identity['id']

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)

    pagination = Prediction.query.filter_by(
        user_id=user_id
    ).order_by(
        Prediction.timestamp.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    predictions = [
        {
            'id': p.id,
            'result': p.result,
            'confidence': p.confidence,
            'image_url': f"/static/uploads/{p.image_path}",
            'timestamp': p.timestamp.isoformat(),
        }
        for p in pagination.items
    ]

    return jsonify(
        predictions=predictions,
        total=pagination.total,
        page=pagination.page,
        per_page=pagination.per_page,
    ), 200


# ---------------------------------------------------------------------------
# GET /api/predictions/<id> — Get a single prediction
# ---------------------------------------------------------------------------
@api.route('/predictions/<int:prediction_id>', methods=['GET'])
@jwt_required()
def api_get_prediction(prediction_id):
    """Get a single prediction detail."""
    identity = get_jwt_identity()
    user_id = identity['id']
    user_role = identity.get('role', 'patient')

    prediction = Prediction.query.get_or_404(prediction_id)

    # Access control: owner, doctor, or admin
    if prediction.user_id != user_id and user_role not in ('doctor', 'admin'):
        return jsonify(error="Access denied."), 403

    return jsonify(
        id=prediction.id,
        result=prediction.result,
        confidence=prediction.confidence,
        image_url=f"/static/uploads/{prediction.image_path}",
        timestamp=prediction.timestamp.isoformat(),
        user_id=prediction.user_id,
    ), 200
