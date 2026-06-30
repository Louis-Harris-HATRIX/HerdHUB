import os
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import inspect, text

app = Flask(__name__)
base_dir = os.path.abspath(os.path.dirname(__file__))
env_mode = os.environ.get("FLASK_ENV", "development").lower()
is_production = env_mode == "production"

database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or f"sqlite:///{os.path.join(base_dir, 'livestock.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

secret_key = os.environ.get("SECRET_KEY") or os.environ.get("FLASK_SECRET_KEY")
if is_production and not secret_key:
    raise RuntimeError("SECRET_KEY environment variable is required in production.")
app.secret_key = secret_key or "farm-manager-dev-secret"
app.config["SESSION_COOKIE_SECURE"] = is_production

db = SQLAlchemy(app)

PUBLIC_PATHS = {"/login", "/logout"}
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_INDEMNITY_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp"}
ALLOWED_INDEMNITY_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
ANIMAL_UPLOAD_FOLDER = os.path.join(base_dir, "uploads", "animals")
INDEMNITY_UPLOAD_FOLDER = os.path.join(base_dir, "uploads", "indemnities")
CURRENCY_CODE = "ZAR"
CURRENCY_SYMBOL = "R"
os.makedirs(ANIMAL_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(INDEMNITY_UPLOAD_FOLDER, exist_ok=True)


class AuditMixin:
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    password = db.Column(db.String(512), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    role = db.Column(db.String(30), default="manager")
    is_active = db.Column(db.Boolean, default=True)
    profile_photo = db.Column(db.String(200))
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Camp(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    size = db.Column(db.String(40))
    water_status = db.Column(db.String(40))
    grazing_condition = db.Column(db.String(40))
    livestock_count = db.Column(db.Integer, default=0)
    last_movement_date = db.Column(db.String(20))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class Animal(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tag_number = db.Column(db.String(80), unique=True, nullable=False)
    species = db.Column(db.String(20), nullable=False)
    breed = db.Column(db.String(80))
    sex = db.Column(db.String(20))
    dob_or_age = db.Column(db.String(40))
    colour_markings = db.Column(db.String(80))
    camp_id = db.Column(db.Integer, db.ForeignKey("camp.id"))
    category = db.Column(db.String(80))
    status = db.Column(db.String(20), default="active")
    purchase_date = db.Column(db.String(20))
    purchase_source = db.Column(db.String(80))
    main_photo_path = db.Column(db.String(255))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    camp = db.relationship("Camp", backref="animals")


class AnimalPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey("animal.id"), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(200))
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)

    animal = db.relationship("Animal", backref="photos")
    uploaded_by = db.relationship("User", backref="uploaded_animal_photos")


class LivestockGroup(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    species = db.Column(db.String(20), nullable=False)
    number_of_animals = db.Column(db.Integer, default=0)
    camp_id = db.Column(db.Integer, db.ForeignKey("camp.id"))
    age_class = db.Column(db.String(40))
    purpose = db.Column(db.String(50))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    camp = db.relationship("Camp", backref="groups")


class Movement(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False)
    from_camp_id = db.Column(db.Integer, db.ForeignKey("camp.id"))
    to_camp_id = db.Column(db.Integer, db.ForeignKey("camp.id"))
    subject_name = db.Column(db.String(120), nullable=False)
    number_moved = db.Column(db.Integer, default=1)
    reason = db.Column(db.String(120))
    person_responsible = db.Column(db.String(80))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    from_camp = db.relationship("Camp", foreign_keys=[from_camp_id], backref="movements_out")
    to_camp = db.relationship("Camp", foreign_keys=[to_camp_id], backref="movements_in")


class HealthRecord(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False)
    subject_name = db.Column(db.String(120), nullable=False)
    treatment_type = db.Column(db.String(40), nullable=False)
    product_used = db.Column(db.String(100))
    dosage = db.Column(db.String(50))
    batch_number = db.Column(db.String(50))
    withdrawal_period = db.Column(db.String(50))
    next_due_date = db.Column(db.String(20))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class BreedingRecord(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    species = db.Column(db.String(20), nullable=False)
    breeding_season = db.Column(db.String(80))
    male_used = db.Column(db.String(80))
    female_reference = db.Column(db.String(120))
    date_exposed = db.Column(db.String(20))
    pregnancy_status = db.Column(db.String(40), default="pending")
    expected_birth_date = db.Column(db.String(20))
    actual_birth_date = db.Column(db.String(20))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class BirthRecord(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date_born = db.Column(db.String(20), nullable=False)
    species = db.Column(db.String(20), nullable=False)
    mother_reference = db.Column(db.String(120))
    father_reference = db.Column(db.String(120))
    number_born = db.Column(db.Integer, default=1)
    number_alive = db.Column(db.Integer, default=1)
    number_dead = db.Column(db.Integer, default=0)
    sex_if_known = db.Column(db.String(20))
    tag_numbers_assigned = db.Column(db.String(200))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class DeathLossRecord(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False)
    subject_name = db.Column(db.String(120), nullable=False)
    number_lost = db.Column(db.Integer, default=1)
    cause = db.Column(db.String(40))
    camp_id = db.Column(db.Integer, db.ForeignKey("camp.id"))
    estimated_value_lost = db.Column(db.String(40))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    camp = db.relationship("Camp", backref="losses")


class SalePurchaseRecord(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False)
    party = db.Column(db.String(120), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)
    species = db.Column(db.String(20), nullable=False)
    item_name = db.Column(db.String(120), nullable=False)
    number = db.Column(db.Integer, default=1)
    weight = db.Column(db.String(40))
    price_per_unit = db.Column(db.String(40))
    total_amount = db.Column(db.String(40))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class Task(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    due_date = db.Column(db.String(20), nullable=False)
    related_name = db.Column(db.String(120))
    priority = db.Column(db.String(20), default="medium")
    assigned_to = db.Column(db.String(80))
    status = db.Column(db.String(20), default="open")
    recurring = db.Column(db.String(20))
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(80), nullable=False)
    target_type = db.Column(db.String(80))
    target_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="activity_logs")


class DiaryEntry(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_date = db.Column(db.String(20), nullable=False)
    weather = db.Column(db.String(80))
    rainfall = db.Column(db.String(40))
    water_points_checked = db.Column(db.Text)
    grazing_condition = db.Column(db.String(80))
    fence_issues = db.Column(db.Text)
    sick_animals_observed = db.Column(db.Text)
    predator_theft_incidents = db.Column(db.Text)
    staff_attendance_notes = db.Column(db.Text)
    equipment_issues = db.Column(db.Text)
    general_notes = db.Column(db.Text)
    photo_placeholder = db.Column(db.String(200))
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class HuntingBooking(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_reference = db.Column(db.String(30), unique=True, nullable=False, index=True)
    hunter_name = db.Column(db.String(120), nullable=False)
    contact_number = db.Column(db.String(40))
    email = db.Column(db.String(120))
    date_from = db.Column(db.String(20), nullable=False)
    date_to = db.Column(db.String(20), nullable=False)
    number_of_hunting_days = db.Column(db.Integer, default=1)
    number_of_hunters = db.Column(db.Integer, default=1)
    number_of_guests = db.Column(db.Integer, default=0)
    day_fee_per_hunter = db.Column(db.Numeric(12, 2), default=0)
    staff_fee_per_day = db.Column(db.Numeric(12, 2), default=0)
    guide_fee_per_day = db.Column(db.Numeric(12, 2), default=0)
    tracker_fee_per_day = db.Column(db.Numeric(12, 2), default=0)
    skinner_fee_per_day = db.Column(db.Numeric(12, 2), default=0)
    accommodation_required = db.Column(db.Boolean, default=False)
    accommodation_nights = db.Column(db.Integer, default=0)
    accommodation_people = db.Column(db.Integer, default=0)
    accommodation_rate_per_person_per_night = db.Column(db.Numeric(12, 2), default=0)
    accommodation_total = db.Column(db.Numeric(12, 2), default=0)
    hunting_day_fees_total = db.Column(db.Numeric(12, 2), default=0)
    staff_fees_total = db.Column(db.Numeric(12, 2), default=0)
    extras_total = db.Column(db.Numeric(12, 2), default=0)
    animals_shot_total = db.Column(db.Numeric(12, 2), default=0)
    grand_total = db.Column(db.Numeric(12, 2), default=0)
    deposit_paid = db.Column(db.Numeric(12, 2), default=0)
    balance_due = db.Column(db.Numeric(12, 2), default=0)
    payment_status = db.Column(db.String(20), default="unpaid", index=True)
    fee_override_enabled = db.Column(db.Boolean, default=False)
    override_notes = db.Column(db.Text)
    override_hunting_day_fees_total = db.Column(db.Numeric(12, 2), default=0)
    override_staff_fees_total = db.Column(db.Numeric(12, 2), default=0)
    override_accommodation_total = db.Column(db.Numeric(12, 2), default=0)
    override_animals_shot_total = db.Column(db.Numeric(12, 2), default=0)
    override_extras_total = db.Column(db.Numeric(12, 2), default=0)
    override_grand_total = db.Column(db.Numeric(12, 2), default=0)
    final_hunting_day_fees_total = db.Column(db.Numeric(12, 2), default=0)
    final_staff_fees_total = db.Column(db.Numeric(12, 2), default=0)
    final_accommodation_total = db.Column(db.Numeric(12, 2), default=0)
    final_animals_shot_total = db.Column(db.Numeric(12, 2), default=0)
    final_extras_total = db.Column(db.Numeric(12, 2), default=0)
    final_grand_total = db.Column(db.Numeric(12, 2), default=0)
    final_balance_due = db.Column(db.Numeric(12, 2), default=0)
    guide_assigned = db.Column(db.String(120))
    status = db.Column(db.String(20), default="enquiry", index=True)
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class HunterProfile(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False, index=True)
    id_or_passport_number = db.Column(db.String(60), index=True)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    licence_details = db.Column(db.String(255))
    firearm_details = db.Column(db.String(255))
    emergency_contact_name = db.Column(db.String(120))
    emergency_contact_number = db.Column(db.String(40))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class HuntingIndemnity(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("hunting_booking.id"), nullable=False, index=True)
    hunter_id = db.Column(db.Integer, db.ForeignKey("hunter_profile.id"), nullable=False, index=True)
    date_signed = db.Column(db.String(20))
    status = db.Column(db.String(20), default="missing", index=True)
    indemnity_file_path = db.Column(db.String(255))
    witness_or_staff_member = db.Column(db.String(120))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    booking = db.relationship("HuntingBooking", backref="indemnities")
    hunter = db.relationship("HunterProfile", backref="indemnities")


class HuntingSpeciesPrice(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    species_name = db.Column(db.String(120), nullable=False, index=True)
    category = db.Column(db.String(40), default="trophy", index=True)
    sex = db.Column(db.String(20), default="unknown")
    price = db.Column(db.Numeric(12, 2), default=0)
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class HuntingLog(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey("hunting_booking.id"), nullable=False, index=True)
    hunter_id = db.Column(db.Integer, db.ForeignKey("hunter_profile.id"), nullable=True, index=True)
    species = db.Column(db.String(120), nullable=False, index=True)
    outcome = db.Column(db.String(20), default="shot", index=True)
    recovered = db.Column(db.Boolean, default=True)
    number_animals = db.Column(db.Integer, default=1)
    price_charged = db.Column(db.Numeric(12, 2), default=0)
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    booking = db.relationship("HuntingBooking", backref="hunting_logs")
    hunter = db.relationship("HunterProfile", backref="hunting_logs")


class HuntingWoundedFollowUp(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hunting_log_id = db.Column(db.Integer, db.ForeignKey("hunting_log.id"), nullable=False, index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("hunting_booking.id"), nullable=False, index=True)
    species = db.Column(db.String(120), nullable=False)
    date_wounded = db.Column(db.String(20))
    follow_up_status = db.Column(db.String(20), default="open", index=True)
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    hunting_log = db.relationship("HuntingLog", backref="wounded_follow_ups")
    booking = db.relationship("HuntingBooking", backref="wounded_follow_ups")


class WildlifeSpecies(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    common_name = db.Column(db.String(120), nullable=False, index=True)
    scientific_name = db.Column(db.String(160))
    category = db.Column(db.String(60), default="game", index=True)
    sex_tracking_required = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)


class WildlifeCount(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    count_date = db.Column(db.String(20), nullable=False, index=True)
    camp_id = db.Column(db.Integer, db.ForeignKey("camp.id"), nullable=False, index=True)
    species_id = db.Column(db.Integer, db.ForeignKey("wildlife_species.id"), nullable=False, index=True)
    count_method = db.Column(db.String(80), default="visual")
    male_count = db.Column(db.Integer, default=0)
    female_count = db.Column(db.Integer, default=0)
    juvenile_count = db.Column(db.Integer, default=0)
    total_count = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    camp = db.relationship("Camp", backref="wildlife_counts")
    species = db.relationship("WildlifeSpecies", backref="counts")


class WildlifeOfftakeRecord(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False, index=True)
    camp_id = db.Column(db.Integer, db.ForeignKey("camp.id"), nullable=False, index=True)
    species_id = db.Column(db.Integer, db.ForeignKey("wildlife_species.id"), nullable=False, index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("hunting_booking.id"), nullable=True, index=True)
    hunter_id = db.Column(db.Integer, db.ForeignKey("hunter_profile.id"), nullable=True, index=True)
    offtake_type = db.Column(db.String(40), default="trophy", index=True)
    sex = db.Column(db.String(20), default="unknown")
    age_class = db.Column(db.String(40))
    trophy_score = db.Column(db.String(40))
    price_value = db.Column(db.Numeric(12, 2), default=0)
    recovered = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    camp = db.relationship("Camp", backref="wildlife_offtakes")
    species = db.relationship("WildlifeSpecies", backref="offtakes")
    booking = db.relationship("HuntingBooking", backref="wildlife_offtakes")
    hunter = db.relationship("HunterProfile", backref="wildlife_offtakes")


class StaffNote(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    note_date = db.Column(db.String(20), nullable=False, index=True)
    staff_member = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(160), nullable=False)
    note_type = db.Column(db.String(60), default="general", index=True)
    details = db.Column(db.Text, nullable=False)
    camp_id = db.Column(db.Integer, db.ForeignKey("camp.id"), nullable=True, index=True)
    status = db.Column(db.String(30), default="open", index=True)
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    camp = db.relationship("Camp", backref="staff_notes")


class MaintenanceNote(AuditMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    note_date = db.Column(db.String(20), nullable=False, index=True)
    asset_or_area = db.Column(db.String(160), nullable=False)
    camp_id = db.Column(db.Integer, db.ForeignKey("camp.id"), nullable=True, index=True)
    issue_type = db.Column(db.String(80), default="general", index=True)
    priority = db.Column(db.String(20), default="medium", index=True)
    status = db.Column(db.String(30), default="open", index=True)
    assigned_to = db.Column(db.String(120))
    details = db.Column(db.Text, nullable=False)
    completed_date = db.Column(db.String(20))
    notes = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    camp = db.relationship("Camp", backref="maintenance_notes")


def parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def record_in_range(record, date_field, start_date=None, end_date=None):
    if not start_date and not end_date:
        return True
    value = getattr(record, date_field, None)
    if not value:
        return True
    record_date = parse_date(value)
    if not record_date:
        return True
    if start_date and record_date < start_date:
        return False
    if end_date and record_date > end_date:
        return False
    return True


def build_notifications():
    tasks = Task.query.filter_by(is_deleted=False).all()
    health_records = HealthRecord.query.filter_by(is_deleted=False).all()
    breeding_records = BreedingRecord.query.filter_by(is_deleted=False).all()
    deaths = DeathLossRecord.query.filter_by(is_deleted=False).all()
    camps = Camp.query.filter_by(is_deleted=False).all()
    notifications = []

    for task in tasks:
        if task.status != "done" and task.due_date and task.due_date < date.today().isoformat():
            notifications.append({"type": "overdue", "title": task.title, "message": f"Overdue task due {task.due_date}", "badge": "danger"})
        elif task.status != "done" and task.due_date and task.due_date == date.today().isoformat():
            notifications.append({"type": "today", "title": task.title, "message": "Task due today", "badge": "warning"})

    for record in health_records:
        if record.next_due_date and record.next_due_date <= (date.today().isoformat()):
            notifications.append({"type": "followup", "title": record.subject_name, "message": f"Follow-up needed for {record.treatment_type}", "badge": "warning"})

    for record in breeding_records:
        if record.pregnancy_status == "pregnant" and record.expected_birth_date:
            expected = parse_date(record.expected_birth_date)
            if expected and expected <= date.today().replace(day=min(28, date.today().day)):
                notifications.append({"type": "pregnant", "title": record.female_reference, "message": "Pregnancy due soon", "badge": "info"})

    for death in deaths:
        if death.number_lost and death.number_lost >= 2:
            notifications.append({"type": "death", "title": death.subject_name, "message": "High loss alert", "badge": "danger"})

    for camp in camps:
        if camp.water_status and camp.water_status.lower() in {"low", "dry", "urgent"}:
            notifications.append({"type": "water", "title": camp.name, "message": "Water issue reported", "badge": "warning"})

    return notifications[:10]


@app.context_processor
def inject_user():
    user = current_user()
    notifications = build_notifications() if user else []
    return {
        "current_user": user,
        "current_role": role_label(user.role) if user else "Guest",
        "can_manage_users": bool(user and user.role == "admin"),
        "can_change_settings": bool(user and user.role == "admin"),
        "is_admin": bool(user and user.role == "admin"),
        "notifications": notifications,
        "notification_count": len(notifications),
        "animal_photo_url": lambda animal, filename: url_for("animal_photo_file", animal_id=animal.id, filename=filename) if animal and filename else None,
        "currency_code": CURRENCY_CODE,
        "currency_symbol": CURRENCY_SYMBOL,
        "format_currency": format_currency,
    }


def current_user():
    try:
        user_id = session.get("user_id")
    except RuntimeError:
        return None

    if user_id:
        user = db.session.get(User, user_id)
        if user and user.is_active:
            return user
    return None


def role_label(role):
    return "Admin / Farm Owner" if role == "admin" else "Farm Manager"


def require_role(*roles):
    user = current_user()
    if not user:
        return redirect(url_for("login", next=request.path))
    if user.role not in roles:
        flash("You do not have permission for that action.")
        return render_template("errors/403.html", title="Access denied"), 403
    return None


def log_activity(action, target_type, target_id, details):
    try:
        user = current_user()
    except RuntimeError:
        return
    if not user:
        return
    record = ActivityLog(user_id=user.id, action=action, target_type=target_type, target_id=target_id, details=details)
    db.session.add(record)
    db.session.commit()


def set_audit_fields(record, user_id):
    record.created_by_user_id = record.created_by_user_id or user_id
    record.updated_by_user_id = user_id
    record.updated_at = datetime.now(timezone.utc)
    if not record.created_at:
        record.created_at = datetime.now(timezone.utc)


def archive_record(record, user_id):
    record.is_deleted = True
    record.updated_by_user_id = user_id
    record.updated_at = datetime.now(timezone.utc)


def next_booking_reference():
    prefix = f"BK{date.today().strftime('%y')}"
    latest = HuntingBooking.query.filter(HuntingBooking.booking_reference.like(f"{prefix}%")).order_by(HuntingBooking.id.desc()).first()
    if latest and latest.booking_reference and latest.booking_reference[-4:].isdigit():
        number = int(latest.booking_reference[-4:]) + 1
    else:
        number = 1
    return f"{prefix}{number:04d}"


def parse_money_value(value):
    if value is None:
        return 0.0
    cleaned = str(value).upper().replace(CURRENCY_CODE, "").replace(CURRENCY_SYMBOL, "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0.0
    try:
        amount = Decimal(cleaned)
        return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return 0.0


def parse_int_value(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def format_currency(value):
    return f"{CURRENCY_SYMBOL}{parse_money_value(value):,.2f}"


def build_wildlife_count_totals(form_data):
    male_count = max(parse_int_value(form_data.get("male_count"), 0), 0)
    female_count = max(parse_int_value(form_data.get("female_count"), 0), 0)
    juvenile_count = max(parse_int_value(form_data.get("juvenile_count"), 0), 0)
    subtotal = male_count + female_count + juvenile_count
    provided_total = parse_int_value(form_data.get("total_count"), subtotal)
    total_count = max(provided_total, 0)
    return male_count, female_count, juvenile_count, subtotal, total_count


def validate_wildlife_count_form(form_data):
    if not form_data.get("count_date"):
        return "Count date is required."
    if not form_data.get("camp_id"):
        return "Camp is required for a wildlife count."
    if not form_data.get("species_id"):
        return "Species is required for a wildlife count."

    male_count, female_count, juvenile_count, subtotal, total_count = build_wildlife_count_totals(form_data)
    if min(male_count, female_count, juvenile_count, total_count) < 0:
        return "Wildlife count values cannot be negative."
    if total_count < subtotal:
        return "Total count cannot be less than the sum of male, female, and juvenile counts."
    return None


def validate_wildlife_offtake_form(form_data):
    errors = {}
    if not form_data.get("date"):
        errors["date"] = "Offtake date is required."
    if not form_data.get("camp_id"):
        errors["camp_id"] = "Camp is required for a wildlife offtake record."
    if not form_data.get("species_id"):
        errors["species_id"] = "Species is required for a wildlife offtake record."

    offtake_type = (form_data.get("offtake_type") or "trophy").strip().lower()
    if offtake_type not in {"trophy", "cull", "meat"}:
        errors["offtake_type"] = "Invalid offtake type selected."

    sex = (form_data.get("sex") or "unknown").strip().lower()
    if sex not in {"male", "female", "unknown"}:
        errors["sex"] = "Sex must be male, female, or unknown."

    price_value = parse_money_value(form_data.get("price_value"))
    if price_value < 0:
        errors["price_value"] = "Offtake value cannot be negative."
    if offtake_type == "trophy" and price_value <= 0:
        errors["price_value"] = "Trophy offtake records should include a value greater than R0.00."
    return errors


def validate_staff_note_form(form_data):
    errors = {}
    if not form_data.get("note_date"):
        errors["note_date"] = "Note date is required."
    if not (form_data.get("staff_member") or "").strip():
        errors["staff_member"] = "Staff member is required."
    if not (form_data.get("subject") or "").strip():
        errors["subject"] = "Subject is required."
    if not (form_data.get("details") or "").strip():
        errors["details"] = "Details are required."

    status = (form_data.get("status") or "open").strip().lower()
    if status not in {"open", "resolved", "monitoring"}:
        errors["status"] = "Invalid staff note status selected."
    return errors


def validate_maintenance_note_form(form_data):
    errors = {}
    if not form_data.get("note_date"):
        errors["note_date"] = "Note date is required."
    if not (form_data.get("asset_or_area") or "").strip():
        errors["asset_or_area"] = "Asset or area is required."
    if not (form_data.get("details") or "").strip():
        errors["details"] = "Details are required."

    priority = (form_data.get("priority") or "medium").strip().lower()
    if priority not in {"low", "medium", "high"}:
        errors["priority"] = "Invalid maintenance priority selected."

    status = (form_data.get("status") or "open").strip().lower()
    if status not in {"open", "in_progress", "completed"}:
        errors["status"] = "Invalid maintenance status selected."

    note_date = parse_date(form_data.get("note_date"))
    completed_date_raw = form_data.get("completed_date")
    completed_date = parse_date(completed_date_raw)
    if completed_date_raw and not completed_date:
        errors["completed_date"] = "Completed date is invalid."
    if note_date and completed_date and completed_date < note_date:
        errors["completed_date"] = "Completed date cannot be before the note date."
    if status == "completed" and not completed_date_raw:
        errors["completed_date"] = "Completed maintenance notes must include a completed date."
    return errors


def render_wildlife_offtake_page(item=None, q="", form_values=None, form_errors=None):
    return render_template(
        "wildlife_offtake.html",
        items=WildlifeOfftakeRecord.query.filter_by(is_deleted=False).order_by(WildlifeOfftakeRecord.date.desc(), WildlifeOfftakeRecord.id.desc()).all(),
        q=q,
        item=item,
        form_values=form_values or {},
        form_errors=form_errors or {},
        form_submitted=bool(form_values),
        camps=Camp.query.filter_by(is_deleted=False).order_by(Camp.name).all(),
        species_items=WildlifeSpecies.query.filter_by(is_deleted=False, active=True).order_by(WildlifeSpecies.common_name).all(),
        bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.booking_reference).all(),
        hunters=HunterProfile.query.filter_by(is_deleted=False).order_by(HunterProfile.full_name).all(),
    )


def render_staff_notes_page(item=None, q="", form_values=None, form_errors=None):
    return render_template(
        "staff_notes.html",
        items=StaffNote.query.filter_by(is_deleted=False).order_by(StaffNote.note_date.desc(), StaffNote.id.desc()).all(),
        q=q,
        item=item,
        form_values=form_values or {},
        form_errors=form_errors or {},
        form_submitted=bool(form_values),
        camps=Camp.query.filter_by(is_deleted=False).order_by(Camp.name).all(),
    )


def render_maintenance_notes_page(item=None, q="", form_values=None, form_errors=None):
    return render_template(
        "maintenance_notes.html",
        items=MaintenanceNote.query.filter_by(is_deleted=False).order_by(MaintenanceNote.note_date.desc(), MaintenanceNote.id.desc()).all(),
        q=q,
        item=item,
        form_values=form_values or {},
        form_errors=form_errors or {},
        form_submitted=bool(form_values),
        camps=Camp.query.filter_by(is_deleted=False).order_by(Camp.name).all(),
    )


def render_module_report_page(title, intro, report_tables, filters=None):
    return render_template(
        "module_reports.html",
        title=title,
        report_title=title,
        report_intro=intro,
        report_tables=report_tables,
        filters=filters or {},
    )


def calculate_booking_totals(booking):
    days = max(parse_int_value(booking.number_of_hunting_days, 0), 0)
    hunters = max(parse_int_value(booking.number_of_hunters, 0), 0)
    day_fee = parse_money_value(booking.day_fee_per_hunter)
    staff_fee = parse_money_value(booking.staff_fee_per_day)
    guide_fee = parse_money_value(booking.guide_fee_per_day)
    tracker_fee = parse_money_value(booking.tracker_fee_per_day)
    skinner_fee = parse_money_value(booking.skinner_fee_per_day)
    extras_total = parse_money_value(booking.extras_total)
    deposit_paid = parse_money_value(booking.deposit_paid)

    hunting_day_fees_total = days * hunters * day_fee
    staff_fees_total = days * (staff_fee + guide_fee + tracker_fee + skinner_fee)

    accommodation_total = 0.0
    if booking.accommodation_required:
        nights = max(parse_int_value(booking.accommodation_nights, 0), 0)
        people = max(parse_int_value(booking.accommodation_people, 0), 0)
        rate = parse_money_value(booking.accommodation_rate_per_person_per_night)
        accommodation_total = nights * people * rate

    animals_shot_total = 0.0
    for log in HuntingLog.query.filter_by(booking_id=booking.id, is_deleted=False).all():
        if (log.outcome or "").lower() == "shot":
            quantity = max(parse_int_value(log.number_animals, 1), 1)
            animals_shot_total += parse_money_value(log.price_charged) * quantity

    grand_total = hunting_day_fees_total + staff_fees_total + accommodation_total + animals_shot_total + extras_total
    balance_due = grand_total - deposit_paid

    return {
        "hunting_day_fees_total": hunting_day_fees_total,
        "staff_fees_total": staff_fees_total,
        "accommodation_total": accommodation_total,
        "animals_shot_total": animals_shot_total,
        "extras_total": extras_total,
        "grand_total": grand_total,
        "balance_due": balance_due,
    }


def apply_booking_totals(booking):
    calculated = calculate_booking_totals(booking)
    booking.hunting_day_fees_total = calculated["hunting_day_fees_total"]
    booking.staff_fees_total = calculated["staff_fees_total"]
    booking.accommodation_total = calculated["accommodation_total"]
    booking.animals_shot_total = calculated["animals_shot_total"]
    booking.grand_total = calculated["grand_total"]
    booking.balance_due = calculated["balance_due"]

    def final_value(calculated_value, override_value):
        if booking.fee_override_enabled and override_value is not None and parse_money_value(override_value) > 0:
            return parse_money_value(override_value)
        return calculated_value

    booking.final_hunting_day_fees_total = final_value(calculated["hunting_day_fees_total"], booking.override_hunting_day_fees_total)
    booking.final_staff_fees_total = final_value(calculated["staff_fees_total"], booking.override_staff_fees_total)
    booking.final_accommodation_total = final_value(calculated["accommodation_total"], booking.override_accommodation_total)
    booking.final_animals_shot_total = final_value(calculated["animals_shot_total"], booking.override_animals_shot_total)
    booking.final_extras_total = final_value(calculated["extras_total"], booking.override_extras_total)

    booking.final_grand_total = final_value(
        booking.final_hunting_day_fees_total
        + booking.final_staff_fees_total
        + booking.final_accommodation_total
        + booking.final_animals_shot_total
        + booking.final_extras_total,
        booking.override_grand_total,
    )
    booking.final_balance_due = max(booking.final_grand_total - parse_money_value(booking.deposit_paid), 0)
    if parse_money_value(booking.deposit_paid) >= parse_money_value(booking.final_grand_total):
        booking.payment_status = "paid"
    elif parse_money_value(booking.deposit_paid) > 0:
        booking.payment_status = "partial"
    else:
        booking.payment_status = "unpaid"


def validate_booking_business_rules(form_data):
    date_from = form_data.get("date_from")
    date_to = form_data.get("date_to")
    from_date = parse_date(date_from)
    to_date = parse_date(date_to)
    if from_date and to_date and to_date < from_date:
        return "End date cannot be before start date."

    hunting_days = parse_int_value(form_data.get("number_of_hunting_days"), 1)
    hunters = parse_int_value(form_data.get("number_of_hunters"), 1)
    if hunting_days < 1:
        return "Hunting days must be at least 1."
    if hunters < 1:
        return "Number of hunters must be at least 1."

    if from_date and to_date:
        available_days = (to_date - from_date).days + 1
        if hunting_days > available_days:
            return "Hunting days cannot exceed the selected booking date range."

    accommodation_required = form_data.get("accommodation_required") == "on"
    if accommodation_required:
        nights = parse_int_value(form_data.get("accommodation_nights"), 0)
        people = parse_int_value(form_data.get("accommodation_people"), 0)
        rate = parse_money_value(form_data.get("accommodation_rate_per_person_per_night"))
        if nights < 1:
            return "Accommodation nights must be at least 1 when accommodation is required."
        if people < 1:
            return "Accommodation people must be at least 1 when accommodation is required."
        if rate <= 0:
            return "Accommodation rate must be greater than 0 when accommodation is required."

    fee_override_enabled = form_data.get("fee_override_enabled") == "on"
    override_notes = (form_data.get("override_notes") or "").strip()
    if fee_override_enabled and not override_notes:
        return "Override reason is required when manual override is enabled."

    if parse_money_value(form_data.get("deposit_paid")) < 0:
        return "Deposit paid cannot be negative."
    return None


def recalculate_booking_if_exists(booking_id):
    parsed_booking_id = parse_int_value(booking_id, 0)
    if parsed_booking_id <= 0:
        return
    booking = HuntingBooking.query.get(parsed_booking_id)
    if booking and not booking.is_deleted:
        apply_booking_totals(booking)


def allowed_image_extension(filename):
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def valid_image_signature(file_storage):
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if header.startswith(b"\xff\xd8\xff"):
        return True
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if header.startswith(b"RIFF") and b"WEBP" in header:
        return True
    return False


def validate_uploaded_photo(file_storage):
    if not file_storage or not file_storage.filename:
        return "No photo selected."
    if not allowed_image_extension(file_storage.filename):
        return "Invalid file type. Only jpg, jpeg, png and webp are allowed."
    if file_storage.mimetype not in ALLOWED_IMAGE_MIME_TYPES:
        return "Invalid image MIME type."

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > app.config["MAX_CONTENT_LENGTH"]:
        return "File is too large. Maximum allowed size is 5MB."
    if not valid_image_signature(file_storage):
        return "Uploaded file content is not a valid image."
    return None


def allowed_indemnity_extension(filename):
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_INDEMNITY_EXTENSIONS


def validate_uploaded_indemnity(file_storage):
    if not file_storage or not file_storage.filename:
        return "No indemnity file selected."
    if not allowed_indemnity_extension(file_storage.filename):
        return "Invalid indemnity file type. Allowed: pdf, jpg, jpeg, png, webp."
    if file_storage.mimetype not in ALLOWED_INDEMNITY_MIME_TYPES:
        return "Invalid indemnity file MIME type."

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > app.config["MAX_CONTENT_LENGTH"]:
        return "Indemnity file is too large. Maximum allowed size is 5MB."

    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if file_storage.mimetype == "application/pdf" and not header.startswith(b"%PDF"):
        return "Uploaded file content is not a valid PDF."
    if file_storage.mimetype in ALLOWED_IMAGE_MIME_TYPES and not valid_image_signature(file_storage):
        return "Uploaded file content is not a valid image."
    return None


def save_uploaded_indemnity(file_storage, indemnity_id):
    ext = secure_filename(file_storage.filename).rsplit(".", 1)[1].lower()
    filename = f"indemnity_{indemnity_id}_{uuid.uuid4().hex}.{ext}"
    target_path = os.path.join(INDEMNITY_UPLOAD_FOLDER, filename)
    file_storage.save(target_path)
    return filename


def save_uploaded_photo(file_storage, animal_id):
    ext = secure_filename(file_storage.filename).rsplit(".", 1)[1].lower()
    filename = f"animal_{animal_id}_{uuid.uuid4().hex}.{ext}"
    target_path = os.path.join(ANIMAL_UPLOAD_FOLDER, filename)
    file_storage.save(target_path)
    return filename


def run_startup_migrations():
    inspector = inspect(db.engine)
    if "animal" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("animal")}
        if "main_photo_path" not in columns:
            db.session.execute(text("ALTER TABLE animal ADD COLUMN main_photo_path VARCHAR(255)"))
            db.session.commit()

    if "hunting_booking" in inspector.get_table_names():
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_hunting_booking_status ON hunting_booking (status)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_hunting_booking_date_from ON hunting_booking (date_from)"))
        booking_columns = {column["name"] for column in inspector.get_columns("hunting_booking")}
        booking_column_defs = {
            "number_of_hunting_days": "INTEGER DEFAULT 1",
            "day_fee_per_hunter": "NUMERIC(12,2) DEFAULT 0",
            "staff_fee_per_day": "NUMERIC(12,2) DEFAULT 0",
            "guide_fee_per_day": "NUMERIC(12,2) DEFAULT 0",
            "tracker_fee_per_day": "NUMERIC(12,2) DEFAULT 0",
            "skinner_fee_per_day": "NUMERIC(12,2) DEFAULT 0",
            "accommodation_nights": "INTEGER DEFAULT 0",
            "accommodation_people": "INTEGER DEFAULT 0",
            "accommodation_rate_per_person_per_night": "NUMERIC(12,2) DEFAULT 0",
            "accommodation_total": "NUMERIC(12,2) DEFAULT 0",
            "hunting_day_fees_total": "NUMERIC(12,2) DEFAULT 0",
            "staff_fees_total": "NUMERIC(12,2) DEFAULT 0",
            "extras_total": "NUMERIC(12,2) DEFAULT 0",
            "animals_shot_total": "NUMERIC(12,2) DEFAULT 0",
            "grand_total": "NUMERIC(12,2) DEFAULT 0",
            "deposit_paid": "NUMERIC(12,2) DEFAULT 0",
            "balance_due": "NUMERIC(12,2) DEFAULT 0",
            "payment_status": "VARCHAR(20) DEFAULT 'unpaid'",
            "fee_override_enabled": "BOOLEAN DEFAULT 0",
            "override_notes": "TEXT",
            "override_hunting_day_fees_total": "NUMERIC(12,2) DEFAULT 0",
            "override_staff_fees_total": "NUMERIC(12,2) DEFAULT 0",
            "override_accommodation_total": "NUMERIC(12,2) DEFAULT 0",
            "override_animals_shot_total": "NUMERIC(12,2) DEFAULT 0",
            "override_extras_total": "NUMERIC(12,2) DEFAULT 0",
            "override_grand_total": "NUMERIC(12,2) DEFAULT 0",
            "final_hunting_day_fees_total": "NUMERIC(12,2) DEFAULT 0",
            "final_staff_fees_total": "NUMERIC(12,2) DEFAULT 0",
            "final_accommodation_total": "NUMERIC(12,2) DEFAULT 0",
            "final_animals_shot_total": "NUMERIC(12,2) DEFAULT 0",
            "final_extras_total": "NUMERIC(12,2) DEFAULT 0",
            "final_grand_total": "NUMERIC(12,2) DEFAULT 0",
            "final_balance_due": "NUMERIC(12,2) DEFAULT 0",
        }
        for col_name, col_def in booking_column_defs.items():
            if col_name not in booking_columns:
                db.session.execute(text(f"ALTER TABLE hunting_booking ADD COLUMN {col_name} {col_def}"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_hunting_booking_payment_status ON hunting_booking (payment_status)"))
        db.session.commit()

    if "hunter_profile" in inspector.get_table_names():
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_hunter_profile_full_name ON hunter_profile (full_name)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_hunter_profile_identity ON hunter_profile (id_or_passport_number)"))
        db.session.commit()

    if "hunting_indemnity" in inspector.get_table_names():
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_hunting_indemnity_status ON hunting_indemnity (status)"))
        indemnity_columns = {column["name"] for column in inspector.get_columns("hunting_indemnity")}
        indemnity_column_defs = {
            "indemnity_file_path": "VARCHAR(255)",
            "witness_or_staff_member": "VARCHAR(120)",
        }
        for col_name, col_def in indemnity_column_defs.items():
            if col_name not in indemnity_columns:
                db.session.execute(text(f"ALTER TABLE hunting_indemnity ADD COLUMN {col_name} {col_def}"))
        db.session.commit()

    if "wildlife_species" in inspector.get_table_names():
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_wildlife_species_common_name ON wildlife_species (common_name)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_wildlife_species_category ON wildlife_species (category)"))
        db.session.commit()

    if "wildlife_count" in inspector.get_table_names():
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_wildlife_count_date ON wildlife_count (count_date)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_wildlife_count_camp ON wildlife_count (camp_id)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_wildlife_count_species ON wildlife_count (species_id)"))
        db.session.commit()

    if "wildlife_offtake_record" in inspector.get_table_names():
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_wildlife_offtake_date ON wildlife_offtake_record (date)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_wildlife_offtake_species ON wildlife_offtake_record (species_id)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_wildlife_offtake_camp ON wildlife_offtake_record (camp_id)"))
        db.session.commit()

    if "staff_note" in inspector.get_table_names():
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_staff_note_date ON staff_note (note_date)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_staff_note_status ON staff_note (status)"))
        db.session.commit()

    if "maintenance_note" in inspector.get_table_names():
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_maintenance_note_date ON maintenance_note (note_date)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_maintenance_note_status ON maintenance_note (status)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_maintenance_note_priority ON maintenance_note (priority)"))
        db.session.commit()


@app.before_request
def ensure_user_session():
    if request.path.startswith("/static") or request.path in PUBLIC_PATHS:
        return None
    if not current_user():
        session.clear()
        flash("Please sign in to continue.")
        return redirect(url_for("login", next=request.path))
    return None


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.errorhandler(413)
def request_entity_too_large(error):
    flash("File too large. Maximum upload size is 5MB.")
    return redirect(request.referrer or url_for("animals_list"))


@app.route("/set-role/<role>")
def set_role_route(role):
    if role in {"Admin", "Farm Manager"}:
        session["role"] = role
    return redirect(request.referrer or url_for("dashboard"))


def verify_password(stored_password, password):
    if not stored_password or not password:
        return False
    # Backward compatibility: allow legacy plain-text passwords and upgrade later.
    if stored_password == password:
        return True
    try:
        return check_password_hash(stored_password, password)
    except ValueError:
        return stored_password == password


@app.route("/login", methods=["GET", "POST"])
def login():
    users = User.query.filter_by(is_active=True).all()
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()
        if user and verify_password(user.password, password):
            if user.password == password:
                user.password = generate_password_hash(password)
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            session.clear()
            session["user_id"] = user.id
            flash(f"Signed in as {user.full_name}")
            next_page = request.form.get("next") or request.args.get("next")
            if next_page and next_page.startswith("/"):
                return redirect(next_page)
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.")
    return render_template("login.html", users=users)


@app.route("/logout")
def logout():
    session.clear()
    flash("Signed out.")
    return redirect(url_for("login"))


@app.route("/switch-user/<int:user_id>")
def switch_user(user_id):
    role_check = require_role("admin")
    if role_check:
        return role_check
    user = db.session.get(User, user_id)
    if user and user.is_active:
        session["user_id"] = user.id
        flash(f"Switched to {user.full_name}")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/")
@app.route("/dashboard")
def dashboard():
    animals = Animal.query.filter_by(is_deleted=False).all()
    camps = Camp.query.filter_by(is_deleted=False).all()
    groups = LivestockGroup.query.filter_by(is_deleted=False).all()
    tasks = Task.query.filter_by(is_deleted=False).all()
    health_records = HealthRecord.query.filter_by(is_deleted=False).all()
    movements = Movement.query.filter_by(is_deleted=False).order_by(Movement.id.desc()).limit(5).all()
    births = BirthRecord.query.filter_by(is_deleted=False).order_by(BirthRecord.id.desc()).limit(5).all()
    deaths = DeathLossRecord.query.filter_by(is_deleted=False).order_by(DeathLossRecord.id.desc()).limit(5).all()
    sales = SalePurchaseRecord.query.filter_by(is_deleted=False).order_by(SalePurchaseRecord.id.desc()).limit(5).all()
    activities = ActivityLog.query.order_by(ActivityLog.id.desc()).limit(8).all()

    total_by_species = {species: sum(1 for animal in animals if animal.species == species) for species in ["cattle", "sheep", "goat"]}
    by_status = {status: sum(1 for animal in animals if animal.status == status) for status in ["active", "sold", "dead", "missing", "culled"]}
    camp_totals = [{"camp": camp, "count": sum(1 for animal in animals if animal.camp_id == camp.id)} for camp in camps]

    upcoming_tasks = [task for task in tasks if task.status != "done" and task.due_date and task.due_date >= date.today().isoformat()]
    overdue_tasks = [task for task in tasks if task.status != "done" and task.due_date and task.due_date < date.today().isoformat()]
    active_treatments = [record for record in health_records if record.next_due_date and record.next_due_date >= date.today().isoformat()]

    return render_template(
        "dashboard.html",
        title="Dashboard",
        animals=animals,
        camps=camps,
        groups=groups,
        tasks=tasks,
        total_by_species=total_by_species,
        by_status=by_status,
        camp_totals=camp_totals,
        upcoming_tasks=upcoming_tasks,
        overdue_tasks=overdue_tasks,
        active_treatments=active_treatments,
        movements=movements,
        births=births,
        deaths=deaths,
        sales=sales,
        activities=activities,
    )


@app.route("/animals")
def animals_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "")
    query = Animal.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(Animal.tag_number.contains(q) | Animal.breed.contains(q) | Animal.notes.contains(q))
    if status_filter:
        query = query.filter(Animal.status == status_filter)
    animals = query.order_by(Animal.tag_number).all()
    camps = Camp.query.filter_by(is_deleted=False).all()
    return render_template("animals.html", animals=animals, camps=camps, q=q, status_filter=status_filter, item=None)


@app.route("/animals/new", methods=["GET", "POST"])
def animals_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        main_photo = request.files.get("main_photo")
        if main_photo and main_photo.filename:
            upload_error = validate_uploaded_photo(main_photo)
            if upload_error:
                flash(upload_error)
                return render_template("animals.html", animals=Animal.query.filter_by(is_deleted=False).all(), camps=Camp.query.filter_by(is_deleted=False).all(), q="", status_filter="", item=None)

        user_id = current_user().id
        animal = Animal(
            tag_number=request.form.get("tag_number"),
            species=request.form.get("species"),
            breed=request.form.get("breed"),
            sex=request.form.get("sex"),
            dob_or_age=request.form.get("dob_or_age"),
            colour_markings=request.form.get("colour_markings"),
            camp_id=request.form.get("camp_id") or None,
            category=request.form.get("category"),
            status=request.form.get("status") or "active",
            purchase_date=request.form.get("purchase_date"),
            purchase_source=request.form.get("purchase_source"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(animal, user_id)
        db.session.add(animal)
        db.session.commit()

        if main_photo and main_photo.filename:
            filename = save_uploaded_photo(main_photo, animal.id)
            animal.main_photo_path = filename
            db.session.add(AnimalPhoto(animal_id=animal.id, file_path=filename, caption="Main profile photo", uploaded_by_user_id=user_id, is_primary=True))
            db.session.commit()

        log_activity("create", "animal", animal.id, f"Created animal {animal.tag_number}")
        flash("Animal record created.")
        return redirect(url_for("animals_list"))
    return render_template("animals.html", animals=Animal.query.filter_by(is_deleted=False).all(), camps=Camp.query.filter_by(is_deleted=False).all(), q="", status_filter="", item=None)


@app.route("/animals/<int:animal_id>/edit", methods=["GET", "POST"])
def animals_edit(animal_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    animal = Animal.query.get_or_404(animal_id)
    if request.method == "POST":
        main_photo = request.files.get("main_photo")
        if main_photo and main_photo.filename:
            upload_error = validate_uploaded_photo(main_photo)
            if upload_error:
                flash(upload_error)
                return render_template("animals.html", animals=Animal.query.filter_by(is_deleted=False).all(), camps=Camp.query.filter_by(is_deleted=False).all(), q="", status_filter="", item=animal)

        animal.tag_number = request.form.get("tag_number")
        animal.species = request.form.get("species")
        animal.breed = request.form.get("breed")
        animal.sex = request.form.get("sex")
        animal.dob_or_age = request.form.get("dob_or_age")
        animal.colour_markings = request.form.get("colour_markings")
        animal.camp_id = request.form.get("camp_id") or None
        animal.category = request.form.get("category")
        animal.status = request.form.get("status") or "active"
        animal.purchase_date = request.form.get("purchase_date")
        animal.purchase_source = request.form.get("purchase_source")
        animal.notes = request.form.get("notes")
        set_audit_fields(animal, current_user().id)

        if main_photo and main_photo.filename:
            filename = save_uploaded_photo(main_photo, animal.id)
            for photo in animal.photos:
                photo.is_primary = False
            animal.main_photo_path = filename
            db.session.add(AnimalPhoto(animal_id=animal.id, file_path=filename, caption="Main profile photo", uploaded_by_user_id=current_user().id, is_primary=True))

        db.session.commit()
        log_activity("update", "animal", animal.id, f"Updated animal {animal.tag_number}")
        flash("Animal record updated.")
        return redirect(url_for("animals_list"))
    return render_template("animals.html", animals=Animal.query.filter_by(is_deleted=False).all(), camps=Camp.query.filter_by(is_deleted=False).all(), q="", status_filter="", item=animal)


@app.route("/animals/<int:animal_id>/delete", methods=["POST"])
def animals_delete(animal_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    animal = Animal.query.get_or_404(animal_id)
    archive_record(animal, current_user().id)
    db.session.commit()
    log_activity("archive", "animal", animal.id, f"Archived animal {animal.tag_number}")
    flash("Animal archived.")
    return redirect(url_for("animals_list"))


@app.route("/animals/<int:animal_id>/photos/file/<path:filename>")
def animal_photo_file(animal_id, filename):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    animal = Animal.query.get_or_404(animal_id)
    allowed_files = {photo.file_path for photo in animal.photos}
    if animal.main_photo_path:
        allowed_files.add(animal.main_photo_path)
    if filename not in allowed_files:
        abort(404)
    return send_from_directory(ANIMAL_UPLOAD_FOLDER, filename)


@app.route("/animals/<int:animal_id>/photos", methods=["POST"])
def animal_photo_upload(animal_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    animal = Animal.query.get_or_404(animal_id)
    photo_file = request.files.get("photo")
    upload_error = validate_uploaded_photo(photo_file)
    if upload_error:
        flash(upload_error)
        return redirect(url_for("animal_detail", animal_id=animal.id))

    filename = save_uploaded_photo(photo_file, animal.id)
    make_primary = request.form.get("is_primary") == "on" or not animal.main_photo_path
    if make_primary:
        for photo in animal.photos:
            photo.is_primary = False
        animal.main_photo_path = filename

    photo = AnimalPhoto(
        animal_id=animal.id,
        file_path=filename,
        caption=request.form.get("caption"),
        uploaded_by_user_id=current_user().id,
        is_primary=make_primary,
    )
    db.session.add(photo)
    db.session.commit()
    log_activity("create", "animal_photo", photo.id, f"Uploaded photo for animal {animal.tag_number}")
    flash("Photo uploaded successfully.")
    return redirect(url_for("animal_detail", animal_id=animal.id))


@app.route("/animals/<int:animal_id>/photos/<int:photo_id>/set-primary", methods=["POST"])
def animal_photo_set_primary(animal_id, photo_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    animal = Animal.query.get_or_404(animal_id)
    photo = AnimalPhoto.query.get_or_404(photo_id)
    if photo.animal_id != animal.id:
        abort(404)

    for item in animal.photos:
        item.is_primary = item.id == photo.id
    animal.main_photo_path = photo.file_path
    db.session.commit()
    log_activity("update", "animal_photo", photo.id, f"Set primary photo for animal {animal.tag_number}")
    flash("Primary photo updated.")
    return redirect(url_for("animal_detail", animal_id=animal.id))


@app.route("/animals/<int:animal_id>/photos/<int:photo_id>/delete", methods=["POST"])
def animal_photo_delete(animal_id, photo_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    animal = Animal.query.get_or_404(animal_id)
    photo = AnimalPhoto.query.get_or_404(photo_id)
    if photo.animal_id != animal.id:
        abort(404)

    if photo.file_path:
        file_to_delete = os.path.join(ANIMAL_UPLOAD_FOLDER, photo.file_path)
        if os.path.exists(file_to_delete):
            os.remove(file_to_delete)

    removed_primary = animal.main_photo_path == photo.file_path
    db.session.delete(photo)
    db.session.commit()

    if removed_primary:
        replacement = AnimalPhoto.query.filter_by(animal_id=animal.id).order_by(AnimalPhoto.uploaded_at.desc()).first()
        animal.main_photo_path = replacement.file_path if replacement else None
        if replacement:
            replacement.is_primary = True
        db.session.commit()

    log_activity("delete", "animal_photo", photo_id, f"Deleted photo for animal {animal.tag_number}")
    flash("Photo deleted.")
    return redirect(url_for("animal_detail", animal_id=animal.id))


@app.route("/groups")
def groups_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    species_filter = request.args.get("species", "")
    query = LivestockGroup.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(LivestockGroup.name.contains(q) | LivestockGroup.notes.contains(q))
    if species_filter:
        query = query.filter(LivestockGroup.species == species_filter)
    groups = query.order_by(LivestockGroup.name).all()
    camps = Camp.query.filter_by(is_deleted=False).all()
    return render_template("groups.html", groups=groups, camps=camps, q=q, species_filter=species_filter, item=None)


@app.route("/groups/new", methods=["GET", "POST"])
def groups_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        group = LivestockGroup(
            name=request.form.get("name"),
            species=request.form.get("species"),
            number_of_animals=request.form.get("number_of_animals") or 0,
            camp_id=request.form.get("camp_id") or None,
            age_class=request.form.get("age_class"),
            purpose=request.form.get("purpose"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(group, current_user().id)
        db.session.add(group)
        db.session.commit()
        log_activity("create", "group", group.id, f"Created group {group.name}")
        flash("Group record created.")
        return redirect(url_for("groups_list"))
    return render_template("groups.html", groups=LivestockGroup.query.filter_by(is_deleted=False).all(), camps=Camp.query.filter_by(is_deleted=False).all(), q="", species_filter="", item=None)


@app.route("/groups/<int:group_id>/edit", methods=["GET", "POST"])
def groups_edit(group_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    group = LivestockGroup.query.get_or_404(group_id)
    if request.method == "POST":
        group.name = request.form.get("name")
        group.species = request.form.get("species")
        group.number_of_animals = request.form.get("number_of_animals") or 0
        group.camp_id = request.form.get("camp_id") or None
        group.age_class = request.form.get("age_class")
        group.purpose = request.form.get("purpose")
        group.notes = request.form.get("notes")
        set_audit_fields(group, current_user().id)
        db.session.commit()
        log_activity("update", "group", group.id, f"Updated group {group.name}")
        flash("Group record updated.")
        return redirect(url_for("groups_list"))
    return render_template("groups.html", groups=LivestockGroup.query.filter_by(is_deleted=False).all(), camps=Camp.query.filter_by(is_deleted=False).all(), q="", species_filter="", item=group)


@app.route("/groups/<int:group_id>/delete", methods=["POST"])
def groups_delete(group_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    group = LivestockGroup.query.get_or_404(group_id)
    archive_record(group, current_user().id)
    db.session.commit()
    log_activity("archive", "group", group.id, f"Archived group {group.name}")
    flash("Group archived.")
    return redirect(url_for("groups_list"))


@app.route("/camps")
def camps_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = Camp.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(Camp.name.contains(q) | Camp.notes.contains(q))
    camps = query.order_by(Camp.name).all()
    return render_template("camps.html", camps=camps, q=q, item=None)


@app.route("/camps/new", methods=["GET", "POST"])
def camps_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        camp = Camp(
            name=request.form.get("name"),
            size=request.form.get("size"),
            water_status=request.form.get("water_status"),
            grazing_condition=request.form.get("grazing_condition"),
            livestock_count=request.form.get("livestock_count") or 0,
            last_movement_date=request.form.get("last_movement_date"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(camp, current_user().id)
        db.session.add(camp)
        db.session.commit()
        log_activity("create", "camp", camp.id, f"Created camp {camp.name}")
        flash("Camp created.")
        return redirect(url_for("camps_list"))
    return render_template("camps.html", camps=Camp.query.filter_by(is_deleted=False).all(), q="", item=None)


@app.route("/camps/<int:camp_id>/edit", methods=["GET", "POST"])
def camps_edit(camp_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    camp = Camp.query.get_or_404(camp_id)
    if request.method == "POST":
        camp.name = request.form.get("name")
        camp.size = request.form.get("size")
        camp.water_status = request.form.get("water_status")
        camp.grazing_condition = request.form.get("grazing_condition")
        camp.livestock_count = request.form.get("livestock_count") or 0
        camp.last_movement_date = request.form.get("last_movement_date")
        camp.notes = request.form.get("notes")
        set_audit_fields(camp, current_user().id)
        db.session.commit()
        log_activity("update", "camp", camp.id, f"Updated camp {camp.name}")
        flash("Camp updated.")
        return redirect(url_for("camps_list"))
    return render_template("camps.html", camps=Camp.query.filter_by(is_deleted=False).all(), q="", item=camp)


@app.route("/camps/<int:camp_id>/delete", methods=["POST"])
def camps_delete(camp_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    camp = Camp.query.get_or_404(camp_id)
    archive_record(camp, current_user().id)
    db.session.commit()
    log_activity("archive", "camp", camp.id, f"Archived camp {camp.name}")
    flash("Camp archived.")
    return redirect(url_for("camps_list"))


@app.route("/movements")
def movements_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = Movement.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(Movement.subject_name.contains(q) | Movement.reason.contains(q))
    movements = query.order_by(Movement.date.desc()).all()
    camps = Camp.query.filter_by(is_deleted=False).all()
    return render_template("movements.html", movements=movements, camps=camps, q=q, item=None)


@app.route("/movements/new", methods=["GET", "POST"])
def movements_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        movement = Movement(
            date=request.form.get("date"),
            from_camp_id=request.form.get("from_camp_id") or None,
            to_camp_id=request.form.get("to_camp_id") or None,
            subject_name=request.form.get("subject_name"),
            number_moved=request.form.get("number_moved") or 1,
            reason=request.form.get("reason"),
            person_responsible=request.form.get("person_responsible"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(movement, current_user().id)
        db.session.add(movement)
        db.session.commit()
        log_activity("create", "movement", movement.id, f"Logged movement {movement.subject_name}")
        flash("Movement logged.")
        return redirect(url_for("movements_list"))
    return render_template("movements.html", movements=Movement.query.filter_by(is_deleted=False).order_by(Movement.date.desc()).all(), camps=Camp.query.filter_by(is_deleted=False).all(), q="", item=None)


@app.route("/movements/<int:movement_id>/edit", methods=["GET", "POST"])
def movements_edit(movement_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    movement = Movement.query.get_or_404(movement_id)
    if request.method == "POST":
        movement.date = request.form.get("date")
        movement.from_camp_id = request.form.get("from_camp_id") or None
        movement.to_camp_id = request.form.get("to_camp_id") or None
        movement.subject_name = request.form.get("subject_name")
        movement.number_moved = request.form.get("number_moved") or 1
        movement.reason = request.form.get("reason")
        movement.person_responsible = request.form.get("person_responsible")
        movement.notes = request.form.get("notes")
        set_audit_fields(movement, current_user().id)
        db.session.commit()
        log_activity("update", "movement", movement.id, f"Updated movement {movement.subject_name}")
        flash("Movement updated.")
        return redirect(url_for("movements_list"))
    return render_template("movements.html", movements=Movement.query.filter_by(is_deleted=False).order_by(Movement.date.desc()).all(), camps=Camp.query.filter_by(is_deleted=False).all(), q="", item=movement)


@app.route("/movements/<int:movement_id>/delete", methods=["POST"])
def movements_delete(movement_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    movement = Movement.query.get_or_404(movement_id)
    archive_record(movement, current_user().id)
    db.session.commit()
    log_activity("archive", "movement", movement.id, f"Archived movement {movement.subject_name}")
    flash("Movement archived.")
    return redirect(url_for("movements_list"))


@app.route("/health-records")
def health_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = HealthRecord.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(HealthRecord.subject_name.contains(q) | HealthRecord.notes.contains(q))
    records = query.order_by(HealthRecord.date.desc()).all()
    return render_template("health.html", records=records, q=q, item=None)


@app.route("/health-records/new", methods=["GET", "POST"])
def health_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        record = HealthRecord(
            date=request.form.get("date"),
            subject_name=request.form.get("subject_name"),
            treatment_type=request.form.get("treatment_type"),
            product_used=request.form.get("product_used"),
            dosage=request.form.get("dosage"),
            batch_number=request.form.get("batch_number"),
            withdrawal_period=request.form.get("withdrawal_period"),
            next_due_date=request.form.get("next_due_date"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "health_record", record.id, f"Created health record for {record.subject_name}")
        flash("Health record created.")
        return redirect(url_for("health_list"))
    return render_template("health.html", records=HealthRecord.query.filter_by(is_deleted=False).order_by(HealthRecord.date.desc()).all(), q="", item=None)


@app.route("/health-records/<int:record_id>/edit", methods=["GET", "POST"])
def health_edit(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HealthRecord.query.get_or_404(record_id)
    if request.method == "POST":
        record.date = request.form.get("date")
        record.subject_name = request.form.get("subject_name")
        record.treatment_type = request.form.get("treatment_type")
        record.product_used = request.form.get("product_used")
        record.dosage = request.form.get("dosage")
        record.batch_number = request.form.get("batch_number")
        record.withdrawal_period = request.form.get("withdrawal_period")
        record.next_due_date = request.form.get("next_due_date")
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "health_record", record.id, f"Updated health record for {record.subject_name}")
        flash("Health record updated.")
        return redirect(url_for("health_list"))
    return render_template("health.html", records=HealthRecord.query.filter_by(is_deleted=False).order_by(HealthRecord.date.desc()).all(), q="", item=record)


@app.route("/health-records/<int:record_id>/delete", methods=["POST"])
def health_delete(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HealthRecord.query.get_or_404(record_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "health_record", record.id, f"Archived health record for {record.subject_name}")
    flash("Health record archived.")
    return redirect(url_for("health_list"))


@app.route("/breeding")
def breeding_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = BreedingRecord.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(BreedingRecord.female_reference.contains(q) | BreedingRecord.notes.contains(q))
    records = query.order_by(BreedingRecord.date_exposed.desc()).all()
    return render_template("breeding.html", records=records, q=q, item=None)


@app.route("/breeding/new", methods=["GET", "POST"])
def breeding_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        record = BreedingRecord(
            species=request.form.get("species"),
            breeding_season=request.form.get("breeding_season"),
            male_used=request.form.get("male_used"),
            female_reference=request.form.get("female_reference"),
            date_exposed=request.form.get("date_exposed"),
            pregnancy_status=request.form.get("pregnancy_status"),
            expected_birth_date=request.form.get("expected_birth_date"),
            actual_birth_date=request.form.get("actual_birth_date"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "breeding_record", record.id, f"Created breeding record for {record.female_reference}")
        flash("Breeding record created.")
        return redirect(url_for("breeding_list"))
    return render_template("breeding.html", records=BreedingRecord.query.filter_by(is_deleted=False).order_by(BreedingRecord.id.desc()).all(), q="", item=None)


@app.route("/breeding/<int:record_id>/edit", methods=["GET", "POST"])
def breeding_edit(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = BreedingRecord.query.get_or_404(record_id)
    if request.method == "POST":
        record.species = request.form.get("species")
        record.breeding_season = request.form.get("breeding_season")
        record.male_used = request.form.get("male_used")
        record.female_reference = request.form.get("female_reference")
        record.date_exposed = request.form.get("date_exposed")
        record.pregnancy_status = request.form.get("pregnancy_status")
        record.expected_birth_date = request.form.get("expected_birth_date")
        record.actual_birth_date = request.form.get("actual_birth_date")
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "breeding_record", record.id, f"Updated breeding record for {record.female_reference}")
        flash("Breeding record updated.")
        return redirect(url_for("breeding_list"))
    return render_template("breeding.html", records=BreedingRecord.query.filter_by(is_deleted=False).order_by(BreedingRecord.id.desc()).all(), q="", item=record)


@app.route("/breeding/<int:record_id>/delete", methods=["POST"])
def breeding_delete(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = BreedingRecord.query.get_or_404(record_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "breeding_record", record.id, f"Archived breeding record for {record.female_reference}")
    flash("Breeding record archived.")
    return redirect(url_for("breeding_list"))


@app.route("/births")
def births_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = BirthRecord.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(BirthRecord.mother_reference.contains(q) | BirthRecord.notes.contains(q))
    records = query.order_by(BirthRecord.date_born.desc()).all()
    return render_template("births.html", records=records, q=q, item=None)


@app.route("/births/new", methods=["GET", "POST"])
def births_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        record = BirthRecord(
            date_born=request.form.get("date_born"),
            species=request.form.get("species"),
            mother_reference=request.form.get("mother_reference"),
            father_reference=request.form.get("father_reference"),
            number_born=request.form.get("number_born") or 1,
            number_alive=request.form.get("number_alive") or 1,
            number_dead=request.form.get("number_dead") or 0,
            sex_if_known=request.form.get("sex_if_known"),
            tag_numbers_assigned=request.form.get("tag_numbers_assigned"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "birth_record", record.id, f"Created birth record for {record.mother_reference}")
        flash("Birth record created.")
        return redirect(url_for("births_list"))
    return render_template("births.html", records=BirthRecord.query.filter_by(is_deleted=False).order_by(BirthRecord.date_born.desc()).all(), q="", item=None)


@app.route("/births/<int:record_id>/edit", methods=["GET", "POST"])
def births_edit(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = BirthRecord.query.get_or_404(record_id)
    if request.method == "POST":
        record.date_born = request.form.get("date_born")
        record.species = request.form.get("species")
        record.mother_reference = request.form.get("mother_reference")
        record.father_reference = request.form.get("father_reference")
        record.number_born = request.form.get("number_born") or 1
        record.number_alive = request.form.get("number_alive") or 1
        record.number_dead = request.form.get("number_dead") or 0
        record.sex_if_known = request.form.get("sex_if_known")
        record.tag_numbers_assigned = request.form.get("tag_numbers_assigned")
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "birth_record", record.id, f"Updated birth record for {record.mother_reference}")
        flash("Birth record updated.")
        return redirect(url_for("births_list"))
    return render_template("births.html", records=BirthRecord.query.filter_by(is_deleted=False).order_by(BirthRecord.date_born.desc()).all(), q="", item=record)


@app.route("/births/<int:record_id>/delete", methods=["POST"])
def births_delete(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = BirthRecord.query.get_or_404(record_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "birth_record", record.id, f"Archived birth record for {record.mother_reference}")
    flash("Birth record archived.")
    return redirect(url_for("births_list"))


@app.route("/deaths")
def deaths_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = DeathLossRecord.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(DeathLossRecord.subject_name.contains(q) | DeathLossRecord.notes.contains(q))
    records = query.order_by(DeathLossRecord.date.desc()).all()
    camps = Camp.query.filter_by(is_deleted=False).all()
    return render_template("deaths.html", records=records, camps=camps, q=q, item=None)


@app.route("/deaths/new", methods=["GET", "POST"])
def deaths_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        record = DeathLossRecord(
            date=request.form.get("date"),
            subject_name=request.form.get("subject_name"),
            number_lost=request.form.get("number_lost") or 1,
            cause=request.form.get("cause"),
            camp_id=request.form.get("camp_id") or None,
            estimated_value_lost=request.form.get("estimated_value_lost"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "death_loss_record", record.id, f"Created loss record for {record.subject_name}")
        flash("Death or loss record created.")
        return redirect(url_for("deaths_list"))
    return render_template("deaths.html", records=DeathLossRecord.query.filter_by(is_deleted=False).order_by(DeathLossRecord.date.desc()).all(), camps=Camp.query.filter_by(is_deleted=False).all(), q="", item=None)


@app.route("/deaths/<int:record_id>/edit", methods=["GET", "POST"])
def deaths_edit(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = DeathLossRecord.query.get_or_404(record_id)
    if request.method == "POST":
        record.date = request.form.get("date")
        record.subject_name = request.form.get("subject_name")
        record.number_lost = request.form.get("number_lost") or 1
        record.cause = request.form.get("cause")
        record.camp_id = request.form.get("camp_id") or None
        record.estimated_value_lost = request.form.get("estimated_value_lost")
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "death_loss_record", record.id, f"Updated loss record for {record.subject_name}")
        flash("Death or loss record updated.")
        return redirect(url_for("deaths_list"))
    return render_template("deaths.html", records=DeathLossRecord.query.filter_by(is_deleted=False).order_by(DeathLossRecord.date.desc()).all(), camps=Camp.query.filter_by(is_deleted=False).all(), q="", item=record)


@app.route("/deaths/<int:record_id>/delete", methods=["POST"])
def deaths_delete(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = DeathLossRecord.query.get_or_404(record_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "death_loss_record", record.id, f"Archived loss record for {record.subject_name}")
    flash("Death or loss record archived.")
    return redirect(url_for("deaths_list"))


@app.route("/sales")
def sales_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    transaction_type_filter = (request.args.get("transaction_type_filter") or "").strip().lower()
    query = SalePurchaseRecord.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(SalePurchaseRecord.party.contains(q) | SalePurchaseRecord.item_name.contains(q))
    if transaction_type_filter in {"sale", "purchase"}:
        query = query.filter(SalePurchaseRecord.transaction_type == transaction_type_filter)
    records = query.order_by(SalePurchaseRecord.date.desc()).all()
    return render_template("sales.html", records=records, q=q, item=None, transaction_type_filter=transaction_type_filter)


@app.route("/sales/new", methods=["GET", "POST"])
def sales_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    transaction_type_filter = (request.args.get("transaction_type_filter") or "").strip().lower()
    if request.method == "POST":
        record = SalePurchaseRecord(
            date=request.form.get("date"),
            party=request.form.get("party"),
            transaction_type=request.form.get("transaction_type"),
            species=request.form.get("species"),
            item_name=request.form.get("item_name"),
            number=request.form.get("number") or 1,
            weight=request.form.get("weight"),
            price_per_unit=request.form.get("price_per_unit"),
            total_amount=request.form.get("total_amount"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "sale_purchase_record", record.id, f"Created transaction {record.item_name}")
        flash("Transaction created.")
        return redirect(url_for("sales_list", transaction_type_filter=record.transaction_type))
    records_query = SalePurchaseRecord.query.filter_by(is_deleted=False)
    if transaction_type_filter in {"sale", "purchase"}:
        records_query = records_query.filter(SalePurchaseRecord.transaction_type == transaction_type_filter)
    return render_template(
        "sales.html",
        records=records_query.order_by(SalePurchaseRecord.date.desc()).all(),
        q="",
        item=None,
        transaction_type_filter=transaction_type_filter,
    )


@app.route("/sales/<int:record_id>/edit", methods=["GET", "POST"])
def sales_edit(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = SalePurchaseRecord.query.get_or_404(record_id)
    if request.method == "POST":
        record.date = request.form.get("date")
        record.party = request.form.get("party")
        record.transaction_type = request.form.get("transaction_type")
        record.species = request.form.get("species")
        record.item_name = request.form.get("item_name")
        record.number = request.form.get("number") or 1
        record.weight = request.form.get("weight")
        record.price_per_unit = request.form.get("price_per_unit")
        record.total_amount = request.form.get("total_amount")
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "sale_purchase_record", record.id, f"Updated transaction {record.item_name}")
        flash("Transaction updated.")
        return redirect(url_for("sales_list", transaction_type_filter=record.transaction_type))
    transaction_type_filter = (request.args.get("transaction_type_filter") or record.transaction_type or "").strip().lower()
    records_query = SalePurchaseRecord.query.filter_by(is_deleted=False)
    if transaction_type_filter in {"sale", "purchase"}:
        records_query = records_query.filter(SalePurchaseRecord.transaction_type == transaction_type_filter)
    return render_template(
        "sales.html",
        records=records_query.order_by(SalePurchaseRecord.date.desc()).all(),
        q="",
        item=record,
        transaction_type_filter=transaction_type_filter,
    )


@app.route("/sales/<int:record_id>/delete", methods=["POST"])
def sales_delete(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = SalePurchaseRecord.query.get_or_404(record_id)
    transaction_type_filter = record.transaction_type
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "sale_purchase_record", record.id, f"Archived transaction {record.item_name}")
    flash("Transaction archived.")
    return redirect(url_for("sales_list", transaction_type_filter=transaction_type_filter))


@app.route("/tasks")
def tasks_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "")
    query = Task.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(Task.title.contains(q) | Task.description.contains(q) | Task.related_name.contains(q))
    if status_filter:
        query = query.filter(Task.status == status_filter)
    tasks = query.order_by(Task.due_date).all()
    return render_template("tasks.html", tasks=tasks, q=q, status_filter=status_filter, item=None)


@app.route("/tasks/new", methods=["GET", "POST"])
def tasks_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        task = Task(
            title=request.form.get("title"),
            description=request.form.get("description"),
            due_date=request.form.get("due_date"),
            related_name=request.form.get("related_name"),
            priority=request.form.get("priority") or "medium",
            assigned_to=request.form.get("assigned_to"),
            status=request.form.get("status") or "open",
            recurring=request.form.get("recurring"),
        )
        set_audit_fields(task, current_user().id)
        db.session.add(task)
        db.session.commit()
        log_activity("create", "task", task.id, f"Created task {task.title}")
        flash("Task created.")
        return redirect(url_for("tasks_list"))
    return render_template("tasks.html", tasks=Task.query.filter_by(is_deleted=False).order_by(Task.due_date).all(), q="", status_filter="", item=None)


@app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
def tasks_edit(task_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    task = Task.query.get_or_404(task_id)
    if request.method == "POST":
        task.title = request.form.get("title")
        task.description = request.form.get("description")
        task.due_date = request.form.get("due_date")
        task.related_name = request.form.get("related_name")
        task.priority = request.form.get("priority") or "medium"
        task.assigned_to = request.form.get("assigned_to")
        task.status = request.form.get("status") or "open"
        task.recurring = request.form.get("recurring")
        set_audit_fields(task, current_user().id)
        db.session.commit()
        log_activity("update", "task", task.id, f"Updated task {task.title}")
        flash("Task updated.")
        return redirect(url_for("tasks_list"))
    return render_template("tasks.html", tasks=Task.query.filter_by(is_deleted=False).order_by(Task.due_date).all(), q="", status_filter="", item=task)


@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
def tasks_delete(task_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    task = Task.query.get_or_404(task_id)
    archive_record(task, current_user().id)
    db.session.commit()
    log_activity("archive", "task", task.id, f"Archived task {task.title}")
    flash("Task archived.")
    return redirect(url_for("tasks_list"))


@app.route("/livestock")
def livestock_home():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    section_groups = [
        {
            "title": "Livestock Records",
            "description": "Existing livestock functionality remains unchanged and grouped here.",
            "items": [
                {"title": "Animals", "description": "Tag-level livestock records and photos.", "href": url_for("animals_list"), "icon_src": url_for("static", filename="branding/bull-icon.png", v="20260630")},
                {"title": "Groups", "description": "Grouped livestock management by species and purpose.", "href": url_for("groups_list"), "icon": "users"},
                {"title": "Movements", "description": "Track transfers between camps and handling reasons.", "href": url_for("movements_list"), "icon": "route"},
                {"title": "Health", "description": "Treatments, products, withdrawal periods, and follow-ups.", "href": url_for("health_list"), "icon": "stethoscope"},
                {"title": "Breeding", "description": "Exposure, pregnancy status, and breeding seasons.", "href": url_for("breeding_list"), "icon": "sprout"},
                {"title": "Births", "description": "Birth records and newborn tracking.", "href": url_for("births_list"), "icon": "baby"},
                {"title": "Deaths", "description": "Loss tracking and estimated value lost.", "href": url_for("deaths_list"), "icon": "shield-alert"},
                {"title": "Sales", "description": "Sales transactions for livestock and groups.", "href": url_for("sales_list", transaction_type_filter="sale"), "icon": "banknote"},
                {"title": "Purchases", "description": "Purchase transactions kept in the existing sales module.", "href": url_for("sales_list", transaction_type_filter="purchase"), "icon": "shopping-cart"},
            ],
        }
    ]
    return render_template(
        "module_home.html",
        title="Livestock",
        module_title="Livestock",
        module_intro="Manage all existing livestock records without changing the current underlying livestock workflows.",
        action_links=[
            {"label": "Add Animal", "href": url_for("animals_list"), "style": "primary"},
            {"label": "Open Movements", "href": url_for("movements_list"), "style": "outline-secondary"},
        ],
        section_groups=section_groups,
    )


@app.route("/wildlife")
@app.route("/hunting")
def hunting_home():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    section_groups = [
        {
            "title": "Available Now",
            "description": "Current wildlife and hunting workflows already running in the app.",
            "items": [
                {"title": "Hunting Bookings", "description": "Bookings, guests, pricing, and payment status.", "href": url_for("hunting_bookings_list"), "icon": "calendar-check"},
                {"title": "Hunters", "description": "Hunter profiles, licences, and emergency contacts.", "href": url_for("hunting_hunters_list"), "icon": "crosshair"},
                {"title": "Indemnities", "description": "Signed forms and file downloads.", "href": url_for("hunting_indemnities_list"), "icon": "file-check-2"},
                {"title": "Hunting Log", "description": "Shot, wounded, and missed animal records.", "href": url_for("hunting_log_list"), "icon": "clipboard-list"},
                {"title": "Wounded Follow-up", "description": "Open and closed follow-up cases.", "href": url_for("hunting_wounded_list"), "icon": "heart-pulse"},
            ],
        },
        {
            "title": "Wildlife Management",
            "description": "Wildlife-specific data stays separate from livestock and now starts with its own register and counts.",
            "items": [
                {"title": "Species Register", "description": "Dedicated wildlife species master data.", "href": url_for("wildlife_species_list"), "icon": "leaf"},
                {"title": "Game Counts", "description": "Camp-based wildlife count records.", "href": url_for("wildlife_counts_list"), "icon": "binoculars"},
                {"title": "Trophy / Offtake", "description": "Separate offtake and trophy records.", "href": url_for("wildlife_offtake_list"), "icon": "target"},
            ],
        },
    ]
    return render_template(
        "module_home.html",
        title="Wildlife",
        module_title="Wildlife",
        module_intro="Wildlife stays separate from livestock. Current hunting tools are grouped here while wildlife-specific registers and counts are added in later phases.",
        action_links=[
            {"label": "New Booking", "href": url_for("hunting_bookings_new"), "style": "primary"},
            {"label": "Open Game Counts", "href": url_for("wildlife_counts_list"), "style": "outline-secondary"},
        ],
        section_groups=section_groups,
    )


@app.route("/wildlife/species")
def wildlife_species_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = WildlifeSpecies.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(
            WildlifeSpecies.common_name.contains(q)
            | WildlifeSpecies.scientific_name.contains(q)
            | WildlifeSpecies.category.contains(q)
            | WildlifeSpecies.notes.contains(q)
        )
    items = query.order_by(WildlifeSpecies.common_name).all()
    return render_template("wildlife_species.html", items=items, q=q, item=None)


@app.route("/wildlife/species/new", methods=["GET", "POST"])
def wildlife_species_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        record = WildlifeSpecies(
            common_name=request.form.get("common_name"),
            scientific_name=request.form.get("scientific_name"),
            category=request.form.get("category") or "game",
            sex_tracking_required=request.form.get("sex_tracking_required") == "on",
            active=request.form.get("active") == "on",
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "wildlife_species", record.id, f"Created wildlife species {record.common_name}")
        flash("Wildlife species created.")
        return redirect(url_for("wildlife_species_list"))
    return redirect(url_for("wildlife_species_list"))


@app.route("/wildlife/species/<int:item_id>/edit", methods=["GET", "POST"])
def wildlife_species_edit(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = WildlifeSpecies.query.get_or_404(item_id)
    if request.method == "POST":
        record.common_name = request.form.get("common_name")
        record.scientific_name = request.form.get("scientific_name")
        record.category = request.form.get("category") or "game"
        record.sex_tracking_required = request.form.get("sex_tracking_required") == "on"
        record.active = request.form.get("active") == "on"
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "wildlife_species", record.id, f"Updated wildlife species {record.common_name}")
        flash("Wildlife species updated.")
        return redirect(url_for("wildlife_species_list"))
    items = WildlifeSpecies.query.filter_by(is_deleted=False).order_by(WildlifeSpecies.common_name).all()
    return render_template("wildlife_species.html", items=items, q="", item=record)


@app.route("/wildlife/species/<int:item_id>/delete", methods=["POST"])
def wildlife_species_delete(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = WildlifeSpecies.query.get_or_404(item_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "wildlife_species", record.id, f"Archived wildlife species {record.common_name}")
    flash("Wildlife species archived.")
    return redirect(url_for("wildlife_species_list"))


@app.route("/wildlife/counts")
def wildlife_counts_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = WildlifeCount.query.filter_by(is_deleted=False)
    if q:
        query = query.join(WildlifeSpecies, WildlifeCount.species_id == WildlifeSpecies.id).join(Camp, WildlifeCount.camp_id == Camp.id).filter(
            WildlifeSpecies.common_name.contains(q) | Camp.name.contains(q) | WildlifeCount.notes.contains(q)
        )
    items = query.order_by(WildlifeCount.count_date.desc(), WildlifeCount.id.desc()).all()
    return render_template(
        "wildlife_counts.html",
        items=items,
        q=q,
        item=None,
        camps=Camp.query.filter_by(is_deleted=False).order_by(Camp.name).all(),
        species_items=WildlifeSpecies.query.filter_by(is_deleted=False, active=True).order_by(WildlifeSpecies.common_name).all(),
    )


@app.route("/wildlife/counts/new", methods=["GET", "POST"])
def wildlife_counts_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        validation_error = validate_wildlife_count_form(request.form)
        if validation_error:
            flash(validation_error)
            return redirect(url_for("wildlife_counts_list"))

        male_count, female_count, juvenile_count, subtotal, total_count = build_wildlife_count_totals(request.form)
        record = WildlifeCount(
            count_date=request.form.get("count_date"),
            camp_id=request.form.get("camp_id"),
            species_id=request.form.get("species_id"),
            count_method=request.form.get("count_method") or "visual",
            male_count=male_count,
            female_count=female_count,
            juvenile_count=juvenile_count,
            total_count=total_count if request.form.get("total_count") else subtotal,
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "wildlife_count", record.id, f"Created wildlife count for species #{record.species_id} in camp #{record.camp_id}")
        flash("Wildlife count created.")
        return redirect(url_for("wildlife_counts_list"))
    return redirect(url_for("wildlife_counts_list"))


@app.route("/wildlife/counts/<int:item_id>/edit", methods=["GET", "POST"])
def wildlife_counts_edit(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = WildlifeCount.query.get_or_404(item_id)
    if request.method == "POST":
        validation_error = validate_wildlife_count_form(request.form)
        if validation_error:
            flash(validation_error)
            return redirect(url_for("wildlife_counts_edit", item_id=record.id))

        male_count, female_count, juvenile_count, subtotal, total_count = build_wildlife_count_totals(request.form)
        record.count_date = request.form.get("count_date")
        record.camp_id = request.form.get("camp_id")
        record.species_id = request.form.get("species_id")
        record.count_method = request.form.get("count_method") or "visual"
        record.male_count = male_count
        record.female_count = female_count
        record.juvenile_count = juvenile_count
        record.total_count = total_count if request.form.get("total_count") else subtotal
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "wildlife_count", record.id, f"Updated wildlife count {record.id}")
        flash("Wildlife count updated.")
        return redirect(url_for("wildlife_counts_list"))
    items = WildlifeCount.query.filter_by(is_deleted=False).order_by(WildlifeCount.count_date.desc(), WildlifeCount.id.desc()).all()
    return render_template(
        "wildlife_counts.html",
        items=items,
        q="",
        item=record,
        camps=Camp.query.filter_by(is_deleted=False).order_by(Camp.name).all(),
        species_items=WildlifeSpecies.query.filter_by(is_deleted=False, active=True).order_by(WildlifeSpecies.common_name).all(),
    )


@app.route("/wildlife/counts/<int:item_id>/delete", methods=["POST"])
def wildlife_counts_delete(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = WildlifeCount.query.get_or_404(item_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "wildlife_count", record.id, f"Archived wildlife count {record.id}")
    flash("Wildlife count archived.")
    return redirect(url_for("wildlife_counts_list"))


@app.route("/wildlife/offtake")
def wildlife_offtake_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = WildlifeOfftakeRecord.query.filter_by(is_deleted=False)
    if q:
        query = query.join(WildlifeSpecies, WildlifeOfftakeRecord.species_id == WildlifeSpecies.id).join(Camp, WildlifeOfftakeRecord.camp_id == Camp.id).filter(
            WildlifeSpecies.common_name.contains(q) | Camp.name.contains(q) | WildlifeOfftakeRecord.notes.contains(q)
        )
    return render_template(
        "wildlife_offtake.html",
        items=query.order_by(WildlifeOfftakeRecord.date.desc(), WildlifeOfftakeRecord.id.desc()).all(),
        q=q,
        item=None,
        form_values={},
        form_errors={},
        form_submitted=False,
        camps=Camp.query.filter_by(is_deleted=False).order_by(Camp.name).all(),
        species_items=WildlifeSpecies.query.filter_by(is_deleted=False, active=True).order_by(WildlifeSpecies.common_name).all(),
        bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.booking_reference).all(),
        hunters=HunterProfile.query.filter_by(is_deleted=False).order_by(HunterProfile.full_name).all(),
    )


@app.route("/wildlife/offtake/new", methods=["GET", "POST"])
def wildlife_offtake_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        form_errors = validate_wildlife_offtake_form(request.form)
        if form_errors:
            flash("Please correct the highlighted offtake fields.")
            return render_wildlife_offtake_page(form_values=request.form, form_errors=form_errors)

        record = WildlifeOfftakeRecord(
            date=request.form.get("date"),
            camp_id=request.form.get("camp_id"),
            species_id=request.form.get("species_id"),
            booking_id=request.form.get("booking_id") or None,
            hunter_id=request.form.get("hunter_id") or None,
            offtake_type=request.form.get("offtake_type") or "trophy",
            sex=request.form.get("sex") or "unknown",
            age_class=request.form.get("age_class"),
            trophy_score=request.form.get("trophy_score"),
            price_value=parse_money_value(request.form.get("price_value")),
            recovered=request.form.get("recovered") == "on",
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "wildlife_offtake", record.id, f"Created wildlife offtake {record.id}")
        flash("Wildlife offtake record created.")
        return redirect(url_for("wildlife_offtake_list"))
    return redirect(url_for("wildlife_offtake_list"))


@app.route("/wildlife/offtake/<int:item_id>/edit", methods=["GET", "POST"])
def wildlife_offtake_edit(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = WildlifeOfftakeRecord.query.get_or_404(item_id)
    if request.method == "POST":
        form_errors = validate_wildlife_offtake_form(request.form)
        if form_errors:
            flash("Please correct the highlighted offtake fields.")
            return render_wildlife_offtake_page(item=record, form_values=request.form, form_errors=form_errors)

        record.date = request.form.get("date")
        record.camp_id = request.form.get("camp_id")
        record.species_id = request.form.get("species_id")
        record.booking_id = request.form.get("booking_id") or None
        record.hunter_id = request.form.get("hunter_id") or None
        record.offtake_type = request.form.get("offtake_type") or "trophy"
        record.sex = request.form.get("sex") or "unknown"
        record.age_class = request.form.get("age_class")
        record.trophy_score = request.form.get("trophy_score")
        record.price_value = parse_money_value(request.form.get("price_value"))
        record.recovered = request.form.get("recovered") == "on"
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "wildlife_offtake", record.id, f"Updated wildlife offtake {record.id}")
        flash("Wildlife offtake record updated.")
        return redirect(url_for("wildlife_offtake_list"))
    return render_wildlife_offtake_page(item=record)


@app.route("/wildlife/offtake/<int:item_id>/delete", methods=["POST"])
def wildlife_offtake_delete(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = WildlifeOfftakeRecord.query.get_or_404(item_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "wildlife_offtake", record.id, f"Archived wildlife offtake {record.id}")
    flash("Wildlife offtake record archived.")
    return redirect(url_for("wildlife_offtake_list"))


@app.route("/farm-operations")
def farm_operations_home():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    section_groups = [
        {
            "title": "Current Farm Operations",
            "description": "Shared farm tools used across the platform.",
            "items": [
                {"title": "Camps", "description": "Shared camp resource for livestock and wildlife.", "href": url_for("camps_list"), "icon": "map-pinned"},
                {"title": "Tasks", "description": "Operational tasks and follow-ups.", "href": url_for("tasks_list"), "icon": "check-square"},
                {"title": "Daily Diary", "description": "Daily notes, field observations, and incidents.", "href": url_for("diary_list"), "icon": "book-open-text"},
            ],
        },
        {
            "title": "Operations Notes",
            "description": "Operational note-taking modules now live under farm operations.",
            "items": [
                {"title": "Staff Notes", "description": "Team notes and shift observations.", "href": url_for("staff_notes_list"), "icon": "notebook-tabs"},
                {"title": "Maintenance Notes", "description": "Infrastructure and equipment maintenance tracking.", "href": url_for("maintenance_notes_list"), "icon": "wrench"},
            ],
        },
    ]
    return render_template(
        "module_home.html",
        title="Farm Operations",
        module_title="Farm Operations",
        module_intro="Operational tools remain shared across the whole platform, with camps staying available to both livestock and wildlife modules.",
        action_links=[
            {"label": "Open Camps", "href": url_for("camps_list"), "style": "primary"},
            {"label": "Add Task", "href": url_for("tasks_new"), "style": "outline-secondary"},
        ],
        section_groups=section_groups,
    )


@app.route("/farm-operations/staff-notes")
def staff_notes_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = StaffNote.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(StaffNote.staff_member.contains(q) | StaffNote.subject.contains(q) | StaffNote.details.contains(q))
    return render_template(
        "staff_notes.html",
        items=query.order_by(StaffNote.note_date.desc(), StaffNote.id.desc()).all(),
        q=q,
        item=None,
        form_values={},
        form_errors={},
        form_submitted=False,
        camps=Camp.query.filter_by(is_deleted=False).order_by(Camp.name).all(),
    )


@app.route("/farm-operations/staff-notes/new", methods=["GET", "POST"])
def staff_notes_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        form_errors = validate_staff_note_form(request.form)
        if form_errors:
            flash("Please correct the highlighted staff note fields.")
            return render_staff_notes_page(form_values=request.form, form_errors=form_errors)

        record = StaffNote(
            note_date=request.form.get("note_date"),
            staff_member=request.form.get("staff_member"),
            subject=request.form.get("subject"),
            note_type=request.form.get("note_type") or "general",
            details=request.form.get("details"),
            camp_id=request.form.get("camp_id") or None,
            status=request.form.get("status") or "open",
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "staff_note", record.id, f"Created staff note {record.subject}")
        flash("Staff note created.")
        return redirect(url_for("staff_notes_list"))
    return redirect(url_for("staff_notes_list"))


@app.route("/farm-operations/staff-notes/<int:item_id>/edit", methods=["GET", "POST"])
def staff_notes_edit(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = StaffNote.query.get_or_404(item_id)
    if request.method == "POST":
        form_errors = validate_staff_note_form(request.form)
        if form_errors:
            flash("Please correct the highlighted staff note fields.")
            return render_staff_notes_page(item=record, form_values=request.form, form_errors=form_errors)

        record.note_date = request.form.get("note_date")
        record.staff_member = request.form.get("staff_member")
        record.subject = request.form.get("subject")
        record.note_type = request.form.get("note_type") or "general"
        record.details = request.form.get("details")
        record.camp_id = request.form.get("camp_id") or None
        record.status = request.form.get("status") or "open"
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "staff_note", record.id, f"Updated staff note {record.subject}")
        flash("Staff note updated.")
        return redirect(url_for("staff_notes_list"))
    return render_staff_notes_page(item=record)


@app.route("/farm-operations/staff-notes/<int:item_id>/delete", methods=["POST"])
def staff_notes_delete(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = StaffNote.query.get_or_404(item_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "staff_note", record.id, f"Archived staff note {record.subject}")
    flash("Staff note archived.")
    return redirect(url_for("staff_notes_list"))


@app.route("/farm-operations/maintenance-notes")
def maintenance_notes_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = MaintenanceNote.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(MaintenanceNote.asset_or_area.contains(q) | MaintenanceNote.issue_type.contains(q) | MaintenanceNote.details.contains(q))
    return render_template(
        "maintenance_notes.html",
        items=query.order_by(MaintenanceNote.note_date.desc(), MaintenanceNote.id.desc()).all(),
        q=q,
        item=None,
        form_values={},
        form_errors={},
        form_submitted=False,
        camps=Camp.query.filter_by(is_deleted=False).order_by(Camp.name).all(),
    )


@app.route("/farm-operations/maintenance-notes/new", methods=["GET", "POST"])
def maintenance_notes_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        form_errors = validate_maintenance_note_form(request.form)
        if form_errors:
            flash("Please correct the highlighted maintenance fields.")
            return render_maintenance_notes_page(form_values=request.form, form_errors=form_errors)

        record = MaintenanceNote(
            note_date=request.form.get("note_date"),
            asset_or_area=request.form.get("asset_or_area"),
            camp_id=request.form.get("camp_id") or None,
            issue_type=request.form.get("issue_type") or "general",
            priority=request.form.get("priority") or "medium",
            status=request.form.get("status") or "open",
            assigned_to=request.form.get("assigned_to"),
            details=request.form.get("details"),
            completed_date=request.form.get("completed_date"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "maintenance_note", record.id, f"Created maintenance note {record.asset_or_area}")
        flash("Maintenance note created.")
        return redirect(url_for("maintenance_notes_list"))
    return redirect(url_for("maintenance_notes_list"))


@app.route("/farm-operations/maintenance-notes/<int:item_id>/edit", methods=["GET", "POST"])
def maintenance_notes_edit(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = MaintenanceNote.query.get_or_404(item_id)
    if request.method == "POST":
        form_errors = validate_maintenance_note_form(request.form)
        if form_errors:
            flash("Please correct the highlighted maintenance fields.")
            return render_maintenance_notes_page(item=record, form_values=request.form, form_errors=form_errors)

        record.note_date = request.form.get("note_date")
        record.asset_or_area = request.form.get("asset_or_area")
        record.camp_id = request.form.get("camp_id") or None
        record.issue_type = request.form.get("issue_type") or "general"
        record.priority = request.form.get("priority") or "medium"
        record.status = request.form.get("status") or "open"
        record.assigned_to = request.form.get("assigned_to")
        record.details = request.form.get("details")
        record.completed_date = request.form.get("completed_date")
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "maintenance_note", record.id, f"Updated maintenance note {record.asset_or_area}")
        flash("Maintenance note updated.")
        return redirect(url_for("maintenance_notes_list"))
    return render_maintenance_notes_page(item=record)


@app.route("/farm-operations/maintenance-notes/<int:item_id>/delete", methods=["POST"])
def maintenance_notes_delete(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = MaintenanceNote.query.get_or_404(item_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "maintenance_note", record.id, f"Archived maintenance note {record.asset_or_area}")
    flash("Maintenance note archived.")
    return redirect(url_for("maintenance_notes_list"))


@app.route("/reporting")
def reports_home():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    section_groups = [
        {
            "title": "Available Reports",
            "description": "Current report screens already available in the app.",
            "items": [
                {"title": "Livestock Reports", "description": "Current livestock counts, treatments, sales, purchases, and task reporting.", "href": url_for("livestock_reports"), "icon": "bar-chart-3"},
                {"title": "Wildlife Reports", "description": "Species register, game counts, and offtake reporting.", "href": url_for("wildlife_reports_central"), "icon": "trees"},
                {"title": "Hunting Reports", "description": "Current hunting bookings, revenue, and wounded follow-up reporting.", "href": url_for("hunting_reports_central"), "icon": "bar-chart-4"},
                {"title": "Farm Operations Reports", "description": "Camps, tasks, diary, staff notes, and maintenance summaries.", "href": url_for("operations_reports"), "icon": "clipboard-pen"},
            ],
        },
    ]
    return render_template(
        "module_home.html",
        title="Reports",
        module_title="Reports",
        module_intro="Central reporting entry point for livestock, wildlife, hunting, and shared farm operations reporting.",
        action_links=[],
        section_groups=section_groups,
    )


@app.route("/reports/livestock")
def livestock_reports():
    return reports()


@app.route("/reports/wildlife")
def wildlife_reports_central():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    start_date = parse_date(request.args.get("start_date"))
    end_date = parse_date(request.args.get("end_date"))
    camp_filter = request.args.get("camp") or ""
    species_filter = request.args.get("species") or ""
    offtake_type_filter = request.args.get("offtake_type") or ""

    camps = Camp.query.filter_by(is_deleted=False).order_by(Camp.name).all()
    species_items = WildlifeSpecies.query.filter_by(is_deleted=False).order_by(WildlifeSpecies.common_name).all()
    all_species = WildlifeSpecies.query.filter_by(is_deleted=False).all()
    filtered_species = [
        row for row in all_species
        if not species_filter or str(row.id) == species_filter
    ]
    active_species = sum(1 for row in filtered_species if row.active)

    counts = [
        row for row in WildlifeCount.query.filter_by(is_deleted=False).all()
        if record_in_range(row, "count_date", start_date, end_date)
        and (not camp_filter or str(row.camp_id) == camp_filter)
        and (not species_filter or str(row.species_id) == species_filter)
    ]
    offtakes = [
        row for row in WildlifeOfftakeRecord.query.filter_by(is_deleted=False).all()
        if record_in_range(row, "date", start_date, end_date)
        and (not camp_filter or str(row.camp_id) == camp_filter)
        and (not species_filter or str(row.species_id) == species_filter)
        and (not offtake_type_filter or row.offtake_type == offtake_type_filter)
    ]
    latest_count_date = max((row.count_date for row in counts if row.count_date), default="-")
    by_species = {}
    for row in counts:
        label = row.species.common_name if row.species else "Unknown"
        by_species[label] = by_species.get(label, 0) + (row.total_count or 0)
    offtake_value = sum(parse_money_value(row.price_value) for row in offtakes)
    report_tables = [
        {"title": "Species Register", "total": len(filtered_species), "rows": [{"label": "Active", "value": active_species}, {"label": "Inactive", "value": max(len(filtered_species) - active_species, 0)}]},
        {"title": "Game Counts", "total": len(counts), "rows": [{"label": "Latest count date", "value": latest_count_date}, {"label": "Animals counted", "value": sum(row.total_count or 0 for row in counts)}]},
        {"title": "Counts by Species", "total": len(by_species), "rows": [{"label": label, "value": value} for label, value in sorted(by_species.items())] or [{"label": "No records", "value": 0}]},
        {"title": "Trophy / Offtake", "total": len(offtakes), "rows": [{"label": "Recovered", "value": sum(1 for row in offtakes if row.recovered)}, {"label": "Estimated value", "value": format_currency(offtake_value)}]},
    ]
    filters = {
        "action": url_for("wildlife_reports_central"),
        "fields": [
            {"name": "start_date", "label": "Start date", "type": "date", "value": request.args.get("start_date", "")},
            {"name": "end_date", "label": "End date", "type": "date", "value": request.args.get("end_date", "")},
            {"name": "camp", "label": "Camp", "type": "select", "value": camp_filter, "options": [{"value": "", "label": "All camps"}] + [{"value": str(camp.id), "label": camp.name} for camp in camps]},
            {"name": "species", "label": "Species", "type": "select", "value": species_filter, "options": [{"value": "", "label": "All species"}] + [{"value": str(species.id), "label": species.common_name} for species in species_items]},
            {"name": "offtake_type", "label": "Offtake type", "type": "select", "value": offtake_type_filter, "options": [{"value": "", "label": "All types"}, {"value": "trophy", "label": "Trophy"}, {"value": "cull", "label": "Cull"}, {"value": "meat", "label": "Meat"}]},
        ],
    }
    return render_module_report_page("Wildlife Reports", "Wildlife species, counts, and offtake reporting.", report_tables, filters=filters)


@app.route("/reports/hunting")
def hunting_reports_central():
    return hunting_reports()


@app.route("/reports/operations")
def operations_reports():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    start_date = parse_date(request.args.get("start_date"))
    end_date = parse_date(request.args.get("end_date"))
    camp_filter = request.args.get("camp") or ""
    status_filter = request.args.get("status") or ""

    camps = Camp.query.filter_by(is_deleted=False).all()
    filtered_camps = [camp for camp in camps if not camp_filter or str(camp.id) == camp_filter]
    tasks = [
        task for task in Task.query.filter_by(is_deleted=False).all()
        if record_in_range(task, "due_date", start_date, end_date)
        and (not status_filter or task.status == status_filter)
    ]
    diary_entries = [
        entry for entry in DiaryEntry.query.filter_by(is_deleted=False).all()
        if record_in_range(entry, "entry_date", start_date, end_date)
    ]
    staff_notes = [
        note for note in StaffNote.query.filter_by(is_deleted=False).all()
        if record_in_range(note, "note_date", start_date, end_date)
        and (not camp_filter or str(note.camp_id) == camp_filter)
        and (not status_filter or note.status == status_filter)
    ]
    maintenance_notes = [
        note for note in MaintenanceNote.query.filter_by(is_deleted=False).all()
        if record_in_range(note, "note_date", start_date, end_date)
        and (not camp_filter or str(note.camp_id) == camp_filter)
        and (not status_filter or note.status == status_filter)
    ]
    report_tables = [
        {"title": "Camps", "total": len(filtered_camps), "rows": [{"label": "Water issues", "value": sum(1 for camp in filtered_camps if (camp.water_status or '').lower() in {'low', 'dry', 'urgent'})}, {"label": "Total camps", "value": len(filtered_camps)}]},
        {"title": "Tasks", "total": len(tasks), "rows": [{"label": "Open", "value": sum(1 for task in tasks if task.status == 'open')}, {"label": "Done", "value": sum(1 for task in tasks if task.status == 'done')}]},
        {"title": "Daily Diary", "total": len(diary_entries), "rows": [{"label": "Entries", "value": len(diary_entries)}, {"label": "Latest entry", "value": max((entry.entry_date for entry in diary_entries if entry.entry_date), default='-')}]},
        {"title": "Staff Notes", "total": len(staff_notes), "rows": [{"label": "Open", "value": sum(1 for note in staff_notes if note.status == 'open')}, {"label": "Resolved", "value": sum(1 for note in staff_notes if note.status == 'resolved')}]},
        {"title": "Maintenance Notes", "total": len(maintenance_notes), "rows": [{"label": "Open", "value": sum(1 for note in maintenance_notes if note.status == 'open')}, {"label": "Completed", "value": sum(1 for note in maintenance_notes if note.status == 'completed')}]},
    ]
    filters = {
        "action": url_for("operations_reports"),
        "fields": [
            {"name": "start_date", "label": "Start date", "type": "date", "value": request.args.get("start_date", "")},
            {"name": "end_date", "label": "End date", "type": "date", "value": request.args.get("end_date", "")},
            {"name": "camp", "label": "Camp", "type": "select", "value": camp_filter, "options": [{"value": "", "label": "All camps"}] + [{"value": str(camp.id), "label": camp.name} for camp in camps]},
            {"name": "status", "label": "Status", "type": "select", "value": status_filter, "options": [{"value": "", "label": "All statuses"}, {"value": "open", "label": "Open"}, {"value": "done", "label": "Done"}, {"value": "resolved", "label": "Resolved"}, {"value": "monitoring", "label": "Monitoring"}, {"value": "in_progress", "label": "In progress"}, {"value": "completed", "label": "Completed"}]},
        ],
    }
    return render_module_report_page("Farm Operations Reports", "Shared operational reporting across camps, tasks, diary, staff notes, and maintenance.", report_tables, filters=filters)


@app.route("/admin")
def admin_home():
    role_check = require_role("admin")
    if role_check:
        return role_check
    section_groups = [
        {
            "title": "Administration",
            "description": "Shared platform administration remains outside the livestock and wildlife modules.",
            "items": [
                {"title": "Users", "description": "Manage user access, roles, and profile records.", "href": url_for("users_list"), "icon": "user-cog"},
                {"title": "Activity Log", "description": "Audit trail of recent changes across the platform.", "href": url_for("activity_log"), "icon": "list-checks"},
                {"title": "Settings", "description": "Application-wide shared settings.", "href": url_for("settings"), "icon": "settings"},
            ],
        }
    ]
    return render_template(
        "module_home.html",
        title="Admin",
        module_title="Admin",
        module_intro="Shared administration area for users, audit activity, and settings.",
        action_links=[],
        section_groups=section_groups,
    )


@app.route("/hunting/bookings")
def hunting_bookings_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "")
    query = HuntingBooking.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(HuntingBooking.booking_reference.contains(q) | HuntingBooking.hunter_name.contains(q) | HuntingBooking.notes.contains(q))
    if status_filter:
        query = query.filter(HuntingBooking.status == status_filter)
    bookings = query.order_by(HuntingBooking.date_from.desc(), HuntingBooking.id.desc()).all()
    return render_template("hunting_bookings.html", bookings=bookings, q=q, status_filter=status_filter, item=None)


@app.route("/hunting/bookings/new", methods=["GET", "POST"])
def hunting_bookings_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        validation_error = validate_booking_business_rules(request.form)
        if validation_error:
            flash(validation_error)
            return render_template("hunting_bookings.html", bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.date_from.desc()).all(), q="", status_filter="", item=None)

        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")

        accommodation_required = request.form.get("accommodation_required") == "on"
        accommodation_nights = parse_int_value(request.form.get("accommodation_nights"), 0) if accommodation_required else 0
        accommodation_people = parse_int_value(request.form.get("accommodation_people"), 0) if accommodation_required else 0
        accommodation_rate = parse_money_value(request.form.get("accommodation_rate_per_person_per_night")) if accommodation_required else 0

        booking = HuntingBooking(
            booking_reference=request.form.get("booking_reference") or next_booking_reference(),
            hunter_name=request.form.get("hunter_name"),
            contact_number=request.form.get("contact_number"),
            email=request.form.get("email"),
            date_from=date_from,
            date_to=date_to,
            number_of_hunting_days=max(parse_int_value(request.form.get("number_of_hunting_days"), 1), 1),
            number_of_hunters=max(parse_int_value(request.form.get("number_of_hunters"), 1), 1),
            number_of_guests=max(parse_int_value(request.form.get("number_of_guests"), 0), 0),
            day_fee_per_hunter=parse_money_value(request.form.get("day_fee_per_hunter")),
            staff_fee_per_day=parse_money_value(request.form.get("staff_fee_per_day")),
            guide_fee_per_day=parse_money_value(request.form.get("guide_fee_per_day")),
            tracker_fee_per_day=parse_money_value(request.form.get("tracker_fee_per_day")),
            skinner_fee_per_day=parse_money_value(request.form.get("skinner_fee_per_day")),
            accommodation_required=accommodation_required,
            accommodation_nights=accommodation_nights,
            accommodation_people=accommodation_people,
            accommodation_rate_per_person_per_night=accommodation_rate,
            extras_total=parse_money_value(request.form.get("extras_total")),
            deposit_paid=parse_money_value(request.form.get("deposit_paid")),
            fee_override_enabled=request.form.get("fee_override_enabled") == "on",
            override_notes=request.form.get("override_notes"),
            override_hunting_day_fees_total=parse_money_value(request.form.get("override_hunting_day_fees_total")),
            override_staff_fees_total=parse_money_value(request.form.get("override_staff_fees_total")),
            override_accommodation_total=parse_money_value(request.form.get("override_accommodation_total")),
            override_animals_shot_total=parse_money_value(request.form.get("override_animals_shot_total")),
            override_extras_total=parse_money_value(request.form.get("override_extras_total")),
            override_grand_total=parse_money_value(request.form.get("override_grand_total")),
            guide_assigned=request.form.get("guide_assigned"),
            status=request.form.get("status") or "enquiry",
            notes=request.form.get("notes"),
        )
        set_audit_fields(booking, current_user().id)
        db.session.add(booking)
        db.session.flush()
        apply_booking_totals(booking)
        db.session.commit()
        log_activity("create", "hunting_booking", booking.id, f"Created hunting booking {booking.booking_reference}")
        flash("Hunting booking created.")
        return redirect(url_for("hunting_bookings_list"))
    return render_template("hunting_bookings.html", bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.date_from.desc()).all(), q="", status_filter="", item=None)


@app.route("/hunting/bookings/<int:booking_id>/edit", methods=["GET", "POST"])
def hunting_bookings_edit(booking_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    booking = HuntingBooking.query.get_or_404(booking_id)
    if request.method == "POST":
        validation_error = validate_booking_business_rules(request.form)
        if validation_error:
            flash(validation_error)
            return render_template("hunting_bookings.html", bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.date_from.desc()).all(), q="", status_filter="", item=booking)

        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")
        accommodation_required = request.form.get("accommodation_required") == "on"
        accommodation_nights = parse_int_value(request.form.get("accommodation_nights"), 0) if accommodation_required else 0
        accommodation_people = parse_int_value(request.form.get("accommodation_people"), 0) if accommodation_required else 0
        accommodation_rate = parse_money_value(request.form.get("accommodation_rate_per_person_per_night")) if accommodation_required else 0

        booking.booking_reference = request.form.get("booking_reference") or booking.booking_reference
        booking.hunter_name = request.form.get("hunter_name")
        booking.contact_number = request.form.get("contact_number")
        booking.email = request.form.get("email")
        booking.date_from = date_from
        booking.date_to = date_to
        booking.number_of_hunting_days = max(parse_int_value(request.form.get("number_of_hunting_days"), 1), 1)
        booking.number_of_hunters = max(parse_int_value(request.form.get("number_of_hunters"), 1), 1)
        booking.number_of_guests = max(parse_int_value(request.form.get("number_of_guests"), 0), 0)
        booking.day_fee_per_hunter = parse_money_value(request.form.get("day_fee_per_hunter"))
        booking.staff_fee_per_day = parse_money_value(request.form.get("staff_fee_per_day"))
        booking.guide_fee_per_day = parse_money_value(request.form.get("guide_fee_per_day"))
        booking.tracker_fee_per_day = parse_money_value(request.form.get("tracker_fee_per_day"))
        booking.skinner_fee_per_day = parse_money_value(request.form.get("skinner_fee_per_day"))
        booking.accommodation_required = accommodation_required
        booking.accommodation_nights = accommodation_nights
        booking.accommodation_people = accommodation_people
        booking.accommodation_rate_per_person_per_night = accommodation_rate
        booking.extras_total = parse_money_value(request.form.get("extras_total"))
        booking.deposit_paid = parse_money_value(request.form.get("deposit_paid"))
        booking.fee_override_enabled = request.form.get("fee_override_enabled") == "on"
        booking.override_notes = request.form.get("override_notes")
        booking.override_hunting_day_fees_total = parse_money_value(request.form.get("override_hunting_day_fees_total"))
        booking.override_staff_fees_total = parse_money_value(request.form.get("override_staff_fees_total"))
        booking.override_accommodation_total = parse_money_value(request.form.get("override_accommodation_total"))
        booking.override_animals_shot_total = parse_money_value(request.form.get("override_animals_shot_total"))
        booking.override_extras_total = parse_money_value(request.form.get("override_extras_total"))
        booking.override_grand_total = parse_money_value(request.form.get("override_grand_total"))
        booking.guide_assigned = request.form.get("guide_assigned")
        booking.status = request.form.get("status") or "enquiry"
        booking.notes = request.form.get("notes")
        set_audit_fields(booking, current_user().id)
        apply_booking_totals(booking)
        db.session.commit()
        log_activity("update", "hunting_booking", booking.id, f"Updated hunting booking {booking.booking_reference}")
        flash("Hunting booking updated.")
        return redirect(url_for("hunting_bookings_list"))
    return render_template("hunting_bookings.html", bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.date_from.desc()).all(), q="", status_filter="", item=booking)


@app.route("/hunting/bookings/<int:booking_id>/delete", methods=["POST"])
def hunting_bookings_delete(booking_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    booking = HuntingBooking.query.get_or_404(booking_id)
    archive_record(booking, current_user().id)
    db.session.commit()
    log_activity("archive", "hunting_booking", booking.id, f"Archived hunting booking {booking.booking_reference}")
    flash("Hunting booking archived.")
    return redirect(url_for("hunting_bookings_list"))


@app.route("/hunting/hunters")
def hunting_hunters_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    q = request.args.get("q", "").strip()
    query = HunterProfile.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(HunterProfile.full_name.contains(q) | HunterProfile.id_or_passport_number.contains(q) | HunterProfile.notes.contains(q))
    hunters = query.order_by(HunterProfile.full_name).all()
    return render_template("hunting_hunters.html", hunters=hunters, q=q, item=None)


@app.route("/hunting/hunters/new", methods=["GET", "POST"])
def hunting_hunters_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        hunter = HunterProfile(
            full_name=request.form.get("full_name"),
            id_or_passport_number=request.form.get("id_or_passport_number"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            address=request.form.get("address"),
            licence_details=request.form.get("licence_details"),
            firearm_details=request.form.get("firearm_details"),
            emergency_contact_name=request.form.get("emergency_contact_name"),
            emergency_contact_number=request.form.get("emergency_contact_number"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(hunter, current_user().id)
        db.session.add(hunter)
        db.session.commit()
        log_activity("create", "hunter_profile", hunter.id, f"Created hunter profile {hunter.full_name}")
        flash("Hunter profile created.")
        return redirect(url_for("hunting_hunters_list"))
    return render_template("hunting_hunters.html", hunters=HunterProfile.query.filter_by(is_deleted=False).order_by(HunterProfile.full_name).all(), q="", item=None)


@app.route("/hunting/hunters/<int:hunter_id>/edit", methods=["GET", "POST"])
def hunting_hunters_edit(hunter_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    hunter = HunterProfile.query.get_or_404(hunter_id)
    if request.method == "POST":
        hunter.full_name = request.form.get("full_name")
        hunter.id_or_passport_number = request.form.get("id_or_passport_number")
        hunter.phone = request.form.get("phone")
        hunter.email = request.form.get("email")
        hunter.address = request.form.get("address")
        hunter.licence_details = request.form.get("licence_details")
        hunter.firearm_details = request.form.get("firearm_details")
        hunter.emergency_contact_name = request.form.get("emergency_contact_name")
        hunter.emergency_contact_number = request.form.get("emergency_contact_number")
        hunter.notes = request.form.get("notes")
        set_audit_fields(hunter, current_user().id)
        db.session.commit()
        log_activity("update", "hunter_profile", hunter.id, f"Updated hunter profile {hunter.full_name}")
        flash("Hunter profile updated.")
        return redirect(url_for("hunting_hunters_list"))
    return render_template("hunting_hunters.html", hunters=HunterProfile.query.filter_by(is_deleted=False).order_by(HunterProfile.full_name).all(), q="", item=hunter)


@app.route("/hunting/hunters/<int:hunter_id>/delete", methods=["POST"])
def hunting_hunters_delete(hunter_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    hunter = HunterProfile.query.get_or_404(hunter_id)
    archive_record(hunter, current_user().id)
    db.session.commit()
    log_activity("archive", "hunter_profile", hunter.id, f"Archived hunter profile {hunter.full_name}")
    flash("Hunter profile archived.")
    return redirect(url_for("hunting_hunters_list"))


@app.route("/hunting/indemnities")
def hunting_indemnities_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    items = HuntingIndemnity.query.filter_by(is_deleted=False).order_by(HuntingIndemnity.id.desc()).all()
    return render_template(
        "hunting_indemnities.html",
        items=items,
        bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.booking_reference).all(),
        hunters=HunterProfile.query.filter_by(is_deleted=False).order_by(HunterProfile.full_name).all(),
        item=None,
    )


@app.route("/hunting/indemnities/new", methods=["GET", "POST"])
def hunting_indemnities_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        upload = request.files.get("indemnity_file")
        if upload and upload.filename:
            upload_error = validate_uploaded_indemnity(upload)
            if upload_error:
                flash(upload_error)
                return redirect(url_for("hunting_indemnities_list"))

        record = HuntingIndemnity(
            booking_id=request.form.get("booking_id"),
            hunter_id=request.form.get("hunter_id"),
            date_signed=request.form.get("date_signed"),
            status=request.form.get("status") or "missing",
            witness_or_staff_member=request.form.get("witness_or_staff_member"),
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.flush()
        if upload and upload.filename:
            record.indemnity_file_path = save_uploaded_indemnity(upload, record.id)
            if (record.status or "").lower() == "missing":
                record.status = "signed"
        db.session.commit()
        log_activity("create", "hunting_indemnity", record.id, f"Created hunting indemnity {record.id}")
        flash("Hunting indemnity created.")
        return redirect(url_for("hunting_indemnities_list"))
    return redirect(url_for("hunting_indemnities_list"))


@app.route("/hunting/indemnities/<int:item_id>/edit", methods=["GET", "POST"])
def hunting_indemnities_edit(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HuntingIndemnity.query.get_or_404(item_id)
    if request.method == "POST":
        upload = request.files.get("indemnity_file")
        if upload and upload.filename:
            upload_error = validate_uploaded_indemnity(upload)
            if upload_error:
                flash(upload_error)
                return redirect(url_for("hunting_indemnities_edit", item_id=record.id))

        previous_file = record.indemnity_file_path
        record.booking_id = request.form.get("booking_id")
        record.hunter_id = request.form.get("hunter_id")
        record.date_signed = request.form.get("date_signed")
        record.status = request.form.get("status") or "missing"
        record.witness_or_staff_member = request.form.get("witness_or_staff_member")
        record.notes = request.form.get("notes")
        if upload and upload.filename:
            record.indemnity_file_path = save_uploaded_indemnity(upload, record.id)
            if (record.status or "").lower() == "missing":
                record.status = "signed"
            if previous_file and previous_file != record.indemnity_file_path:
                old_path = os.path.join(INDEMNITY_UPLOAD_FOLDER, os.path.basename(previous_file))
                if os.path.exists(old_path):
                    os.remove(old_path)
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "hunting_indemnity", record.id, f"Updated hunting indemnity {record.id}")
        flash("Hunting indemnity updated.")
        return redirect(url_for("hunting_indemnities_list"))
    items = HuntingIndemnity.query.filter_by(is_deleted=False).order_by(HuntingIndemnity.id.desc()).all()
    return render_template(
        "hunting_indemnities.html",
        items=items,
        bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.booking_reference).all(),
        hunters=HunterProfile.query.filter_by(is_deleted=False).order_by(HunterProfile.full_name).all(),
        item=record,
    )


@app.route("/hunting/indemnities/<int:item_id>/delete", methods=["POST"])
def hunting_indemnities_delete(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HuntingIndemnity.query.get_or_404(item_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "hunting_indemnity", record.id, f"Archived hunting indemnity {record.id}")
    flash("Hunting indemnity archived.")
    return redirect(url_for("hunting_indemnities_list"))


@app.route("/hunting/indemnities/<int:item_id>/file")
def hunting_indemnity_file(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HuntingIndemnity.query.get_or_404(item_id)
    if record.is_deleted or not record.indemnity_file_path:
        abort(404)
    filename = os.path.basename(record.indemnity_file_path)
    file_path = os.path.join(INDEMNITY_UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        abort(404)
    return send_from_directory(INDEMNITY_UPLOAD_FOLDER, filename, as_attachment=True, download_name=filename)


@app.route("/hunting/species-prices")
def hunting_species_prices_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    items = HuntingSpeciesPrice.query.filter_by(is_deleted=False).order_by(HuntingSpeciesPrice.species_name).all()
    return render_template("hunting_species_prices.html", items=items, item=None)


@app.route("/hunting/species-prices/new", methods=["GET", "POST"])
def hunting_species_prices_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        record = HuntingSpeciesPrice(
            species_name=request.form.get("species_name"),
            category=request.form.get("category") or "trophy",
            sex=request.form.get("sex") or "unknown",
            price=parse_money_value(request.form.get("price")),
            active=request.form.get("active") == "on",
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "hunting_species_price", record.id, f"Created species price {record.species_name}")
        flash("Species price created.")
        return redirect(url_for("hunting_species_prices_list"))
    return redirect(url_for("hunting_species_prices_list"))


@app.route("/hunting/species-prices/<int:item_id>/edit", methods=["GET", "POST"])
def hunting_species_prices_edit(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HuntingSpeciesPrice.query.get_or_404(item_id)
    if request.method == "POST":
        record.species_name = request.form.get("species_name")
        record.category = request.form.get("category") or "trophy"
        record.sex = request.form.get("sex") or "unknown"
        record.price = parse_money_value(request.form.get("price"))
        record.active = request.form.get("active") == "on"
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "hunting_species_price", record.id, f"Updated species price {record.species_name}")
        flash("Species price updated.")
        return redirect(url_for("hunting_species_prices_list"))
    items = HuntingSpeciesPrice.query.filter_by(is_deleted=False).order_by(HuntingSpeciesPrice.species_name).all()
    return render_template("hunting_species_prices.html", items=items, item=record)


@app.route("/hunting/species-prices/<int:item_id>/delete", methods=["POST"])
def hunting_species_prices_delete(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HuntingSpeciesPrice.query.get_or_404(item_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "hunting_species_price", record.id, f"Archived species price {record.species_name}")
    flash("Species price archived.")
    return redirect(url_for("hunting_species_prices_list"))


@app.route("/hunting/log")
def hunting_log_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    items = HuntingLog.query.filter_by(is_deleted=False).order_by(HuntingLog.date.desc(), HuntingLog.id.desc()).all()
    return render_template(
        "hunting_log.html",
        items=items,
        bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.booking_reference).all(),
        hunters=HunterProfile.query.filter_by(is_deleted=False).order_by(HunterProfile.full_name).all(),
        item=None,
    )


@app.route("/hunting/log/new", methods=["GET", "POST"])
def hunting_log_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        record = HuntingLog(
            date=request.form.get("date") or date.today().isoformat(),
            booking_id=request.form.get("booking_id"),
            hunter_id=request.form.get("hunter_id") or None,
            species=request.form.get("species"),
            outcome=request.form.get("outcome") or "shot",
            recovered=request.form.get("recovered") == "on",
            number_animals=max(parse_int_value(request.form.get("number_animals"), 1), 1),
            price_charged=parse_money_value(request.form.get("price_charged")),
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.flush()
        recalculate_booking_if_exists(record.booking_id)
        db.session.commit()
        log_activity("create", "hunting_log", record.id, f"Created hunting log {record.id}")
        flash("Hunting log entry created.")
        return redirect(url_for("hunting_log_list"))
    return redirect(url_for("hunting_log_list"))


@app.route("/hunting/log/<int:item_id>/edit", methods=["GET", "POST"])
def hunting_log_edit(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HuntingLog.query.get_or_404(item_id)
    previous_booking_id = record.booking_id
    if request.method == "POST":
        record.date = request.form.get("date") or record.date
        record.booking_id = request.form.get("booking_id")
        record.hunter_id = request.form.get("hunter_id") or None
        record.species = request.form.get("species")
        record.outcome = request.form.get("outcome") or "shot"
        record.recovered = request.form.get("recovered") == "on"
        record.number_animals = max(parse_int_value(request.form.get("number_animals"), 1), 1)
        record.price_charged = parse_money_value(request.form.get("price_charged"))
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        for booking_id in {previous_booking_id, parse_int_value(record.booking_id, 0)}:
            recalculate_booking_if_exists(booking_id)
        db.session.commit()
        log_activity("update", "hunting_log", record.id, f"Updated hunting log {record.id}")
        flash("Hunting log entry updated.")
        return redirect(url_for("hunting_log_list"))
    items = HuntingLog.query.filter_by(is_deleted=False).order_by(HuntingLog.date.desc(), HuntingLog.id.desc()).all()
    return render_template(
        "hunting_log.html",
        items=items,
        bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.booking_reference).all(),
        hunters=HunterProfile.query.filter_by(is_deleted=False).order_by(HunterProfile.full_name).all(),
        item=record,
    )


@app.route("/hunting/log/<int:item_id>/delete", methods=["POST"])
def hunting_log_delete(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HuntingLog.query.get_or_404(item_id)
    booking_id = record.booking_id
    archive_record(record, current_user().id)
    recalculate_booking_if_exists(booking_id)
    db.session.commit()
    log_activity("archive", "hunting_log", record.id, f"Archived hunting log {record.id}")
    flash("Hunting log entry archived.")
    return redirect(url_for("hunting_log_list"))


@app.route("/hunting/wounded")
def hunting_wounded_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    items = HuntingWoundedFollowUp.query.filter_by(is_deleted=False).order_by(HuntingWoundedFollowUp.id.desc()).all()
    return render_template(
        "hunting_wounded_follow_up.html",
        items=items,
        bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.booking_reference).all(),
        logs=HuntingLog.query.filter_by(is_deleted=False).order_by(HuntingLog.id.desc()).all(),
        item=None,
    )


@app.route("/hunting/wounded/new", methods=["GET", "POST"])
def hunting_wounded_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        record = HuntingWoundedFollowUp(
            hunting_log_id=request.form.get("hunting_log_id"),
            booking_id=request.form.get("booking_id"),
            species=request.form.get("species"),
            date_wounded=request.form.get("date_wounded"),
            follow_up_status=request.form.get("follow_up_status") or "open",
            notes=request.form.get("notes"),
        )
        set_audit_fields(record, current_user().id)
        db.session.add(record)
        db.session.commit()
        log_activity("create", "hunting_wounded_follow_up", record.id, f"Created wounded follow-up {record.id}")
        flash("Wounded follow-up created.")
        return redirect(url_for("hunting_wounded_list"))
    return redirect(url_for("hunting_wounded_list"))


@app.route("/hunting/wounded/<int:item_id>/edit", methods=["GET", "POST"])
def hunting_wounded_edit(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HuntingWoundedFollowUp.query.get_or_404(item_id)
    if request.method == "POST":
        record.hunting_log_id = request.form.get("hunting_log_id")
        record.booking_id = request.form.get("booking_id")
        record.species = request.form.get("species")
        record.date_wounded = request.form.get("date_wounded")
        record.follow_up_status = request.form.get("follow_up_status") or "open"
        record.notes = request.form.get("notes")
        set_audit_fields(record, current_user().id)
        db.session.commit()
        log_activity("update", "hunting_wounded_follow_up", record.id, f"Updated wounded follow-up {record.id}")
        flash("Wounded follow-up updated.")
        return redirect(url_for("hunting_wounded_list"))
    items = HuntingWoundedFollowUp.query.filter_by(is_deleted=False).order_by(HuntingWoundedFollowUp.id.desc()).all()
    return render_template(
        "hunting_wounded_follow_up.html",
        items=items,
        bookings=HuntingBooking.query.filter_by(is_deleted=False).order_by(HuntingBooking.booking_reference).all(),
        logs=HuntingLog.query.filter_by(is_deleted=False).order_by(HuntingLog.id.desc()).all(),
        item=record,
    )


@app.route("/hunting/wounded/<int:item_id>/delete", methods=["POST"])
def hunting_wounded_delete(item_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = HuntingWoundedFollowUp.query.get_or_404(item_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "hunting_wounded_follow_up", record.id, f"Archived wounded follow-up {record.id}")
    flash("Wounded follow-up archived.")
    return redirect(url_for("hunting_wounded_list"))


@app.route("/hunting/payments")
def hunting_payments_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    status_filter = request.args.get("status", "")
    query = HuntingBooking.query.filter_by(is_deleted=False)
    if status_filter:
        query = query.filter(HuntingBooking.payment_status == status_filter)
    bookings = query.order_by(HuntingBooking.date_from.desc()).all()
    for booking in bookings:
        apply_booking_totals(booking)
    db.session.commit()
    return render_template("hunting_payments.html", bookings=bookings, status_filter=status_filter)


@app.route("/hunting/bookings/<int:booking_id>/summary")
def hunting_booking_summary(booking_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    booking = HuntingBooking.query.get_or_404(booking_id)
    apply_booking_totals(booking)
    db.session.commit()
    logs = HuntingLog.query.filter_by(booking_id=booking.id, is_deleted=False).order_by(HuntingLog.date.desc()).all()
    wounded = HuntingWoundedFollowUp.query.filter_by(booking_id=booking.id, is_deleted=False).order_by(HuntingWoundedFollowUp.id.desc()).all()
    return render_template("hunting_booking_summary.html", booking=booking, logs=logs, wounded=wounded)


@app.route("/hunting/reports")
def hunting_reports():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    bookings = HuntingBooking.query.filter_by(is_deleted=False).all()
    for booking in bookings:
        apply_booking_totals(booking)
    db.session.commit()
    report_tables = [
        {
            "title": "Bookings",
            "total": len(bookings),
            "rows": [
                {"label": "Enquiry", "value": sum(1 for b in bookings if b.status == "enquiry")},
                {"label": "Confirmed", "value": sum(1 for b in bookings if b.status == "confirmed")},
                {"label": "Completed", "value": sum(1 for b in bookings if b.status == "completed")},
                {"label": "Cancelled", "value": sum(1 for b in bookings if b.status == "cancelled")},
            ],
        },
        {
            "title": "Revenue",
            "total": format_currency(sum(parse_money_value(b.final_grand_total) for b in bookings)),
            "rows": [
                {"label": "Deposits", "value": format_currency(sum(parse_money_value(b.deposit_paid) for b in bookings))},
                {"label": "Balances", "value": format_currency(sum(parse_money_value(b.final_balance_due) for b in bookings))},
            ],
        },
        {
            "title": "Wounded Follow-up",
            "total": HuntingWoundedFollowUp.query.filter_by(is_deleted=False).count(),
            "rows": [
                {"label": "Open", "value": HuntingWoundedFollowUp.query.filter_by(is_deleted=False, follow_up_status="open").count()},
                {"label": "Recovered", "value": HuntingWoundedFollowUp.query.filter_by(is_deleted=False, follow_up_status="recovered").count()},
                {"label": "Not recovered", "value": HuntingWoundedFollowUp.query.filter_by(is_deleted=False, follow_up_status="not_recovered").count()},
            ],
        },
    ]
    return render_template("hunting_reports.html", report_tables=report_tables)


@app.route("/users/<int:user_id>/profile")
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    if current_user() and current_user().role != "admin" and current_user().id != user.id:
        flash("You do not have permission to view that profile.")
        return redirect(url_for("dashboard"))
    return render_template("profile.html", user=user)


@app.route("/users/<int:user_id>/reset-password", methods=["POST"])
def reset_password(user_id):
    role_check = require_role("admin")
    if role_check:
        return role_check
    user = User.query.get_or_404(user_id)
    new_password = request.form.get("password") or "changeme"
    user.password = generate_password_hash(new_password)
    db.session.commit()
    log_activity("update", "user", user.id, f"Reset password for {user.username}")
    flash("Password reset successfully.")
    return redirect(url_for("user_profile", user_id=user.id))


@app.route("/reports")
def reports():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check

    start_date = parse_date(request.args.get("start_date"))
    end_date = parse_date(request.args.get("end_date"))
    species_filter = request.args.get("species") or ""
    camp_filter = request.args.get("camp") or ""
    status_filter = request.args.get("status") or ""

    animals = Animal.query.filter_by(is_deleted=False).all()
    camps = Camp.query.filter_by(is_deleted=False).all()
    births = BirthRecord.query.filter_by(is_deleted=False).all()
    deaths = DeathLossRecord.query.filter_by(is_deleted=False).all()
    health = HealthRecord.query.filter_by(is_deleted=False).all()
    tasks = Task.query.filter_by(is_deleted=False).all()
    sales = SalePurchaseRecord.query.filter_by(is_deleted=False).all()
    purchases = [record for record in sales if record.transaction_type == "purchase"]
    sales = [record for record in sales if record.transaction_type == "sale"]
    activity_logs = ActivityLog.query.all()

    def filter_record(record):
        if species_filter and getattr(record, "species", None) != species_filter:
            return False
        if camp_filter:
            camp_value = getattr(record, "camp_id", None)
            if camp_value is None or str(camp_value) != camp_filter:
                return False
        if status_filter and getattr(record, "status", None) != status_filter:
            return False
        if getattr(record, "date", None):
            return record_in_range(record, "date", start_date, end_date)
        if getattr(record, "date_born", None):
            return record_in_range(record, "date_born", start_date, end_date)
        if getattr(record, "created_at", None):
            return record_in_range(record, "created_at", start_date, end_date)
        return True

    filtered_animals = [record for record in animals if filter_record(record)]
    filtered_births = [record for record in births if filter_record(record)]
    filtered_deaths = [record for record in deaths if filter_record(record)]
    filtered_health = [record for record in health if filter_record(record)]
    filtered_tasks = [record for record in tasks if filter_record(record)]
    filtered_sales = [record for record in sales if filter_record(record)]
    filtered_purchases = [record for record in purchases if filter_record(record)]
    filtered_activity_logs = [record for record in activity_logs if record_in_range(record, "created_at", start_date, end_date)]

    species_totals = {}
    for animal in filtered_animals:
        species_totals[animal.species] = species_totals.get(animal.species, 0) + 1

    camp_totals = {}
    for animal in filtered_animals:
        camp_totals[animal.camp_id] = camp_totals.get(animal.camp_id, 0) + 1

    sales_total = sum(parse_money_value(record.total_amount) for record in filtered_sales)
    purchases_total = sum(parse_money_value(record.total_amount) for record in filtered_purchases)
    camp_detail = {camp.name: camp_totals.get(camp.id, 0) for camp in camps}

    treatment_types = {}
    for record in filtered_health:
        treatment_key = (record.treatment_type or "other").title()
        treatment_types[treatment_key] = treatment_types.get(treatment_key, 0) + 1

    report_tables = [
        {
            "title": "Livestock Count",
            "total": sum(species_totals.values()),
            "rows": [{"label": species.title(), "value": count} for species, count in species_totals.items()],
        },
        {
            "title": "Animals by Camp",
            "total": len(filtered_animals),
            "rows": [{"label": name, "value": count} for name, count in camp_detail.items()],
        },
        {
            "title": "Births",
            "total": len(filtered_births),
            "rows": [
                {"label": "Records", "value": len(filtered_births)},
                {"label": "Born", "value": sum(record.number_born or 0 for record in filtered_births)},
                {"label": "Alive", "value": sum(record.number_alive or 0 for record in filtered_births)},
                {"label": "Dead", "value": sum(record.number_dead or 0 for record in filtered_births)},
            ],
        },
        {
            "title": "Deaths / Losses",
            "total": sum(record.number_lost or 0 for record in filtered_deaths),
            "rows": [
                {"label": "Records", "value": len(filtered_deaths)},
                {"label": "Animals lost", "value": sum(record.number_lost or 0 for record in filtered_deaths)},
            ],
        },
        {
            "title": "Health Treatments",
            "total": len(filtered_health),
            "rows": [{"label": label, "value": value} for label, value in treatment_types.items()] or [{"label": "No records", "value": 0}],
        },
        {
            "title": "Sales",
            "total": len(filtered_sales),
            "rows": [
                {"label": "Transactions", "value": len(filtered_sales)},
                {"label": "Total value", "value": format_currency(sales_total)},
            ],
        },
        {
            "title": "Purchases",
            "total": len(filtered_purchases),
            "rows": [
                {"label": "Transactions", "value": len(filtered_purchases)},
                {"label": "Total value", "value": format_currency(purchases_total)},
            ],
        },
        {
            "title": "Tasks",
            "total": len(filtered_tasks),
            "rows": [
                {"label": "Open", "value": sum(1 for task in filtered_tasks if task.status == "open")},
                {"label": "Done", "value": sum(1 for task in filtered_tasks if task.status == "done")},
                {"label": "Other", "value": sum(1 for task in filtered_tasks if task.status not in {"open", "done"})},
            ],
        },
    ]

    return render_template(
        "reports.html",
        report_tables=report_tables,
        camps=camps,
        species_filter=species_filter,
        camp_filter=camp_filter,
        status_filter=status_filter,
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
    )


@app.route("/diary")
def diary_list():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    entries = DiaryEntry.query.filter_by(is_deleted=False).order_by(DiaryEntry.entry_date.desc()).all()
    users = {user.id: user for user in User.query.all()}
    return render_template("diary.html", entries=entries, item=None, users=users)


@app.route("/diary/new", methods=["GET", "POST"])
def diary_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    if request.method == "POST":
        entry = DiaryEntry(
            entry_date=request.form.get("entry_date") or date.today().isoformat(),
            weather=request.form.get("weather"),
            rainfall=request.form.get("rainfall"),
            water_points_checked=request.form.get("water_points_checked"),
            grazing_condition=request.form.get("grazing_condition"),
            fence_issues=request.form.get("fence_issues"),
            sick_animals_observed=request.form.get("sick_animals_observed"),
            predator_theft_incidents=request.form.get("predator_theft_incidents"),
            staff_attendance_notes=request.form.get("staff_attendance_notes"),
            equipment_issues=request.form.get("equipment_issues"),
            general_notes=request.form.get("general_notes"),
            photo_placeholder=request.form.get("photo_placeholder") or "Pending",
        )
        set_audit_fields(entry, current_user().id)
        db.session.add(entry)
        db.session.commit()
        log_activity("create", "diary", entry.id, f"Created diary entry for {entry.entry_date}")
        flash("Diary entry saved.")
        return redirect(url_for("diary_list"))
    users = {user.id: user for user in User.query.all()}
    return render_template("diary.html", entries=DiaryEntry.query.filter_by(is_deleted=False).order_by(DiaryEntry.entry_date.desc()).all(), item=None, users=users)


@app.route("/diary/<int:entry_id>/edit", methods=["GET", "POST"])
def diary_edit(entry_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    entry = DiaryEntry.query.get_or_404(entry_id)
    if request.method == "POST":
        entry.entry_date = request.form.get("entry_date") or entry.entry_date
        entry.weather = request.form.get("weather")
        entry.rainfall = request.form.get("rainfall")
        entry.water_points_checked = request.form.get("water_points_checked")
        entry.grazing_condition = request.form.get("grazing_condition")
        entry.fence_issues = request.form.get("fence_issues")
        entry.sick_animals_observed = request.form.get("sick_animals_observed")
        entry.predator_theft_incidents = request.form.get("predator_theft_incidents")
        entry.staff_attendance_notes = request.form.get("staff_attendance_notes")
        entry.equipment_issues = request.form.get("equipment_issues")
        entry.general_notes = request.form.get("general_notes")
        entry.photo_placeholder = request.form.get("photo_placeholder") or entry.photo_placeholder or "Pending"
        set_audit_fields(entry, current_user().id)
        db.session.commit()
        log_activity("update", "diary", entry.id, f"Updated diary entry {entry.entry_date}")
        flash("Diary entry updated.")
        return redirect(url_for("diary_list"))
    users = {user.id: user for user in User.query.all()}
    return render_template("diary.html", entries=DiaryEntry.query.filter_by(is_deleted=False).order_by(DiaryEntry.entry_date.desc()).all(), item=entry, users=users)


@app.route("/diary/<int:entry_id>/delete", methods=["POST"])
def diary_delete(entry_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    entry = DiaryEntry.query.get_or_404(entry_id)
    archive_record(entry, current_user().id)
    db.session.commit()
    log_activity("archive", "diary", entry.id, f"Archived diary entry {entry.entry_date}")
    flash("Diary entry archived.")
    return redirect(url_for("diary_list"))


@app.route("/animals/<int:animal_id>")
def animal_detail(animal_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    animal = Animal.query.get_or_404(animal_id)
    photos = AnimalPhoto.query.filter_by(animal_id=animal.id).order_by(AnimalPhoto.is_primary.desc(), AnimalPhoto.uploaded_at.desc()).all()
    timeline_items = []
    for movement in Movement.query.filter_by(is_deleted=False).all():
        if movement.subject_name and animal.tag_number and movement.subject_name.lower() in animal.tag_number.lower():
            timeline_items.append((movement.date, "Movement", movement.reason or "Movement record", movement.notes))
    for record in HealthRecord.query.filter_by(is_deleted=False).all():
        if record.subject_name and animal.tag_number and record.subject_name.lower() in animal.tag_number.lower():
            timeline_items.append((record.date, "Health", record.treatment_type, record.notes))
    for record in BirthRecord.query.filter_by(is_deleted=False).all():
        if record.mother_reference and record.mother_reference.lower() == animal.tag_number.lower():
            timeline_items.append((record.date_born, "Birth", f"{record.number_alive} alive", record.notes))
    for record in DeathLossRecord.query.filter_by(is_deleted=False).all():
        if record.subject_name and animal.tag_number and record.subject_name.lower() in animal.tag_number.lower():
            timeline_items.append((record.date, "Death", f"{record.number_lost} lost", record.notes))
    for record in SalePurchaseRecord.query.filter_by(is_deleted=False).all():
        if record.item_name and animal.tag_number and record.item_name.lower() in animal.tag_number.lower():
            timeline_items.append((record.date, record.transaction_type.title(), record.party, record.notes))
    for task in Task.query.filter_by(is_deleted=False).all():
        if task.related_name and animal.tag_number and task.related_name.lower() in animal.tag_number.lower():
            timeline_items.append((task.due_date, "Task", task.title, task.description))
    timeline_items.sort(key=lambda item: item[0] or "", reverse=True)
    return render_template("animal_detail.html", animal=animal, photos=photos, timeline_items=timeline_items)


@app.route("/groups/<int:group_id>")
def group_detail(group_id):
    group = LivestockGroup.query.get_or_404(group_id)
    timeline_items = []
    for movement in Movement.query.filter_by(is_deleted=False).all():
        if movement.subject_name and group.name and movement.subject_name.lower() == group.name.lower():
            timeline_items.append((movement.date, "Movement", movement.reason or "Movement record", movement.notes))
    for task in Task.query.filter_by(is_deleted=False).all():
        if task.related_name and group.name and task.related_name.lower() == group.name.lower():
            timeline_items.append((task.due_date, "Task", task.title, task.description))
    for record in HealthRecord.query.filter_by(is_deleted=False).all():
        if record.subject_name and group.name and record.subject_name.lower() == group.name.lower():
            timeline_items.append((record.date, "Health", record.treatment_type, record.notes))
    timeline_items.sort(key=lambda item: item[0] or "", reverse=True)
    return render_template("group_detail.html", group=group, timeline_items=timeline_items)


@app.route("/camps/<int:camp_id>")
def camp_detail(camp_id):
    camp = Camp.query.get_or_404(camp_id)
    timeline_items = []
    for movement in Movement.query.filter_by(is_deleted=False).all():
        if movement.from_camp_id == camp.id or movement.to_camp_id == camp.id:
            timeline_items.append((movement.date, "Movement", movement.subject_name, movement.notes))
    for record in DeathLossRecord.query.filter_by(is_deleted=False).all():
        if record.camp_id == camp.id:
            timeline_items.append((record.date, "Death", record.subject_name, record.notes))
    for record in Animal.query.filter_by(is_deleted=False).all():
        if record.camp_id == camp.id:
            timeline_items.append((record.purchase_date or record.created_at, "Animal", record.tag_number, record.notes))
    for task in Task.query.filter_by(is_deleted=False).all():
        if task.related_name and camp.name and task.related_name.lower() == camp.name.lower():
            timeline_items.append((task.due_date, "Task", task.title, task.description))
    timeline_items.sort(key=lambda item: item[0] or "", reverse=True)
    return render_template("camp_detail.html", camp=camp, timeline_items=timeline_items)


@app.route("/users")
def users_list():
    role_check = require_role("admin")
    if role_check:
        return role_check
    users = User.query.order_by(User.username).all()
    return render_template("users.html", users=users, item=None)


@app.route("/users/new", methods=["GET", "POST"])
def users_new():
    role_check = require_role("admin")
    if role_check:
        return role_check
    if request.method == "POST":
        user = User(
            username=request.form.get("username"),
            full_name=request.form.get("full_name"),
            password=generate_password_hash(request.form.get("password") or "changeme"),
            role=request.form.get("role") or "manager",
            is_active=request.form.get("is_active") == "on",
        )
        db.session.add(user)
        db.session.commit()
        log_activity("create", "user", user.id, f"Created user {user.username}")
        flash("User created.")
        return redirect(url_for("users_list"))
    return render_template("users.html", users=User.query.order_by(User.username).all(), item=None)


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
def users_edit(user_id):
    role_check = require_role("admin")
    if role_check:
        return role_check
    user = User.query.get_or_404(user_id)
    if request.method == "POST":
        user.full_name = request.form.get("full_name")
        user.role = request.form.get("role") or user.role
        user.is_active = request.form.get("is_active") == "on"
        if request.form.get("password"):
            user.password = generate_password_hash(request.form.get("password"))
        db.session.commit()
        log_activity("update", "user", user.id, f"Updated user {user.username}")
        flash("User updated.")
        return redirect(url_for("users_list"))
    return render_template("users.html", users=User.query.order_by(User.username).all(), item=user)


@app.route("/activity")
def activity_log():
    role_check = require_role("admin")
    if role_check:
        return role_check
    logs = ActivityLog.query.order_by(ActivityLog.id.desc()).all()
    return render_template("activity.html", logs=logs)


@app.route("/settings")
def settings():
    role_check = require_role("admin")
    if role_check:
        return role_check
    return render_template("settings.html")


@app.errorhandler(404)
def handle_not_found(error):
    return render_template("errors/404.html", title="Page not found"), 404


@app.errorhandler(403)
def handle_forbidden(error):
    return render_template("errors/403.html", title="Access denied"), 403


@app.errorhandler(500)
def handle_server_error(error):
    return render_template("errors/500.html", title="Server error"), 500


def seed_data():
    if User.query.count() > 0:
        return

    owner_username = os.environ.get("OWNER_USERNAME", "owner")
    owner_password = os.environ.get("OWNER_PASSWORD", "owner123")
    owner_name = os.environ.get("OWNER_FULL_NAME", "Admin / Farm Owner")

    owner = User(username=owner_username, full_name=owner_name, password=generate_password_hash(owner_password), role="admin", is_active=True)
    db.session.add(owner)
    db.session.commit()

    log_activity("create", "system", None, f"Seeded owner user '{owner_username}'")


with app.app_context():
    db.create_all()
    run_startup_migrations()
    db.create_all()
    seed_data()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
