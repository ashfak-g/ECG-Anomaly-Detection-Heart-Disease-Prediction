#!/usr/bin/env python3
"""Idempotent PostgreSQL migration for doctor workflow tables/columns.

Usage:
  source .env
  python scripts/migrate_doctor_workflow.py
"""

from __future__ import annotations

import os
import subprocess
from urllib.parse import urlparse
from pathlib import Path


def load_dotenv_file(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get_database_url() -> str:
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        return database_url

    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv_file(repo_root / '.env')
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL is not set. Export it or place it in .env before running the migration.')
    return database_url


def get_database_name(database_url: str) -> str:
    parsed = urlparse(database_url)
    if not parsed.path or parsed.path == '/':
        raise RuntimeError('DATABASE_URL does not contain a database name.')
    return parsed.path.lstrip('/')


def build_sql(statements):
    return ';\n'.join(statement.strip().rstrip(';') for statement in statements) + ';\n'


def main() -> None:
    database_url = get_database_url()
    database_name = get_database_name(database_url)

    statements = [
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'patient'",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS doctor_verification_status VARCHAR(20) DEFAULT 'not_requested'",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS doctor_verified_at TIMESTAMP WITHOUT TIME ZONE",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS doctor_designation VARCHAR(120)",
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES \"user\"(id) ON DELETE SET NULL,
            action VARCHAR(100) NOT NULL,
            resource_type VARCHAR(50),
            resource_id INTEGER,
            timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            details JSON
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp DESC)",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id)",
        """
        CREATE TABLE IF NOT EXISTS availability_slot (
            id SERIAL PRIMARY KEY,
            doctor_id INTEGER NOT NULL REFERENCES \"user\"(id) ON DELETE CASCADE,
            start_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            end_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            is_booked BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_availability_doctor_id ON availability_slot(doctor_id)",
        "CREATE INDEX IF NOT EXISTS idx_availability_start_time ON availability_slot(start_time)",
        """
        CREATE TABLE IF NOT EXISTS appointment (
            id SERIAL PRIMARY KEY,
            patient_id INTEGER NOT NULL REFERENCES \"user\"(id) ON DELETE CASCADE,
            doctor_id INTEGER NOT NULL REFERENCES \"user\"(id) ON DELETE CASCADE,
            slot_id INTEGER NOT NULL UNIQUE REFERENCES availability_slot(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            reason VARCHAR(500),
            approved_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_appointment_patient_id ON appointment(patient_id)",
        "CREATE INDEX IF NOT EXISTS idx_appointment_doctor_id ON appointment(doctor_id)",
        "CREATE INDEX IF NOT EXISTS idx_appointment_status ON appointment(status)",
        """
        CREATE TABLE IF NOT EXISTS prescription (
            id SERIAL PRIMARY KEY,
            appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointment(id) ON DELETE CASCADE,
            doctor_id INTEGER NOT NULL REFERENCES \"user\"(id) ON DELETE CASCADE,
            patient_id INTEGER NOT NULL REFERENCES \"user\"(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_prescription_doctor_id ON prescription(doctor_id)",
        "CREATE INDEX IF NOT EXISTS idx_prescription_patient_id ON prescription(patient_id)",
        """
        CREATE TABLE IF NOT EXISTS password_reset_otp (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE REFERENCES \"user\"(id) ON DELETE CASCADE,
            otp_hash VARCHAR(255) NOT NULL,
            expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            attempts_left INTEGER NOT NULL DEFAULT 5,
            resend_after TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            consumed_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_password_reset_otp_user_id ON password_reset_otp(user_id)",
    ]

    sql = build_sql(statements + [
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE audit_log TO heart_user",
        "GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO heart_user",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE availability_slot TO heart_user",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE appointment TO heart_user",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE password_reset_otp TO heart_user",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE prescription TO heart_user",
        "GRANT USAGE, SELECT ON SEQUENCE availability_slot_id_seq TO heart_user",
        "GRANT USAGE, SELECT ON SEQUENCE appointment_id_seq TO heart_user",
        "GRANT USAGE, SELECT ON SEQUENCE password_reset_otp_id_seq TO heart_user",
        "GRANT USAGE, SELECT ON SEQUENCE prescription_id_seq TO heart_user",
    ])

    subprocess.run(
        ['sudo', '-u', 'postgres', 'psql', '-d', database_name, '-v', 'ON_ERROR_STOP=1'],
        input=sql,
        text=True,
        check=True,
    )
    print('doctor workflow migration completed successfully')


if __name__ == '__main__':
    main()
