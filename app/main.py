import os
from datetime import datetime, timedelta
from io import BytesIO
from flask import Blueprint, render_template, url_for, flash, redirect, request, current_app, jsonify, render_template_string
from flask import send_file
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from app import db
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from app.models import Prediction, UserMedicalInfo, AuditLog, User, AvailabilitySlot, Appointment, Prescription
from app.utils import roles_required, admin_required
from app.forms import UploadForm, UpdateAccountForm, MedicalInfoForm, AvailabilityForm, AppointmentRequestForm, PrescriptionForm
from app.utils import save_picture
from app.ai import predict_image
from app.hospitals import HOSPITALS
from app.chatbot import ChatBot
from app.email import send_appointment_approved, send_appointment_rejected

main = Blueprint('main', __name__)


def role_home_endpoint(user):
    role = getattr(user, 'role', 'patient') if user else 'patient'
    if role == 'admin':
        return 'main.admin_analytics'
    if role == 'doctor':
        if getattr(user, 'doctor_verification_status', '') != 'approved':
            return 'auth.doctor_login'
        return 'main.doctor_dashboard'
    return 'main.dashboard'


@main.app_context_processor
def inject_doctor_notification_count():
    count = 0
    if current_user.is_authenticated and getattr(current_user, 'role', '') == 'doctor' and getattr(current_user, 'doctor_verification_status', '') == 'approved':
        count = Appointment.query.filter_by(doctor_id=current_user.id, status='pending').count()
    return {'doctor_notification_count': count}

@main.route("/get_hospitals/<city_name>")
def get_hospitals(city_name):
    hospitals = HOSPITALS.get(city_name, [])
    return jsonify(hospitals)

bot = ChatBot()


def medical_info_complete(user):
    medical_info = getattr(user, 'medical_info', None)
    if not medical_info:
        return False
    required_fields = [
        medical_info.phone_number,
        medical_info.age,
        medical_info.gender,
        medical_info.blood_group,
        medical_info.blood_pressure,
        medical_info.allergy,
    ]
    return all(value not in (None, '') for value in required_fields)

@main.route("/")

@main.route("/home")
def index():
    if current_user.is_authenticated:
        return redirect(url_for(role_home_endpoint(current_user)))
    return render_template('index.html')

@main.route("/chat", methods=['POST'])
@login_required
def chat():
    data = request.get_json()
    user_message = data.get('message', '')
    response = bot.get_response(user_message, current_user=current_user)
    return jsonify({'response': response})

@main.route("/medical-info", methods=['GET', 'POST'])
@login_required
def medical_info():
    form = MedicalInfoForm()
    medical_info = current_user.medical_info or UserMedicalInfo(user=current_user)

    if form.validate_on_submit():
        medical_info.age = form.age.data
        medical_info.gender = form.gender.data or None
        medical_info.blood_group = form.blood_group.data or None
        medical_info.phone_number = form.phone_number.data
        medical_info.blood_pressure = form.blood_pressure.data or None
        
        # New Medical Details
        try:
            medical_info.weight = float(form.weight.data) if form.weight.data else None
            medical_info.height = float(form.height.data) if form.height.data else None
        except ValueError:
            pass
            
        medical_info.emergency_contact_name = form.emergency_contact_name.data or None
        medical_info.emergency_contact_phone = form.emergency_contact_phone.data or None
        
        # In the route we will catch the list of checkboxes array for 'heart_conditions' and join by comma
        heart_conds = request.form.getlist('heart_conditions_list')
        if heart_conds:
            medical_info.heart_conditions = ", ".join(heart_conds)
        else:
            medical_info.heart_conditions = None

        medical_info.allergy = form.allergy.data or None
        medical_info.diabetes = form.diabetes.data
        medical_info.user = current_user
        db.session.add(medical_info)
        db.session.commit()
        flash('Your medical information has been updated!', 'success')
        return redirect(url_for('main.medical_info'))
    elif request.method == 'GET':
        form.phone_number.data = medical_info.phone_number
        form.age.data = medical_info.age
        form.gender.data = medical_info.gender
        form.blood_group.data = medical_info.blood_group
        form.blood_pressure.data = medical_info.blood_pressure
        
        form.weight.data = str(medical_info.weight) if medical_info.weight else ""
        form.height.data = str(medical_info.height) if medical_info.height else ""
        form.emergency_contact_name.data = medical_info.emergency_contact_name
        form.emergency_contact_phone.data = medical_info.emergency_contact_phone
        
        form.allergy.data = medical_info.allergy
        form.diabetes.data = medical_info.diabetes

    return render_template('medical_info.html', title='Medical Information', form=form, medical_complete=medical_info_complete(current_user))


@main.route("/medical-help")
@login_required
def medical_help():
    return render_template('medical_help.html', title='Find Medical Help Nearby')

@main.route("/dashboard", methods=['GET', 'POST'])
@login_required
def dashboard():
    current_role = getattr(current_user, 'role', 'patient')
    if current_role == 'admin':
        flash('Admin accounts use the admin panel.', 'info')
        return redirect(url_for('main.admin_analytics'))
    if current_role == 'doctor':
        return redirect(url_for('main.doctor_dashboard'))

    form = UploadForm()
    if form.validate_on_submit():
        if form.picture.data:
            picture_file = save_picture(form.picture.data)
            
            # Full path for AI model
            full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], picture_file)
            
            # Run inference
            result, confidence, metadata = predict_image(full_path)
            
            # Save to Database
            prediction = Prediction(
                image_path=picture_file, 
                result=result, 
                confidence=confidence, 
                author=current_user
            )
            db.session.add(prediction)
            db.session.commit()

            # Audit: prediction creation
            try:
                audit = AuditLog(
                    user_id=current_user.id,
                    action='prediction.create',
                    resource_type='prediction',
                    resource_id=prediction.id,
                    details={
                        'result': result,
                        'confidence': float(confidence) if confidence is not None else None,
                        'method': metadata.get('method'),
                        'class_name': metadata.get('class_name'),
                        'processing_time_ms': metadata.get('processing_time_ms')
                    }
                )
                db.session.add(audit)
                db.session.commit()
            except Exception:
                db.session.rollback()

            flash('Image analyzed successfully!', 'success')
            return redirect(url_for('main.result', prediction_id=prediction.id))
            
    page = request.args.get('page', 1, type=int)
    # Get user history
    history = Prediction.query.options(
        joinedload(Prediction.author)
    ).filter_by(user_id=current_user.id).order_by(Prediction.timestamp.desc()).paginate(page=page, per_page=5, error_out=False)
    
    return render_template('dashboard.html', title='Dashboard', form=form, history=history, medical_complete=medical_info_complete(current_user))

@main.route("/result/<int:prediction_id>")
@login_required
def result(prediction_id):
    prediction = Prediction.query.get_or_404(prediction_id)
    viewer_role = getattr(current_user, 'role', '')

    # Allow owner, admins, and verified doctors for other users' results.
    if prediction.author != current_user:
        if viewer_role == 'doctor' and not getattr(current_user, 'is_verified_doctor', lambda: False)():
            flash('Doctor account is not verified yet. Contact admin.', 'warning')
            return redirect(url_for(role_home_endpoint(current_user)))
        if viewer_role not in ('doctor', 'admin'):
            flash('You cannot view this result.', 'danger')
            return redirect(url_for(role_home_endpoint(current_user)))

    # Audit: view
    try:
        audit = AuditLog(
            user_id=current_user.id,
            action='prediction.view',
            resource_type='prediction',
            resource_id=prediction.id,
            details={'viewer_role': getattr(current_user, 'role', None)}
        )
        db.session.add(audit)
        db.session.commit()
    except Exception:
        db.session.rollback()
    return render_template('result.html', title='Analysis Result', prediction=prediction, medical_complete=medical_info_complete(current_user))


@main.route("/report/<int:prediction_id>")
@login_required
def download_report(prediction_id):
    prediction = Prediction.query.get_or_404(prediction_id)
    requester_role = getattr(current_user, 'role', '')

    # Allow owner, admins, and verified doctors for other users' reports.
    if prediction.author != current_user:
        if requester_role == 'doctor' and not getattr(current_user, 'is_verified_doctor', lambda: False)():
            flash('Doctor account is not verified yet. Contact admin.', 'warning')
            return redirect(url_for(role_home_endpoint(current_user)))
        if requester_role not in ('doctor', 'admin'):
            flash('You cannot download this report.', 'danger')
            return redirect(url_for(role_home_endpoint(current_user)))

    report_owner = prediction.author
    medical_info = report_owner.medical_info if report_owner else None
    # If the requester is the owner, ensure their medical info is complete
    if prediction.author == current_user and not medical_info_complete(current_user):
        flash('Please complete your medical information in Profile before downloading the report.', 'warning')
        return redirect(url_for('main.profile'))

    report_buffer = BytesIO()
    document = SimpleDocTemplate(
        report_buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title='ECG Report'
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CenterTitle', parent=styles['Title'], alignment=1, textColor=colors.HexColor('#1f4e79')))
    styles.add(ParagraphStyle(name='Section', parent=styles['Heading2'], textColor=colors.HexColor('#1f4e79')))
    # Header/footer drawing
    def _draw_header_footer(canvas, doc):
        canvas.saveState()
        width, height = A4
        header_y = height - 18 * mm + 6
        # Header background line
        canvas.setFillColor(colors.HexColor('#1f4e79'))
        canvas.setFont('Helvetica-Bold', 12)
        canvas.drawString(18 * mm, header_y, 'HeartAnomaly AI')
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.black)
        canvas.drawRightString(width - 18 * mm, header_y, datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))

        # Footer small text
        footer_y = 12 * mm
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#6c757d'))
        canvas.drawCentredString(width / 2.0, footer_y, 'This report is for informational purposes only. Not a medical diagnosis.')
        canvas.restoreState()

    def clean(value, fallback='Not provided'):
        if value is None or value == '':
            return fallback
        return str(value)

    story = []
    story.append(Paragraph('HeartAnomaly AI', styles['CenterTitle']))
    story.append(Paragraph('Downloadable ECG Patient Report', styles['Heading3']))
    story.append(Spacer(1, 8))

    summary_data = [
        ['Patient Name', clean(getattr(report_owner, 'name', None))],
        ['Phone Number', clean(getattr(medical_info, 'phone_number', None))],
        ['Email', clean(getattr(report_owner, 'email', None))],
        ['Age', clean(getattr(medical_info, 'age', None))],
        ['Gender', clean(getattr(medical_info, 'gender', None))],
        ['Blood Group', clean(getattr(medical_info, 'blood_group', None))],
        ['Blood Pressure', clean(getattr(medical_info, 'blood_pressure', None))],
        ['Allergy', clean(getattr(medical_info, 'allergy', None))],
        ['Diabetes', 'Yes' if getattr(medical_info, 'diabetes', False) else 'No'],
        ['Report Date', prediction.timestamp.strftime('%Y-%m-%d %H:%M')],
    ]

    summary_table = Table(summary_data, colWidths=[55 * mm, 110 * mm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#eaf2f8')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#c7d5e0')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#f7fbfe')]),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph('ECG Report', styles['Section']))
    result_color = '#1f8b4c' if prediction.result == 'Normal' else '#c0392b'
    story.append(Paragraph(f"<b>Status:</b> <font color='{result_color}'>{prediction.result}</font>", styles['BodyText']))
    story.append(Paragraph(f"<b>Confidence:</b> {(prediction.confidence * 100):.2f}%", styles['BodyText']))
    story.append(Spacer(1, 6))

    image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], prediction.image_path)
    if os.path.exists(image_path):
        story.append(Paragraph('Uploaded ECG Image', styles['Section']))
        story.append(RLImage(image_path, width=120 * mm, height=67 * mm))
        story.append(Spacer(1, 8))

    story.append(Paragraph('ECG Risk Timeline', styles['Section']))
    timeline_rows = [['No.', 'Date', 'Result', 'Confidence']]
    recent_predictions = Prediction.query.options(
        joinedload(Prediction.author)
    ).filter_by(user_id=prediction.user_id).order_by(Prediction.timestamp.desc()).limit(5).all()
    for index, item in enumerate(recent_predictions, start=1):
        timeline_rows.append([
            str(index),
            item.timestamp.strftime('%Y-%m-%d %H:%M'),
            item.result,
            f"{(item.confidence * 100):.2f}%"
        ])

    timeline_table = Table(timeline_rows, colWidths=[15 * mm, 50 * mm, 45 * mm, 35 * mm])
    timeline_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4e79')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#c7d5e0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7fbfe')]),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(timeline_table)
    story.append(Spacer(1, 10))
    story.append(Paragraph('Disclaimer: This report is generated by an AI model for research purposes only and is not a medical diagnosis.', styles['BodyText']))

    document.build(story, onFirstPage=_draw_header_footer, onLaterPages=_draw_header_footer)
    report_buffer.seek(0)

    # Audit: report download
    try:
        audit = AuditLog(
            user_id=current_user.id,
            action='report.download',
            resource_type='prediction',
            resource_id=prediction.id,
            details={'requested_for_user': prediction.user_id}
        )
        db.session.add(audit)
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Use the target patient's name when author is not the requester
    target_user = prediction.author
    safe_user_name = secure_filename(target_user.name) if target_user else f"user_{prediction.user_id}"

    return send_file(
        report_buffer,
        as_attachment=True,
        download_name=f'{safe_user_name}_ecg_report_{prediction.id}.pdf',
        mimetype='application/pdf'
    )


@main.route("/report/<int:prediction_id>/preview")
@login_required
def preview_report(prediction_id):
    """Preview ECG report as inline PDF in browser."""
    prediction = Prediction.query.get_or_404(prediction_id)
    requester_role = getattr(current_user, 'role', '')

    # Allow owner, admins, and verified doctors for other users' reports.
    if prediction.author != current_user:
        if requester_role == 'doctor' and not getattr(current_user, 'is_verified_doctor', lambda: False)():
            flash('Doctor account is not verified yet. Contact admin.', 'warning')
            return redirect(url_for(role_home_endpoint(current_user)))
        if requester_role not in ('doctor', 'admin'):
            flash('You cannot preview this report.', 'danger')
            return redirect(url_for(role_home_endpoint(current_user)))

    report_owner = prediction.author
    medical_info = report_owner.medical_info if report_owner else None
    # If the requester is the owner, ensure their medical info is complete
    if prediction.author == current_user and not medical_info_complete(current_user):
        flash('Please complete your medical information in Profile before previewing the report.', 'warning')
        return redirect(url_for('main.profile'))

    report_buffer = BytesIO()
    document = SimpleDocTemplate(
        report_buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title='ECG Report'
    )
    story = []
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ReportHeading', parent=styles['Heading2'], fontSize=13, textColor=colors.HexColor('#1f4e79'), spaceAfter=10))
    styles.add(ParagraphStyle(name='ReportSection', parent=styles['Heading3'], fontSize=12, textColor=colors.HexColor('#1f4e79'), spaceAfter=8, spaceBefore=8))

    # Header/footer drawing
    def _draw_header_footer(canvas, doc):
        canvas.saveState()
        width, height = A4
        header_y = height - 18 * mm + 6
        # Header background line
        canvas.setFillColor(colors.HexColor('#1f4e79'))
        canvas.setFont('Helvetica-Bold', 12)
        canvas.drawString(18 * mm, header_y, 'HeartAnomaly AI')
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.black)
        canvas.drawRightString(width - 18 * mm, header_y, datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))

        # Footer small text
        footer_y = 12 * mm
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#6c757d'))
        canvas.drawCentredString(width / 2.0, footer_y, 'This report is for informational purposes only. Not a medical diagnosis.')
        canvas.restoreState()

    story.append(Paragraph('Downloadable ECG Patient Report', styles['ReportHeading']))
    story.append(Spacer(1, 10))

    patient_info_rows = [
        ['Patient Name', report_owner.name if report_owner else 'N/A'],
        ['Patient Email', report_owner.email if report_owner else 'N/A'],
        ['Report Generated', prediction.timestamp.strftime('%Y-%m-%d %H:%M:%S')],
        ['Age', f"{medical_info.age if medical_info and medical_info.age else 'N/A'}"],
        ['Gender', f"{medical_info.gender if medical_info and medical_info.gender else 'N/A'}"],
    ]
    patient_info_table = Table(patient_info_rows, colWidths=[120 * mm, 60 * mm])
    patient_info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e8f1f7')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#c7d5e0')),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(patient_info_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph('ECG Report', styles['ReportSection']))
    result_color = '#1f8b4c' if prediction.result == 'Normal' else '#c0392b'
    story.append(Paragraph(f"<b>Status:</b> <font color='{result_color}'>{prediction.result}</font>", styles['BodyText']))
    story.append(Paragraph(f"<b>Confidence:</b> {(prediction.confidence * 100):.2f}%", styles['BodyText']))
    story.append(Spacer(1, 6))

    image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], prediction.image_path)
    if os.path.exists(image_path):
        story.append(Paragraph('Uploaded ECG Image', styles['ReportSection']))
        story.append(RLImage(image_path, width=120 * mm, height=67 * mm))
        story.append(Spacer(1, 8))

    # PREVIEW MODE: Skip timeline for faster loading
    story.append(Paragraph('Disclaimer: This report is generated by an AI model for research purposes only and is not a medical diagnosis.', styles['BodyText']))

    # Build the document and handle generation errors gracefully so the iframe doesn't hang
    try:
        document.build(story, onFirstPage=_draw_header_footer, onLaterPages=_draw_header_footer)
        report_buffer.seek(0)
    except Exception as e:
        current_app.logger.exception('Failed to generate preview PDF for prediction_id=%s', prediction_id)
        error_html = render_template_string(
            '<html><body style="font-family:Inter, Arial, sans-serif;padding:24px;">'
            '<h3>Preview unavailable</h3>'
            '<p>Unable to generate the preview right now. You can download the full report instead.</p>'
            '<p style="color:#666;font-size:0.9rem;"><small>Error: {{ err }}</small></p>'
            '</body></html>', err=str(e)
        )
        return current_app.response_class(error_html, mimetype='text/html', status=500)

    # Audit: report preview
    try:
        audit = AuditLog(
            user_id=current_user.id,
            action='report.preview',
            resource_type='prediction',
            resource_id=prediction.id,
            details={'requested_for_user': prediction.user_id}
        )
        db.session.add(audit)
        db.session.commit()
    except Exception:
        db.session.rollback()

    response = send_file(
        report_buffer,
        as_attachment=False,
        mimetype='application/pdf'
    )
    # Cache preview for 30 minutes to improve performance
    response.headers['Cache-Control'] = 'public, max-age=1800'
    return response


@main.route('/appointments', methods=['GET', 'POST'])
@roles_required('patient')
def appointments():
    form = AppointmentRequestForm()

    if request.method == 'POST':
        slot_id = request.form.get('slot_id')
        slot = AvailabilitySlot.query.filter_by(id=slot_id, is_booked=False).first()
        if not slot:
            flash('Selected slot is no longer available.', 'warning')
            return redirect(url_for('main.appointments'))

        doctor = User.query.filter_by(id=slot.doctor_id, role='doctor').first()
        if not doctor or doctor.doctor_verification_status != 'approved':
            flash('Doctor is not available for appointment booking.', 'danger')
            return redirect(url_for('main.appointments'))

        reason = (request.form.get('reason') or '').strip()
        appointment = Appointment(
            patient_id=current_user.id,
            doctor_id=slot.doctor_id,
            slot_id=slot.id,
            status='pending',
            reason=reason or None,
        )
        slot.is_booked = True

        try:
            db.session.add(appointment)
            db.session.commit()
            try:
                db.session.add(AuditLog(
                    user_id=current_user.id,
                    action='appointment.request',
                    resource_type='appointment',
                    resource_id=appointment.id,
                    details={'doctor_id': slot.doctor_id, 'slot_id': slot.id}
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()
            flash('Appointment requested successfully.', 'success')
        except Exception:
            db.session.rollback()
            flash('Could not request appointment.', 'danger')
        return redirect(url_for('main.appointments'))

    available_slots = AvailabilitySlot.query.join(User, AvailabilitySlot.doctor_id == User.id).filter(
        User.role == 'doctor',
        User.doctor_verification_status == 'approved',
        AvailabilitySlot.is_booked == False,
        AvailabilitySlot.start_time >= datetime.utcnow(),
    ).order_by(AvailabilitySlot.start_time.asc()).all()

    available_slots_by_doctor = {}
    available_slots_by_doctor_obj = {}
    for slot in available_slots:
        available_slots_by_doctor.setdefault(slot.doctor_id, []).append(slot)
        if slot.doctor not in available_slots_by_doctor_obj:
            available_slots_by_doctor_obj[slot.doctor] = []
        available_slots_by_doctor_obj[slot.doctor].append(slot)

    my_appointments = Appointment.query.filter_by(patient_id=current_user.id).order_by(Appointment.created_at.desc()).all()
    return render_template(
        'appointments.html',
        title='Appointments',
        form=form,
        available_slots=available_slots,
        available_slots_by_doctor=available_slots_by_doctor,
        available_slots_by_doctor_obj=available_slots_by_doctor_obj,
        my_appointments=my_appointments,
    )


@main.route('/doctor/dashboard')
@roles_required('doctor')
def doctor_dashboard():
    if current_user.doctor_verification_status != 'approved':
        flash('Doctor account is pending admin approval.', 'warning')
        return redirect(url_for('auth.doctor_login'))

    pending = Appointment.query.options(
        joinedload(Appointment.patient), joinedload(Appointment.slot)
    ).filter_by(doctor_id=current_user.id, status='pending').order_by(Appointment.created_at.asc()).all()
    approved = Appointment.query.options(
        joinedload(Appointment.patient), joinedload(Appointment.slot)
    ).filter_by(doctor_id=current_user.id, status='Accepted').order_by(Appointment.created_at.desc()).all()
    return render_template('doctor_dashboard.html', title='Doctor Dashboard', pending_verification=False, pending=pending, approved=approved)


@main.route('/doctor/availability', methods=['GET', 'POST'])
@roles_required('doctor')
def doctor_availability():
    form = AvailabilityForm()

    if current_user.doctor_verification_status != 'approved':
        flash('Doctor account is pending admin approval.', 'warning')
        return redirect(url_for('auth.doctor_login'))

    if form.validate_on_submit():
        start = form.start_time.data
        end = form.end_time.data
        duration_minutes = int(form.duration.data)

        if end <= start:
            flash('End time must be later than start time.', 'danger')
            return redirect(url_for('main.doctor_availability'))

        # Check for overlaps
        existing_overlap = AvailabilitySlot.query.filter(
            AvailabilitySlot.doctor_id == current_user.id,
            AvailabilitySlot.end_time > start,
            AvailabilitySlot.start_time < end
        ).first()

        if existing_overlap:
            flash('The selected time block overlaps with your existing slots. Please select a different time or clear existing slots.', 'danger')
            return redirect(url_for('main.doctor_availability'))

        try:
            current_time = start
            added_count = 0
            while current_time < end:
                slot_end = current_time + timedelta(minutes=duration_minutes)
                if slot_end > end:
                    slot_end = end
                
                slot = AvailabilitySlot(
                    doctor_id=current_user.id,
                    start_time=current_time,
                    end_time=slot_end,
                )
                db.session.add(slot)
                added_count += 1
                current_time = slot_end

            db.session.commit()
            flash(f'Added {added_count} availability slots of {duration_minutes} minutes.', 'success')
        except Exception:
            db.session.rollback()
            flash('Could not add availability slots.', 'danger')
        return redirect(url_for('main.doctor_availability'))

    # Only show upcoming slots
    slots = AvailabilitySlot.query.filter(
        AvailabilitySlot.doctor_id == current_user.id,
        AvailabilitySlot.start_time >= datetime.utcnow()
    ).order_by(AvailabilitySlot.start_time.asc()).all()
    return render_template('doctor_availability.html', title='Doctor Availability', form=form, slots=slots)


@main.route('/doctor/availability/clear', methods=['POST'])
@roles_required('doctor')
def clear_availability_slots():
    try:
        deleted_count = AvailabilitySlot.query.filter(
            AvailabilitySlot.doctor_id == current_user.id,
            AvailabilitySlot.start_time >= datetime.utcnow(),
            AvailabilitySlot.is_booked == False
        ).delete(synchronize_session=False)
        db.session.commit()
        flash(f'Successfully cleared {deleted_count} upcoming free slots.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Could not clear slots.', 'danger')
    return redirect(url_for('main.doctor_availability'))


@main.route('/doctor/availability/<int:slot_id>/delete', methods=['POST'])
@roles_required('doctor')
def delete_availability_slot(slot_id):
    slot = AvailabilitySlot.query.get_or_404(slot_id)
    if slot.doctor_id != current_user.id:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('main.doctor_availability'))
        
    if slot.is_booked:
        flash('Cannot delete a slot that is already booked.', 'warning')
        return redirect(url_for('main.doctor_availability'))
        
    try:
        db.session.delete(slot)
        db.session.commit()
        flash('Availability slot deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Could not delete slot.', 'danger')
        
    return redirect(url_for('main.doctor_availability'))

@main.route('/doctor/appointments/<int:appointment_id>/status', methods=['POST'])
@roles_required('doctor')
def doctor_update_appointment_status(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.doctor_id != current_user.id:
        flash('Unauthorized appointment action.', 'danger')
        return redirect(url_for('main.doctor_dashboard'))

    if current_user.doctor_verification_status != 'approved':
        flash('Doctor account is pending admin approval.', 'warning')
        return redirect(url_for('auth.doctor_login'))

    decision = (request.form.get('decision') or '').strip().lower()
    if decision not in ('approve', 'reject'):
        flash('Invalid decision.', 'danger')
        return redirect(url_for('main.doctor_dashboard'))

    # Prepare email details
    patient = appointment.patient
    patient_email = patient.email
    patient_name = patient.name
    doctor_name = current_user.name
    
    if decision == 'approve':
        appointment.status = 'Accepted'
        appointment.approved_at = datetime.utcnow()
        action = 'appointment.approve'
        message = 'Appointment approved.'
        
        # Send approval email
        if appointment.slot:
            appointment_date = appointment.slot.start_time.strftime('%B %d, %Y')
            appointment_time = appointment.slot.start_time.strftime('%I:%M %p')
        else:
            appointment_date = 'To be scheduled'
            appointment_time = 'To be scheduled'
        
        email_sent = send_appointment_approved(
            patient_email=patient_email,
            patient_name=patient_name,
            doctor_name=doctor_name,
            appointment_date=appointment_date,
            appointment_time=appointment_time
        )
        
        if not email_sent:
            flash('Appointment approved, but email notification could not be sent.', 'warning')
    else:
        appointment.status = 'rejected'
        appointment.approved_at = None
        if appointment.slot:
            appointment.slot.is_booked = False
        action = 'appointment.reject'
        message = 'Appointment rejected.'
        
        # Send rejection email
        reason = (request.form.get('reason') or '').strip() or None
        email_sent = send_appointment_rejected(
            patient_email=patient_email,
            patient_name=patient_name,
            doctor_name=doctor_name,
            reason=reason
        )
        
        if not email_sent:
            flash('Appointment rejected, but email notification could not be sent.', 'warning')

    try:
        db.session.commit()
        try:
            db.session.add(AuditLog(
                user_id=current_user.id,
                action=action,
                resource_type='appointment',
                resource_id=appointment.id,
                details={'patient_id': appointment.patient_id}
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(message, 'success')
    except Exception:
        db.session.rollback()
        flash('Could not update appointment.', 'danger')

    return redirect(url_for('main.doctor_dashboard'))


@main.route('/doctor/appointments/<int:appointment_id>', methods=['GET', 'POST'])
@roles_required('doctor')
def doctor_appointment_detail(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.doctor_id != current_user.id:
        flash('Unauthorized appointment access.', 'danger')
        return redirect(url_for('main.doctor_dashboard'))

    if current_user.doctor_verification_status != 'approved':
        flash('Doctor account is pending admin approval.', 'warning')
        return redirect(url_for('auth.doctor_login'))

    if appointment.status != 'Accepted':
        flash('Accept the appointment first to view patient report and history.', 'warning')
        return redirect(url_for('main.doctor_dashboard'))

    patient = appointment.patient
    medical_info = patient.medical_info if patient else None
    predictions = Prediction.query.options(
        joinedload(Prediction.author)
    ).filter_by(user_id=appointment.patient_id).order_by(Prediction.timestamp.desc()).all()

    form = PrescriptionForm()
    existing_prescription = Prescription.query.filter_by(appointment_id=appointment.id).first()

    if request.method == 'GET' and existing_prescription:
        form.content.data = existing_prescription.content

    if form.validate_on_submit():
        try:
            if existing_prescription:
                existing_prescription.content = form.content.data
                existing_prescription.updated_at = datetime.utcnow()
                prescription_id = existing_prescription.id
            else:
                new_prescription = Prescription(
                    appointment_id=appointment.id,
                    doctor_id=current_user.id,
                    patient_id=appointment.patient_id,
                    content=form.content.data,
                )
                db.session.add(new_prescription)
                prescription_id = None
            db.session.commit()

            if prescription_id is None:
                saved = Prescription.query.filter_by(appointment_id=appointment.id).first()
                prescription_id = saved.id if saved else None

            try:
                db.session.add(AuditLog(
                    user_id=current_user.id,
                    action='prescription.write',
                    resource_type='prescription',
                    resource_id=prescription_id,
                    details={'appointment_id': appointment.id, 'patient_id': appointment.patient_id}
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()

            flash('Prescription saved successfully.', 'success')
        except Exception:
            db.session.rollback()
            flash('Could not save prescription.', 'danger')

        return redirect(url_for('main.doctor_appointment_detail', appointment_id=appointment.id))

    return render_template(
        'doctor_appointment_detail.html',
        title='Appointment Detail',
        appointment=appointment,
        patient=patient,
        medical_info=medical_info,
        predictions=predictions,
        form=form,
        existing_prescription=existing_prescription,
    )


@main.route('/prescription/<int:appointment_id>/download')
@login_required
def download_prescription(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    prescription = Prescription.query.filter_by(appointment_id=appointment.id).first_or_404()

    # Access allowed for patient, assigned doctor, and admin.
    if current_user.role not in ('admin',):
        is_patient = appointment.patient_id == current_user.id
        is_doctor = appointment.doctor_id == current_user.id
        if not is_patient and not is_doctor:
            flash('You cannot download this prescription.', 'danger')
            return redirect(url_for(role_home_endpoint(current_user)))

    doctor = appointment.doctor
    patient = appointment.patient

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title='Prescription'
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='RxHeader', parent=styles['Heading2'], textColor=colors.HexColor('#1f4e79')))

    def _draw_rx_header_footer(canvas, doc):
        canvas.saveState()
        width, height = A4
        header_y = height - 18 * mm + 6
        canvas.setFont('Helvetica-Bold', 12)
        canvas.setFillColor(colors.HexColor('#1f4e79'))
        canvas.drawString(18 * mm, header_y, 'HeartAnomaly Clinic')
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.black)
        canvas.drawRightString(width - 18 * mm, header_y, (doctor.name if doctor else ''))

        footer_y = 12 * mm
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#6c757d'))
        canvas.drawCentredString(width / 2.0, footer_y, 'Generated by HeartAnomaly — keep this prescription for your records.')
        canvas.restoreState()

    story = []
    story.append(Paragraph(f"<b>Dr. {doctor.name if doctor else 'Unknown'}</b>", styles['RxHeader']))
    story.append(Paragraph(f"{(doctor.doctor_designation or 'Doctor') if doctor else 'Doctor'}", styles['BodyText']))
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"<b>Patient:</b> {patient.name if patient else '-'}", styles['BodyText']))
    story.append(Paragraph(f"<b>Email:</b> {patient.email if patient else '-'}", styles['BodyText']))
    if patient and patient.medical_info:
        info = patient.medical_info
        story.append(Paragraph(f"<b>Age:</b> {info.age if info.age is not None else '-'}", styles['BodyText']))
        story.append(Paragraph(f"<b>Blood Group:</b> {info.blood_group or '-'}", styles['BodyText']))
    story.append(Spacer(1, 8))

    story.append(Paragraph('<b>Prescription</b>', styles['Heading3']))
    story.append(Paragraph(prescription.content.replace('\n', '<br/>'), styles['BodyText']))
    story.append(Spacer(1, 12))

    created_time = prescription.updated_at or prescription.created_at
    story.append(Paragraph(f"Date: {created_time.strftime('%Y-%m-%d %H:%M') if created_time else '-'}", styles['BodyText']))

    document.build(story, onFirstPage=_draw_rx_header_footer, onLaterPages=_draw_rx_header_footer)
    buffer.seek(0)

    try:
        db.session.add(AuditLog(
            user_id=current_user.id,
            action='prescription.download',
            resource_type='prescription',
            resource_id=prescription.id,
            details={'appointment_id': appointment.id}
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    patient_name = secure_filename(patient.name) if patient else f'patient_{appointment.patient_id}'
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'{patient_name}_prescription_{appointment.id}.pdf',
        mimetype='application/pdf'
    )


@main.route('/prescription/<int:appointment_id>/preview')
@login_required
def preview_prescription(appointment_id):
    """Preview prescription as inline PDF in browser."""
    appointment = Appointment.query.get_or_404(appointment_id)
    prescription = Prescription.query.filter_by(appointment_id=appointment.id).first_or_404()

    # Access allowed for patient, assigned doctor, and admin.
    if current_user.role not in ('admin',):
        is_patient = appointment.patient_id == current_user.id
        is_doctor = appointment.doctor_id == current_user.id
        if not is_patient and not is_doctor:
            flash('You cannot preview this prescription.', 'danger')
            return redirect(url_for(role_home_endpoint(current_user)))

    doctor = appointment.doctor
    patient = appointment.patient

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title='Prescription'
    )
    story = []
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='PrescriptionHeading', parent=styles['Heading2'], fontSize=13, textColor=colors.HexColor('#1f4e79'), spaceAfter=10))
    styles.add(ParagraphStyle(name='PrescriptionSection', parent=styles['Heading3'], fontSize=12, textColor=colors.HexColor('#1f4e79'), spaceAfter=8, spaceBefore=8))

    # Header/footer drawing
    def _draw_header_footer(canvas, doc):
        canvas.saveState()
        width, height = A4
        header_y = height - 18 * mm + 6
        # Header background line
        canvas.setFillColor(colors.HexColor('#1f4e79'))
        canvas.setFont('Helvetica-Bold', 12)
        canvas.drawString(18 * mm, header_y, 'HeartAnomaly AI')
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.black)
        canvas.drawRightString(width - 18 * mm, header_y, datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))

        # Footer small text
        footer_y = 12 * mm
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#6c757d'))
        canvas.drawCentredString(width / 2.0, footer_y, 'This prescription is for informational purposes only.')
        canvas.restoreState()

    story.append(Paragraph('Medical Prescription', styles['PrescriptionHeading']))
    story.append(Spacer(1, 10))

    appointment_info_rows = [
        ['Doctor', doctor.name if doctor else 'N/A'],
        ['Patient', patient.name if patient else 'N/A'],
        ['Appointment Date', appointment.slot.start_time.strftime('%Y-%m-%d %H:%M') if appointment.slot else 'N/A'],
        ['Prescription Date', prescription.created_at.strftime('%Y-%m-%d %H:%M') if prescription.created_at else 'N/A'],
    ]
    appointment_info_table = Table(appointment_info_rows, colWidths=[100 * mm, 80 * mm])
    appointment_info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e8f1f7')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#c7d5e0')),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(appointment_info_table)
    story.append(Spacer(1, 15))

    story.append(Paragraph('Prescription Details', styles['PrescriptionSection']))
    story.append(Paragraph(prescription.content, styles['BodyText']))
    story.append(Spacer(1, 15))

    story.append(Paragraph(f"<b>Prescribed by:</b> Dr. {doctor.name if doctor else 'N/A'}", styles['BodyText']))
    story.append(Spacer(1, 8))
    story.append(Paragraph('Disclaimer: Please follow the prescription as directed by your doctor. This is a digital record for your reference.', styles['BodyText']))

    # Build document and handle generation errors gracefully
    try:
        document.build(story, onFirstPage=_draw_header_footer, onLaterPages=_draw_header_footer)
        buffer.seek(0)
    except Exception as e:
        current_app.logger.exception('Failed to generate prescription preview for appointment_id=%s', appointment.id)
        error_html = render_template_string(
            '<html><body style="font-family:Inter, Arial, sans-serif;padding:24px;">'
            '<h3>Preview unavailable</h3>'
            '<p>Unable to generate the prescription preview right now. Please download the prescription instead.</p>'
            '<p style="color:#666;font-size:0.9rem;"><small>Error: {{ err }}</small></p>'
            '</body></html>', err=str(e)
        )
        return current_app.response_class(error_html, mimetype='text/html', status=500)

    # Audit: prescription preview
    try:
        db.session.add(AuditLog(
            user_id=current_user.id,
            action='prescription.preview',
            resource_type='prescription',
            resource_id=prescription.id,
            details={'appointment_id': appointment.id}
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    response = send_file(
        buffer,
        as_attachment=False,
        mimetype='application/pdf'
    )
    # Cache preview for 30 minutes to improve performance
    response.headers['Cache-Control'] = 'public, max-age=1800'
    return response


@main.route('/appointments/<int:appointment_id>/cancel', methods=['POST'])
@roles_required('patient')
def cancel_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.patient_id != current_user.id:
        flash('Unauthorized appointment action.', 'danger')
        return redirect(url_for('main.appointments'))

    if appointment.status != 'pending':
        flash(f'Cannot cancel appointment. Doctor has already {appointment.status.lower()} this appointment.', 'warning')
        return redirect(url_for('main.appointments'))

    if appointment.slot:
        appointment.slot.is_booked = False

    appointment.status = 'cancelled'
    appointment.approved_at = None

    try:
        db.session.commit()
        try:
            db.session.add(AuditLog(
                user_id=current_user.id,
                action='appointment.cancel',
                resource_type='appointment',
                resource_id=appointment.id,
                details={'doctor_id': appointment.doctor_id, 'slot_id': appointment.slot_id}
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash('Appointment cancelled.', 'success')
    except Exception:
        db.session.rollback()
        flash('Could not cancel appointment.', 'danger')

    return redirect(url_for('main.appointments'))


@main.route('/appointments/<int:appointment_id>/reschedule', methods=['POST'])
@roles_required('patient')
def reschedule_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.patient_id != current_user.id:
        flash('Unauthorized appointment action.', 'danger')
        return redirect(url_for('main.appointments'))

    if appointment.status != 'pending':
        flash(f'Cannot reschedule appointment. Current status is {appointment.status}. Please request a new one.', 'warning')
        return redirect(url_for('main.appointments'))

    new_slot_id = request.form.get('new_slot_id')
    new_slot = AvailabilitySlot.query.filter_by(
        id=new_slot_id,
        doctor_id=appointment.doctor_id,
        is_booked=False,
    ).first()

    if not new_slot:
        flash('Selected slot is no longer available.', 'warning')
        return redirect(url_for('main.appointments'))

    old_slot_id = appointment.slot_id
    if appointment.slot:
        appointment.slot.is_booked = False
    new_slot.is_booked = True
    appointment.slot_id = new_slot.id
    appointment.status = 'pending'
    appointment.approved_at = None

    try:
        db.session.commit()
        try:
            db.session.add(AuditLog(
                user_id=current_user.id,
                action='appointment.reschedule',
                resource_type='appointment',
                resource_id=appointment.id,
                details={'doctor_id': appointment.doctor_id, 'old_slot_id': old_slot_id, 'new_slot_id': new_slot.id}
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash('Appointment rescheduled and sent for approval again.', 'success')
    except Exception:
        db.session.rollback()
        flash('Could not reschedule appointment.', 'danger')

    return redirect(url_for('main.appointments'))

@main.route("/profile", methods=['GET', 'POST'])
@login_required
def profile():
    form = UpdateAccountForm()

    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.email = form.email.data
        if form.password.data:
            current_user.password_hash = generate_password_hash(form.password.data)
        db.session.commit()
        flash('Your account has been updated!', 'success')
        return redirect(url_for('main.profile'))
    elif request.method == 'GET':
        form.name.data = current_user.name
        form.email.data = current_user.email
        
    stats = {}
    if current_user.role == 'patient':
        stats['appointments_count'] = Appointment.query.filter_by(patient_id=current_user.id).count()
        stats['ecg_reports_count'] = Prediction.query.filter_by(user_id=current_user.id).count()
        
        # Check if medical info is complete using the new check
        med = current_user.medical_info
        stats['medical_info_complete'] = bool(med and med.phone_number and med.blood_pressure)
    elif current_user.role == 'doctor':
        stats['consultations_count'] = Appointment.query.filter_by(doctor_id=current_user.id, status='Accepted').count()
        stats['pending_requests'] = Appointment.query.filter_by(doctor_id=current_user.id, status='pending').count()

    return render_template('profile.html', title='Profile', form=form, stats=stats)


@main.route('/admin/users', methods=['GET', 'POST'])
@roles_required('admin')
def admin_users():
    from app.models import User
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        action = request.form.get('action', 'update_email')
        user = User.query.get(user_id)
        if not user:
            flash('Invalid user', 'danger')
            return redirect(url_for('main.admin_users'))

        # Handle user deletion
        if action == 'delete_user':
            # Prevent deleting the current admin user
            if user.id == current_user.id:
                flash('Cannot delete your own admin account', 'danger')
                return redirect(url_for('main.admin_users'))

            deleted_user_name = user.name
            deleted_user_email = user.email
            deleted_user_id = user.id
            deleted_user_role = user.role

            try:
                # Delete in order of dependencies to avoid foreign key constraint issues
                # 1. Delete prescriptions
                Prescription.query.filter(
                    (Prescription.doctor_id == user.id) | (Prescription.patient_id == user.id)
                ).delete()
                
                # 2. Delete appointments (both as doctor and patient)
                Appointment.query.filter(
                    (Appointment.doctor_id == user.id) | (Appointment.patient_id == user.id)
                ).delete()
                
                # 3. Delete availability slots (for doctors)
                AvailabilitySlot.query.filter(AvailabilitySlot.doctor_id == user.id).delete()
                
                # 4. Delete predictions
                Prediction.query.filter(Prediction.user_id == user.id).delete()
                
                # 5. Delete the user (medical_info and password_reset_otp cascade automatically)
                db.session.delete(user)
                db.session.commit()

                # Log the deletion
                try:
                    db.session.add(AuditLog(
                        user_id=current_user.id,
                        action='user.delete',
                        resource_type='user',
                        resource_id=deleted_user_id,
                        details={'name': deleted_user_name, 'email': deleted_user_email, 'role': deleted_user_role}
                    ))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

                flash(f'User "{deleted_user_name}" ({deleted_user_email}) has been deleted', 'success')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error deleting user {user_id}: {str(e)}")
                flash('Could not delete user. Please try again.', 'danger')

            return redirect(url_for('main.admin_users'))

        # Handle email update
        new_email = (request.form.get('email') or '').strip().lower()
        if not new_email:
            flash('Email is required', 'danger')
            return redirect(url_for('main.admin_users'))

        existing_user = User.query.filter(User.email == new_email, User.id != user.id).first()
        if existing_user:
            flash('Email already in use by another account', 'danger')
            return redirect(url_for('main.admin_users'))

        old_email = user.email
        user.email = new_email

        try:
            db.session.commit()
            try:
                db.session.add(AuditLog(
                    user_id=current_user.id,
                    action='user.email.update',
                    resource_type='user',
                    resource_id=user.id,
                    details={'old_email': old_email, 'new_email': new_email}
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()

            flash('User email updated', 'success')
        except Exception:
            db.session.rollback()
            flash('Could not update email', 'danger')

        return redirect(url_for('main.admin_users'))

    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=users)


@main.route('/admin/doctors', methods=['GET', 'POST'])
@roles_required('admin')
def admin_doctors():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        decision = (request.form.get('decision') or '').strip().lower()
        doctor = User.query.filter_by(id=user_id, role='doctor').first()

        if not doctor:
            flash('Doctor account not found.', 'danger')
            return redirect(url_for('main.admin_doctors'))

        if decision not in ('approve', 'reject'):
            flash('Invalid decision.', 'danger')
            return redirect(url_for('main.admin_doctors'))

        # Once a decision has been made, it cannot be changed.
        if doctor.doctor_verification_status != 'pending':
            flash('This doctor has already been reviewed and cannot be changed.', 'warning')
            return redirect(url_for('main.admin_doctors'))

        old_status = doctor.doctor_verification_status
        if decision == 'approve':
            doctor.doctor_verification_status = 'approved'
            doctor.doctor_verified_at = datetime.utcnow()
            audit_action = 'doctor.verify'
            success_message = 'Doctor approved successfully.'
        else:
            doctor.doctor_verification_status = 'rejected'
            doctor.doctor_verified_at = None
            audit_action = 'doctor.reject'
            success_message = 'Doctor rejected.'

        try:
            db.session.commit()
            try:
                db.session.add(AuditLog(
                    user_id=current_user.id,
                    action=audit_action,
                    resource_type='user',
                    resource_id=doctor.id,
                    details={
                        'doctor_email': doctor.email,
                        'old_status': old_status,
                        'new_status': doctor.doctor_verification_status,
                    }
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()

            flash(success_message, 'success')
        except Exception:
            db.session.rollback()
            flash('Unable to update doctor verification status.', 'danger')

        return redirect(url_for('main.admin_doctors'))

    doctors = User.query.filter_by(role='doctor').order_by(User.created_at.desc()).all()
    return render_template('admin_doctors.html', doctors=doctors)


@main.route('/admin/analytics')
@roles_required('admin')
def admin_analytics():
    today = datetime.utcnow().date()
    week_ago = datetime.utcnow() - timedelta(days=7)

    total_users = User.query.count()
    total_patients = User.query.filter_by(role='patient').count()
    total_doctors = User.query.filter_by(role='doctor').count()
    total_admins = User.query.filter_by(role='admin').count()

    doctors_pending = User.query.filter_by(role='doctor', doctor_verification_status='pending').count()
    doctors_approved = User.query.filter_by(role='doctor', doctor_verification_status='approved').count()
    doctors_rejected = User.query.filter_by(role='doctor', doctor_verification_status='rejected').count()

    total_predictions = Prediction.query.count()
    predictions_today = Prediction.query.filter(func.date(Prediction.timestamp) == today).count()
    predictions_7d = Prediction.query.filter(Prediction.timestamp >= week_ago).count()
    normal_predictions = Prediction.query.filter_by(result='Normal').count()
    abnormal_predictions = Prediction.query.filter_by(result='Abnormal').count()

    report_downloads_7d = AuditLog.query.filter(
        AuditLog.action == 'report.download',
        AuditLog.timestamp >= week_ago,
    ).count()

    recent_audits = AuditLog.query.options(
        joinedload(AuditLog.user)
    ).order_by(AuditLog.timestamp.desc()).limit(10).all()

    return render_template(
        'admin_analytics.html',
        total_users=total_users,
        total_patients=total_patients,
        total_doctors=total_doctors,
        total_admins=total_admins,
        doctors_pending=doctors_pending,
        doctors_approved=doctors_approved,
        doctors_rejected=doctors_rejected,
        total_predictions=total_predictions,
        predictions_today=predictions_today,
        predictions_7d=predictions_7d,
        normal_predictions=normal_predictions,
        abnormal_predictions=abnormal_predictions,
        report_downloads_7d=report_downloads_7d,
        recent_audits=recent_audits,
    )


@main.route('/admin/audit')
@roles_required('admin')
def admin_audit():
    try:
        logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(200).all()
    except Exception:
        db.session.rollback()
        flash('Audit log table is unavailable. Ask DBA to create it.', 'warning')
        logs = []
    return render_template('admin_audit.html', logs=logs)
