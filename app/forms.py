from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, BooleanField, IntegerField, SelectField, TextAreaField, DateTimeLocalField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError, Optional, NumberRange, Regexp
from flask_login import current_user
from app.models import User

class RegistrationForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8, message='Password must be at least 8 characters long.')])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is taken. Please choose a different one.')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class UpdateAccountForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('New Password (Optional)', validators=[Length(min=8, message='Password must be at least 8 characters long.')])
    confirm_password = PasswordField('Confirm New Password', validators=[EqualTo('password')])
    submit = SubmitField('Update')


class MedicalInfoForm(FlaskForm):
    phone_number = StringField(
        'Phone Number',
        validators=[
            DataRequired(),
            Regexp(r'^\d{11}$', message='Phone number must contain exactly 11 digits.'),
        ],
    )
    age = IntegerField('Age', validators=[DataRequired(), NumberRange(min=0, max=120)])
    gender = SelectField(
        'Gender',
        choices=[('', 'Select Gender'), ('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other'), ('Prefer not to say', 'Prefer not to say')],
        validators=[DataRequired()]
    )
    blood_group = SelectField(
        'Blood Group',
        choices=[('', 'Select Blood Group'), ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'), ('AB+', 'AB+'), ('AB-', 'AB-'), ('O+', 'O+'), ('O-', 'O-')],
        validators=[DataRequired()]
    )
    blood_pressure = StringField('Blood Pressure', validators=[DataRequired(), Length(max=30)])
    
    # New Health Metrics
    weight = StringField('Weight (kg)', validators=[Optional()])
    height = StringField('Height (cm)', validators=[Optional()])
    
    # Emergency Contact
    emergency_contact_name = StringField('Emergency Contact Name', validators=[Optional(), Length(max=100)])
    emergency_contact_phone = StringField('Emergency Contact Phone', validators=[
        Optional(), 
        Regexp(r'^\d{11}$', message='Emergency phone must contain exactly 11 digits.')
    ])
    
    # Heart History fields (we will process this as a string from multiple checkboxes if needed, or handle in template)
    # Actually, WTForms SelectMultipleField can be used, but since we are doing some manual stuff, let's add a few hidden/boolean fields or just a string field
    heart_conditions = StringField('Heart Conditions', validators=[Optional(), Length(max=500)])
    
    allergy = TextAreaField('Other Allergies / Conditions', validators=[Optional(), Length(max=200)])
    diabetes = BooleanField('I have diabetes')
    submit = SubmitField('Update')

    def validate_email(self, email):
        if email.data != current_user.email:
            user = User.query.filter_by(email=email.data).first()
            if user:
                raise ValidationError('That email is taken. Please choose a different one.')

class UploadForm(FlaskForm):
    picture = FileField('Upload ECG Image', validators=[DataRequired(), FileAllowed(['jpg', 'png', 'jpeg'])])
    submit = SubmitField('Analyze')


class DoctorRegistrationForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=100)])
    designation = StringField('Designation', validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8, message='Password must be at least 8 characters long.')])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Doctor Sign Up')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is taken. Please choose a different one.')


class AvailabilityForm(FlaskForm):
    start_time = DateTimeLocalField('Start Time', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    end_time = DateTimeLocalField('End Time', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    duration = SelectField(
        'Slot Duration',
        choices=[('15', '15 Minutes'), ('30', '30 Minutes'), ('45', '45 Minutes'), ('60', '60 Minutes')],
        default='30',
        validators=[DataRequired()]
    )
    submit = SubmitField('Add Free Slot')


class AppointmentRequestForm(FlaskForm):
    reason = TextAreaField('Reason (Optional)', validators=[Optional(), Length(max=500)])
    submit = SubmitField('Request Appointment')


class PrescriptionForm(FlaskForm):
    content = TextAreaField('Prescription', validators=[DataRequired(), Length(min=5, max=5000)])
    submit = SubmitField('Save Prescription')


class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send OTP')


class VerifyOtpForm(FlaskForm):
    otp = StringField(
        'OTP',
        validators=[
            DataRequired(),
            Regexp(r'^\d{6}$', message='Enter a valid 6-digit OTP.'),
        ],
    )
    submit = SubmitField('Verify OTP')


class ResendOtpForm(FlaskForm):
    submit = SubmitField('Resend OTP')


class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        'New Password',
        validators=[DataRequired(), Length(min=8, message='Password must be at least 8 characters long.')],
    )
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')
