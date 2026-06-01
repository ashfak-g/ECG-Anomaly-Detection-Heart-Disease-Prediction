from datetime import datetime
from flask_login import UserMixin
from app import db, login_manager

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # Role: 'patient', 'doctor', or 'admin'
    role = db.Column(db.String(20), nullable=False, default='patient')
    # Doctor verification workflow: not_requested -> pending -> approved/rejected
    doctor_verification_status = db.Column(db.String(20), nullable=False, default='not_requested')
    doctor_verified_at = db.Column(db.DateTime, nullable=True)
    doctor_designation = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    predictions = db.relationship('Prediction', backref='author', lazy=True, cascade='all, delete-orphan')
    medical_info = db.relationship('UserMedicalInfo', backref='user', uselist=False, cascade='all, delete-orphan')
    audit_logs = db.relationship('AuditLog', backref='user', lazy=True)
    availability_slots = db.relationship('AvailabilitySlot', backref='doctor', lazy=True, foreign_keys='AvailabilitySlot.doctor_id', cascade='all, delete-orphan')
    doctor_appointments = db.relationship('Appointment', backref='doctor', lazy=True, foreign_keys='Appointment.doctor_id', cascade='all, delete-orphan')
    patient_appointments = db.relationship('Appointment', backref='patient', lazy=True, foreign_keys='Appointment.patient_id', cascade='all, delete-orphan')
    written_prescriptions = db.relationship('Prescription', backref='doctor_user', lazy=True, foreign_keys='Prescription.doctor_id', cascade='all, delete-orphan')
    received_prescriptions = db.relationship('Prescription', backref='patient_user', lazy=True, foreign_keys='Prescription.patient_id', cascade='all, delete-orphan')
    password_reset_otp = db.relationship('PasswordResetOTP', backref='user', uselist=False, viewonly=True)

    def __repr__(self):
        return f"User('{self.name}', '{self.email}')"

    def is_patient(self):
        return (self.role or 'patient') == 'patient'

    def is_doctor(self):
        return (self.role or '') == 'doctor'

    def is_admin(self):
        return (self.role or '') == 'admin'

    def is_verified_doctor(self):
        return self.is_doctor() and (self.doctor_verification_status or '') == 'approved'

class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(100), nullable=False) # Path relative to static folder
    result = db.Column(db.String(20), nullable=False) # 'Normal' or 'Abnormal'
    confidence = db.Column(db.Float, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f"Prediction('{self.result}', '{self.timestamp}')"


class PasswordResetOTP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    otp_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts_left = db.Column(db.Integer, nullable=False, default=5)
    resend_after = db.Column(db.DateTime, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return (
            f"PasswordResetOTP(user_id={self.user_id}, expires_at={self.expires_at}, "
            f"attempts_left={self.attempts_left})"
        )


class UserMedicalInfo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    age = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(30), nullable=True)
    blood_group = db.Column(db.String(10), nullable=True)
    phone_number = db.Column(db.String(30), nullable=True)
    blood_pressure = db.Column(db.String(30), nullable=True)
    allergy = db.Column(db.String(200), nullable=True)
    diabetes = db.Column(db.Boolean, default=False)
    
    # New Heart Health and Emergency Fields
    weight = db.Column(db.Float, nullable=True)
    height = db.Column(db.Float, nullable=True)
    emergency_contact_name = db.Column(db.String(100), nullable=True)
    emergency_contact_phone = db.Column(db.String(30), nullable=True)
    heart_conditions = db.Column(db.String(500), nullable=True)

    def __repr__(self):
        return f"UserMedicalInfo(user_id={self.user_id}, age={self.age}, gender='{self.gender}')"


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)  # e.g. 'prediction.create', 'report.download', 'prediction.view'
    resource_type = db.Column(db.String(50), nullable=True)
    resource_id = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.JSON, nullable=True)

    def __repr__(self):
        return f"AuditLog(user_id={self.user_id}, action='{self.action}', resource={self.resource_type}:{self.resource_id})"


class AvailabilitySlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    is_booked = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"AvailabilitySlot(doctor_id={self.doctor_id}, start='{self.start_time}', end='{self.end_time}', booked={self.is_booked})"


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('availability_slot.id'), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    reason = db.Column(db.String(500), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    slot = db.relationship('AvailabilitySlot', backref=db.backref('appointment', uselist=False))

    def __repr__(self):
        return f"Appointment(patient_id={self.patient_id}, doctor_id={self.doctor_id}, status='{self.status}')"


class Prescription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False, unique=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    appointment = db.relationship('Appointment', backref=db.backref('prescription', uselist=False))

    def __repr__(self):
        return f"Prescription(appointment_id={self.appointment_id}, doctor_id={self.doctor_id}, patient_id={self.patient_id})"
