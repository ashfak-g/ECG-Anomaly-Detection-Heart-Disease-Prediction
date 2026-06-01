-- PostgreSQL schema for Heart Anomalies app
-- Run with:
--   psql -U <db_user> -d <db_name> -f postgres_schema.sql

CREATE TABLE IF NOT EXISTS "user" (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'patient',
    doctor_verification_status VARCHAR(20) NOT NULL DEFAULT 'not_requested',
    doctor_verified_at TIMESTAMP WITHOUT TIME ZONE,
    doctor_designation VARCHAR(120),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- For existing databases created before role support
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'patient';
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS doctor_verification_status VARCHAR(20) DEFAULT 'not_requested';
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS doctor_verified_at TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS doctor_designation VARCHAR(120);

CREATE TABLE IF NOT EXISTS prediction (
    id SERIAL PRIMARY KEY,
    image_path VARCHAR(100) NOT NULL,
    result VARCHAR(20) NOT NULL,
    confidence DOUBLE PRECISION,
    timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    user_id INTEGER NOT NULL,
    CONSTRAINT fk_prediction_user
        FOREIGN KEY (user_id)
        REFERENCES "user" (id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_prediction_user_id ON prediction (user_id);

CREATE TABLE IF NOT EXISTS user_medical_info (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    age INTEGER,
    gender VARCHAR(30),
    blood_group VARCHAR(10),
    phone_number VARCHAR(30),
    blood_pressure VARCHAR(30),
    allergy VARCHAR(200),
    diabetes BOOLEAN DEFAULT FALSE,
    CONSTRAINT fk_user_medical_info_user
        FOREIGN KEY (user_id)
        REFERENCES "user" (id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_medical_info_user_id ON user_medical_info (user_id);

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
);

CREATE INDEX IF NOT EXISTS idx_password_reset_otp_user_id ON password_reset_otp (user_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id INTEGER,
    timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    details JSON,
    CONSTRAINT fk_audit_log_user
        FOREIGN KEY (user_id)
        REFERENCES "user" (id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log (user_id);

CREATE TABLE IF NOT EXISTS availability_slot (
    id SERIAL PRIMARY KEY,
    doctor_id INTEGER NOT NULL,
    start_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    end_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    is_booked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    CONSTRAINT fk_availability_doctor
        FOREIGN KEY (doctor_id)
        REFERENCES "user" (id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_availability_doctor_id ON availability_slot (doctor_id);
CREATE INDEX IF NOT EXISTS idx_availability_start_time ON availability_slot (start_time);

CREATE TABLE IF NOT EXISTS appointment (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    slot_id INTEGER NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reason VARCHAR(500),
    approved_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    CONSTRAINT fk_appointment_patient
        FOREIGN KEY (patient_id)
        REFERENCES "user" (id)
        ON DELETE CASCADE,
    CONSTRAINT fk_appointment_doctor
        FOREIGN KEY (doctor_id)
        REFERENCES "user" (id)
        ON DELETE CASCADE,
    CONSTRAINT fk_appointment_slot
        FOREIGN KEY (slot_id)
        REFERENCES availability_slot (id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_appointment_patient_id ON appointment (patient_id);
CREATE INDEX IF NOT EXISTS idx_appointment_doctor_id ON appointment (doctor_id);
CREATE INDEX IF NOT EXISTS idx_appointment_status ON appointment (status);

CREATE TABLE IF NOT EXISTS prescription (
    id SERIAL PRIMARY KEY,
    appointment_id INTEGER NOT NULL UNIQUE,
    doctor_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    CONSTRAINT fk_prescription_appointment
        FOREIGN KEY (appointment_id)
        REFERENCES appointment (id)
        ON DELETE CASCADE,
    CONSTRAINT fk_prescription_doctor
        FOREIGN KEY (doctor_id)
        REFERENCES "user" (id)
        ON DELETE CASCADE,
    CONSTRAINT fk_prescription_patient
        FOREIGN KEY (patient_id)
        REFERENCES "user" (id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_prescription_doctor_id ON prescription (doctor_id);
CREATE INDEX IF NOT EXISTS idx_prescription_patient_id ON prescription (patient_id);

-- ==========================================================================
-- Production performance indexes (added by upgrade plan)
-- ==========================================================================

-- Prediction timeline queries: ORDER BY timestamp DESC for a given user
CREATE INDEX IF NOT EXISTS idx_prediction_user_timestamp
    ON prediction (user_id, timestamp DESC);

-- Appointment lookups by doctor + status (doctor dashboard)
CREATE INDEX IF NOT EXISTS idx_appointment_doctor_status
    ON appointment (doctor_id, status);

-- Audit log queries: per-user timeline
CREATE INDEX IF NOT EXISTS idx_audit_log_user_timestamp
    ON audit_log (user_id, timestamp DESC);

-- Availability slot lookup: open slots for a doctor, sorted by time
CREATE INDEX IF NOT EXISTS idx_availability_slot_doctor_booked
    ON availability_slot (doctor_id, is_booked, start_time);

-- User lookup by role (admin panel filtering)
CREATE INDEX IF NOT EXISTS idx_user_role ON "user" (role);
