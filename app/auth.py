from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, current_user, logout_user
from app import db
from app.models import User
from app.forms import (
    RegistrationForm,
    LoginForm,
    DoctorRegistrationForm,
    ForgotPasswordForm,
    VerifyOtpForm,
    ResendOtpForm,
    ResetPasswordForm,
)
from werkzeug.security import generate_password_hash, check_password_hash
from app.main import medical_info_complete
from app.security import limiter, LOGIN_LIMIT, generate_numeric_otp, hash_otp, verify_otp_hash
from app.email import send_password_reset_otp_email, send_login_2fa_otp_email

auth = Blueprint('auth', __name__)


def _redirect_for_role(user):
    if user.role == 'admin':
        return url_for('main.admin_analytics')
    if user.role == 'doctor':
        return url_for('main.doctor_dashboard')
    return url_for('main.dashboard')


def _find_reset_user(email: str):
    """Allow OTP reset only for patient and doctor roles."""
    return User.query.filter(User.email.ilike(email), User.role.in_(['patient', 'doctor'])).first()


def _get_password_reset_state():
    return session.get('password_reset_state') or {}


def _set_password_reset_state(state):
    session['password_reset_state'] = state


def _clear_password_reset_state():
    session.pop('password_reset_state', None)


def _send_password_reset_otp(user, otp_value):
    sent = send_password_reset_otp_email(user.email, user.name, otp_value)
    if not sent:
        current_app.logger.warning(
            'Password reset OTP email failed for %s. OTP value: %s',
            user.email,
            otp_value,
        )
    return sent


def _get_login_2fa_state():
    return session.get('login_2fa_state') or {}


def _set_login_2fa_state(state):
    session['login_2fa_state'] = state


def _clear_login_2fa_state():
    session.pop('login_2fa_state', None)
    session.pop('login_2fa_user_id', None)
    session.pop('login_2fa_next', None)


def _send_login_2fa_otp(user, otp_value):
    sent = send_login_2fa_otp_email(user.email, user.name, otp_value)
    if not sent:
        current_app.logger.warning(
            'Login 2FA OTP email failed for %s. OTP value: %s',
            user.email,
            otp_value,
        )
    return sent


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(_redirect_for_role(current_user))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        user = User(name=form.name.data, email=form.email.data, password_hash=hashed_password, role='patient')
        db.session.add(user)
        db.session.commit()
        flash('Your account has been created! You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('register.html', title='Register', form=form)


@auth.route('/doctor/register', methods=['GET', 'POST'])
def doctor_register():
    if current_user.is_authenticated:
        return redirect(_redirect_for_role(current_user))
    form = DoctorRegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        user = User(
            name=form.name.data,
            email=form.email.data.lower(),
            password_hash=hashed_password,
            role='doctor',
            doctor_designation=form.designation.data,
            doctor_verification_status='pending',
        )
        db.session.add(user)
        db.session.commit()
        flash('Doctor account created and sent for admin verification.', 'success')
        return redirect(url_for('auth.doctor_login'))
    return render_template('doctor_register.html', title='Doctor Register', form=form)


@auth.route('/doctor/portal')
def doctor_portal():
    if current_user.is_authenticated and current_user.role == 'doctor':
        return redirect(_redirect_for_role(current_user))
    return render_template('doctor_portal.html', title='Doctor Portal')

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_redirect_for_role(current_user))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            if user.role == 'doctor':
                flash('Please use the doctor login page.', 'warning')
                return redirect(url_for('auth.doctor_login'))
            
            if user.role == 'admin':
                login_user(user)
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(_redirect_for_role(user))
            
            # Initiate 2FA for patient
            _clear_login_2fa_state()
            session['login_2fa_user_id'] = user.id
            session['login_2fa_next'] = request.args.get('next')
            
            now = datetime.utcnow()
            otp_value = generate_numeric_otp(current_app.config.get('OTP_LENGTH', 6))
            _set_login_2fa_state({
                'user_id': user.id,
                'otp_hash': hash_otp(otp_value),
                'expires_at': (now + timedelta(seconds=current_app.config.get('OTP_EXPIRY_SECONDS', 600))).isoformat(),
                'attempts_left': current_app.config.get('OTP_MAX_ATTEMPTS', 5),
                'resend_after': (now + timedelta(seconds=current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 60))).isoformat(),
                'consumed_at': None,
            })
            
            sent = _send_login_2fa_otp(user, otp_value)
            if not sent:
                flash('OTP was generated but email delivery failed. Check SMTP settings or server logs.', 'warning')
            
            flash('Please verify your login with the OTP sent to your email.', 'info')
            return redirect(url_for('auth.verify_login_2fa'))
        else:
            flash('Login Unsuccessful. Please check email and password', 'danger')
    return render_template('login.html', title='Login', form=form)


@auth.route('/doctor/login', methods=['GET', 'POST'])
def doctor_login():
    if current_user.is_authenticated:
        return redirect(_redirect_for_role(current_user))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            if user.role != 'doctor':
                flash('This account is not a doctor account.', 'danger')
                return redirect(url_for('auth.login'))
            if user.doctor_verification_status != 'approved':
                flash('Doctor account is pending admin approval. You can log in after approval.', 'warning')
                return redirect(url_for('auth.doctor_login'))

            # Initiate 2FA for doctor
            _clear_login_2fa_state()
            session['login_2fa_user_id'] = user.id
            session['login_2fa_next'] = request.args.get('next')
            
            now = datetime.utcnow()
            otp_value = generate_numeric_otp(current_app.config.get('OTP_LENGTH', 6))
            _set_login_2fa_state({
                'user_id': user.id,
                'otp_hash': hash_otp(otp_value),
                'expires_at': (now + timedelta(seconds=current_app.config.get('OTP_EXPIRY_SECONDS', 600))).isoformat(),
                'attempts_left': current_app.config.get('OTP_MAX_ATTEMPTS', 5),
                'resend_after': (now + timedelta(seconds=current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 60))).isoformat(),
                'consumed_at': None,
            })
            
            sent = _send_login_2fa_otp(user, otp_value)
            if not sent:
                flash('OTP was generated but email delivery failed. Check SMTP settings or server logs.', 'warning')
            
            flash('Please verify your login with the OTP sent to your email.', 'info')
            return redirect(url_for('auth.verify_login_2fa'))
        flash('Login Unsuccessful. Please check email and password', 'danger')
    return render_template('doctor_login.html', title='Doctor Login', form=form)


@auth.route('/login/verify-2fa', methods=['GET', 'POST'])
@limiter.limit(LOGIN_LIMIT)
def verify_login_2fa():
    if current_user.is_authenticated:
        return redirect(_redirect_for_role(current_user))

    user_id = session.get('login_2fa_user_id')
    if not user_id:
        flash('Please log in first.', 'warning')
        return redirect(url_for('auth.login'))

    user = User.query.get(user_id)
    if not user:
        _clear_login_2fa_state()
        flash('Invalid login state. Please try again.', 'danger')
        return redirect(url_for('auth.login'))

    form = VerifyOtpForm()
    resend_form = ResendOtpForm()
    if form.validate_on_submit():
        now = datetime.utcnow()
        otp_record = _get_login_2fa_state()
        expires_at = otp_record.get('expires_at')
        
        if not otp_record or otp_record.get('user_id') != user.id or otp_record.get('consumed_at') is not None or not expires_at or datetime.fromisoformat(expires_at) < now:
            _clear_login_2fa_state()
            flash('OTP is invalid or expired. Please log in again.', 'danger')
            return redirect(url_for(f"auth.{'doctor_login' if user.role == 'doctor' else 'login'}"))

        attempts_left = int(otp_record.get('attempts_left', 0))
        if attempts_left <= 0:
            _clear_login_2fa_state()
            flash('Maximum OTP attempts exceeded. Please log in again.', 'danger')
            return redirect(url_for(f"auth.{'doctor_login' if user.role == 'doctor' else 'login'}"))

        if verify_otp_hash(otp_record.get('otp_hash', ''), form.otp.data.strip()):
            otp_record['consumed_at'] = now.isoformat()
            _set_login_2fa_state(otp_record)
            
            next_page = session.get('login_2fa_next')
            
            login_user(user)
            if user.role == 'patient' and not medical_info_complete(user):
                flash('Please complete your medical information in Profile to enable ECG report download.', 'warning')
            
            _clear_login_2fa_state()
            
            return redirect(next_page) if next_page else redirect(_redirect_for_role(user))

        otp_record['attempts_left'] = attempts_left - 1
        _set_login_2fa_state(otp_record)

        if otp_record['attempts_left'] <= 0:
            _clear_login_2fa_state()
            flash('Maximum OTP attempts exceeded. Please log in again.', 'danger')
            return redirect(url_for(f"auth.{'doctor_login' if user.role == 'doctor' else 'login'}"))

        flash(f'Invalid OTP. Attempts remaining: {otp_record["attempts_left"]}', 'warning')

    return render_template('verify_login_2fa.html', title='Verify Login', form=form, resend_form=resend_form, email=user.email)


@auth.route('/login/resend-2fa', methods=['POST'])
@limiter.limit(LOGIN_LIMIT)
def resend_login_2fa():
    if current_user.is_authenticated:
        return redirect(_redirect_for_role(current_user))

    resend_form = ResendOtpForm()
    if not resend_form.validate_on_submit():
        flash('Invalid request. Please refresh and try again.', 'danger')
        return redirect(url_for('auth.verify_login_2fa'))

    user_id = session.get('login_2fa_user_id')
    if not user_id:
        flash('Session expired. Please log in again.', 'warning')
        return redirect(url_for('auth.login'))

    user = User.query.get(user_id)
    now = datetime.utcnow()

    if user:
        otp_record = _get_login_2fa_state()
        resend_after = otp_record.get('resend_after')
        if otp_record and otp_record.get('user_id') == user.id and resend_after and now < datetime.fromisoformat(resend_after):
            wait_seconds = int((datetime.fromisoformat(resend_after) - now).total_seconds())
            flash(f'Please wait {wait_seconds} seconds before resending OTP.', 'warning')
            return redirect(url_for('auth.verify_login_2fa'))

        otp_value = generate_numeric_otp(current_app.config.get('OTP_LENGTH', 6))
        _set_login_2fa_state({
            'user_id': user.id,
            'otp_hash': hash_otp(otp_value),
            'expires_at': (now + timedelta(seconds=current_app.config.get('OTP_EXPIRY_SECONDS', 600))).isoformat(),
            'attempts_left': current_app.config.get('OTP_MAX_ATTEMPTS', 5),
            'resend_after': (now + timedelta(seconds=current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 60))).isoformat(),
            'consumed_at': None,
        })

        sent = _send_login_2fa_otp(user, otp_value)
        if not sent:
            flash('OTP was regenerated but email delivery failed. Check SMTP settings or server logs.', 'warning')

    flash('If the account exists, a new OTP has been sent.', 'info')
    return redirect(url_for('auth.verify_login_2fa'))


@auth.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit(LOGIN_LIMIT)
def forgot_password():
    if current_user.is_authenticated:
        return redirect(_redirect_for_role(current_user))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = (form.email.data or '').strip().lower()
        _clear_password_reset_state()
        session.pop('password_reset_verified_user_id', None)
        session['password_reset_email'] = email

        user = _find_reset_user(email)
        if user:
            now = datetime.utcnow()
            otp_record = _get_password_reset_state()

            can_send = True
            resend_after = otp_record.get('resend_after')
            if resend_after and now < datetime.fromisoformat(resend_after):
                can_send = False

            if can_send:
                otp_value = generate_numeric_otp(current_app.config.get('OTP_LENGTH', 6))
                _set_password_reset_state({
                    'user_id': user.id,
                    'otp_hash': hash_otp(otp_value),
                    'expires_at': (now + timedelta(seconds=current_app.config.get('OTP_EXPIRY_SECONDS', 600))).isoformat(),
                    'attempts_left': current_app.config.get('OTP_MAX_ATTEMPTS', 5),
                    'resend_after': (now + timedelta(seconds=current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 60))).isoformat(),
                    'consumed_at': None,
                })

                sent = _send_password_reset_otp(user, otp_value)
                if not sent:
                    flash('OTP was generated but email delivery failed. Check SMTP settings or server logs.', 'warning')

        flash('If the account exists, an OTP has been sent to the email address.', 'info')
        return redirect(url_for('auth.verify_otp'))

    return render_template('forgot_password.html', title='Forgot Password', form=form)


@auth.route('/forgot-password/verify', methods=['GET', 'POST'])
@limiter.limit(LOGIN_LIMIT)
def verify_otp():
    if current_user.is_authenticated:
        return redirect(_redirect_for_role(current_user))

    email = session.get('password_reset_email')
    if not email:
        flash('Please request an OTP first.', 'warning')
        return redirect(url_for('auth.forgot_password'))

    form = VerifyOtpForm()
    resend_form = ResendOtpForm()
    if form.validate_on_submit():
        user = _find_reset_user(email)
        if not user:
            flash('Invalid or expired OTP. Please request a new OTP.', 'danger')
            return redirect(url_for('auth.forgot_password'))

        now = datetime.utcnow()
        otp_record = _get_password_reset_state()
        expires_at = otp_record.get('expires_at')
        if not otp_record or otp_record.get('user_id') != user.id or otp_record.get('consumed_at') is not None or not expires_at or datetime.fromisoformat(expires_at) < now:
            flash('OTP is invalid or expired. Please request a new OTP.', 'danger')
            return redirect(url_for('auth.forgot_password'))

        attempts_left = int(otp_record.get('attempts_left', 0))
        if attempts_left <= 0:
            flash('Maximum OTP attempts exceeded. Request a new OTP.', 'danger')
            return redirect(url_for('auth.forgot_password'))

        if verify_otp_hash(otp_record.get('otp_hash', ''), form.otp.data.strip()):
            otp_record['consumed_at'] = now.isoformat()
            _set_password_reset_state(otp_record)
            session.pop('password_reset_email', None)
            session['password_reset_verified_user_id'] = user.id
            flash('OTP verified. Set your new password.', 'success')
            return redirect(url_for('auth.reset_password_otp'))

        otp_record['attempts_left'] = attempts_left - 1
        _set_password_reset_state(otp_record)

        if otp_record['attempts_left'] <= 0:
            flash('Maximum OTP attempts exceeded. Request a new OTP.', 'danger')
            return redirect(url_for('auth.forgot_password'))

        flash(f'Invalid OTP. Attempts remaining: {otp_record["attempts_left"]}', 'warning')

    return render_template('verify_otp.html', title='Verify OTP', form=form, resend_form=resend_form, email=email)


@auth.route('/forgot-password/resend', methods=['POST'])
@limiter.limit(LOGIN_LIMIT)
def resend_otp():
    if current_user.is_authenticated:
        return redirect(_redirect_for_role(current_user))

    resend_form = ResendOtpForm()
    if not resend_form.validate_on_submit():
        flash('Invalid session token. Please refresh and try again.', 'danger')
        return redirect(url_for('auth.verify_otp'))

    email = session.get('password_reset_email')
    if not email:
        flash('Session expired. Please request a new OTP.', 'warning')
        return redirect(url_for('auth.forgot_password'))

    user = _find_reset_user(email)
    now = datetime.utcnow()

    if user:
        otp_record = _get_password_reset_state()
        resend_after = otp_record.get('resend_after')
        if otp_record and otp_record.get('user_id') == user.id and resend_after and now < datetime.fromisoformat(resend_after):
            wait_seconds = int((datetime.fromisoformat(resend_after) - now).total_seconds())
            flash(f'Please wait {wait_seconds} seconds before resending OTP.', 'warning')
            return redirect(url_for('auth.verify_otp'))

        otp_value = generate_numeric_otp(current_app.config.get('OTP_LENGTH', 6))
        _set_password_reset_state({
            'user_id': user.id,
            'otp_hash': hash_otp(otp_value),
            'expires_at': (now + timedelta(seconds=current_app.config.get('OTP_EXPIRY_SECONDS', 600))).isoformat(),
            'attempts_left': current_app.config.get('OTP_MAX_ATTEMPTS', 5),
            'resend_after': (now + timedelta(seconds=current_app.config.get('OTP_RESEND_COOLDOWN_SECONDS', 60))).isoformat(),
            'consumed_at': None,
        })

        sent = _send_password_reset_otp(user, otp_value)
        if not sent:
            flash('OTP was regenerated but email delivery failed. Check SMTP settings or server logs.', 'warning')

    flash('If the account exists, a new OTP has been sent.', 'info')
    return redirect(url_for('auth.verify_otp'))


@auth.route('/forgot-password/reset', methods=['GET', 'POST'])
def reset_password_otp():
    if current_user.is_authenticated:
        return redirect(_redirect_for_role(current_user))

    user_id = session.get('password_reset_verified_user_id')
    if not user_id:
        flash('Please verify OTP first.', 'warning')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.get(user_id)
    if not user or user.role not in ('patient', 'doctor'):
        session.pop('password_reset_verified_user_id', None)
        flash('Password reset session is invalid. Please try again.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.password_hash = generate_password_hash(form.password.data)
        _clear_password_reset_state()
        session.pop('password_reset_verified_user_id', None)
        session.pop('password_reset_email', None)

        flash('Your password has been reset. You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', title='Reset Password', form=form)

@auth.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))
