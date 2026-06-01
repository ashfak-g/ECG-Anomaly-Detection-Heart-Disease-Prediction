"""
email.py — Email sending utilities for appointment notifications.
Integrates with Flask-Mail for SMTP-based email delivery.
"""

import logging
from flask_mail import Message
from flask import current_app
from app import mail

logger = logging.getLogger(__name__)


def send_email(to, subject, text_body, html_body=None):
    """
    Send an email via SMTP.
    
    Args:
        to (str): Recipient email address
        subject (str): Email subject
        text_body (str): Plain text email body
        html_body (str): HTML email body (optional)
    
    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        username = current_app.config.get('MAIL_USERNAME')
        password = current_app.config.get('MAIL_PASSWORD')
        if not username or not password:
            logger.error(
                "Email not sent: MAIL_USERNAME/MAIL_PASSWORD is not configured. "
                "Set SMTP credentials in environment variables."
            )
            return False

        msg = Message(subject=subject, recipients=[to], body=text_body, html=html_body)
        mail.send(msg)
        logger.info(f"Email sent successfully to {to}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {str(e)}")
        return False


def send_appointment_approved(patient_email, patient_name, doctor_name, appointment_date, appointment_time):
    """
    Send appointment approval notification to patient.
    
    Args:
        patient_email (str): Patient's email address
        patient_name (str): Patient's full name
        doctor_name (str): Doctor's full name
        appointment_date (str): Date of appointment (formatted)
        appointment_time (str): Time of appointment (formatted)
    
    Returns:
        bool: True if sent successfully, False otherwise
    """
    subject = "Appointment Approved - Heart Anomalies"
    
    # Plain text body
    text_body = f"""
Dear {patient_name},

Your appointment request has been approved!

Doctor: {doctor_name}
Date: {appointment_date}
Time: {appointment_time}

Please ensure you arrive 10 minutes early. If you need to reschedule, you can do so through your account dashboard.

Best regards,
Heart Anomalies Team
"""

    # HTML body
    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; padding: 20px; border-radius: 8px;">
                <h2 style="color: #4CAF50;">Appointment Approved</h2>
                
                <p>Dear <strong>{patient_name}</strong>,</p>
                
                <p>Your appointment request has been <strong style="color: #4CAF50;">approved</strong>!</p>
                
                <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p><strong>Doctor:</strong> {doctor_name}</p>
                    <p><strong>Date:</strong> {appointment_date}</p>
                    <p><strong>Time:</strong> {appointment_time}</p>
                </div>
                
                <p style="color: #666;">Please ensure you arrive 10 minutes early. If you need to reschedule, you can do so through your account dashboard.</p>
                
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                <p style="color: #888; font-size: 12px; text-align: center;">Heart Anomalies Team | ECG Analysis Platform</p>
            </div>
        </body>
    </html>
    """
    
    return send_email(patient_email, subject, text_body, html_body)


def send_appointment_rejected(patient_email, patient_name, doctor_name, reason=None):
    """
    Send appointment rejection notification to patient.
    
    Args:
        patient_email (str): Patient's email address
        patient_name (str): Patient's full name
        doctor_name (str): Doctor's full name
        reason (str): Optional reason for rejection
    
    Returns:
        bool: True if sent successfully, False otherwise
    """
    subject = "Appointment Status Update - Heart Anomalies"
    
    reason_text = f"\nReason: {reason}" if reason else ""
    
    # Plain text body
    text_body = f"""
Dear {patient_name},

Unfortunately, your appointment request with Dr. {doctor_name} could not be approved at this time.{reason_text}

You can request another appointment or contact the clinic directly for assistance.

Please visit your account dashboard to view available time slots or request a new appointment.

Best regards,
Heart Anomalies Team
"""

    # HTML body
    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; padding: 20px; border-radius: 8px;">
                <h2 style="color: #FF9800;">Appointment Status Update</h2>
                
                <p>Dear <strong>{patient_name}</strong>,</p>
                
                <p>Unfortunately, your appointment request with Dr. <strong>{doctor_name}</strong> could not be approved at this time.</p>
                
                {"<div style='background-color: #fff3cd; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #FF9800;'><p><strong>Reason:</strong> " + reason + "</p></div>" if reason else ""}
                
                <p style="color: #666;">You can request another appointment or contact the clinic directly for assistance. Please visit your account dashboard to view available time slots or request a new appointment.</p>
                
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                <p style="color: #888; font-size: 12px; text-align: center;">Heart Anomalies Team | ECG Analysis Platform</p>
            </div>
        </body>
    </html>
    """
    
    return send_email(patient_email, subject, text_body, html_body)


def send_password_reset_otp_email(user_email, user_name, otp_code):
    """Send password reset OTP to the user email address."""
    subject = "Password Reset OTP - Heart Anomalies"

    text_body = f"""
Dear {user_name},

Your OTP for password reset is: {otp_code}

This OTP will expire in 10 minutes.
If you did not request this password reset, please ignore this email.

Best regards,
Heart Anomalies Team
"""

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; padding: 20px; border-radius: 8px;">
                <h2 style="color: #1E88E5;">Password Reset OTP</h2>
                <p>Dear <strong>{user_name}</strong>,</p>
                <p>Use the OTP below to reset your password:</p>
                <div style="background-color: #f5f5f5; padding: 16px; border-radius: 6px; text-align: center; margin: 18px 0;">
                    <span style="font-size: 28px; font-weight: 700; letter-spacing: 4px; color: #1E88E5;">{otp_code}</span>
                </div>
                <p style="color: #d32f2f;"><strong>This OTP will expire in 10 minutes.</strong></p>
                <p style="color: #666;">If you did not request this password reset, you can safely ignore this email.</p>
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                <p style="color: #888; font-size: 12px; text-align: center;">Heart Anomalies Team | ECG Analysis Platform</p>
            </div>
        </body>
    </html>
    """

    return send_email(user_email, subject, text_body, html_body)


def send_login_2fa_otp_email(user_email, user_name, otp_code):
    """Send login 2FA OTP to the user email address."""
    subject = "Login Verification OTP - Heart Anomalies"

    text_body = f"""
Dear {user_name},

Your OTP for login verification is: {otp_code}

This OTP will expire in 10 minutes.
If you did not attempt to log in, please secure your account.

Best regards,
Heart Anomalies Team
"""

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; padding: 20px; border-radius: 8px;">
                <h2 style="color: #1E88E5;">Login Verification OTP</h2>
                <p>Dear <strong>{user_name}</strong>,</p>
                <p>Use the OTP below to verify your login:</p>
                <div style="background-color: #f5f5f5; padding: 16px; border-radius: 6px; text-align: center; margin: 18px 0;">
                    <span style="font-size: 28px; font-weight: 700; letter-spacing: 4px; color: #1E88E5;">{otp_code}</span>
                </div>
                <p style="color: #d32f2f;"><strong>This OTP will expire in 10 minutes.</strong></p>
                <p style="color: #666;">If you did not attempt to log in, please secure your account immediately.</p>
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                <p style="color: #888; font-size: 12px; text-align: center;">Heart Anomalies Team | ECG Analysis Platform</p>
            </div>
        </body>
    </html>
    """

    return send_email(user_email, subject, text_body, html_body)
