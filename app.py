import os
import uuid
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
ANIMAL_UPLOAD_FOLDER = os.path.join(base_dir, "uploads", "animals")
os.makedirs(ANIMAL_UPLOAD_FOLDER, exist_ok=True)


class AuditMixin:
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    password = db.Column(db.String(120), nullable=False)
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
    query = SalePurchaseRecord.query.filter_by(is_deleted=False)
    if q:
        query = query.filter(SalePurchaseRecord.party.contains(q) | SalePurchaseRecord.item_name.contains(q))
    records = query.order_by(SalePurchaseRecord.date.desc()).all()
    return render_template("sales.html", records=records, q=q, item=None)


@app.route("/sales/new", methods=["GET", "POST"])
def sales_new():
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
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
        return redirect(url_for("sales_list"))
    return render_template("sales.html", records=SalePurchaseRecord.query.filter_by(is_deleted=False).order_by(SalePurchaseRecord.date.desc()).all(), q="", item=None)


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
        return redirect(url_for("sales_list"))
    return render_template("sales.html", records=SalePurchaseRecord.query.filter_by(is_deleted=False).order_by(SalePurchaseRecord.date.desc()).all(), q="", item=record)


@app.route("/sales/<int:record_id>/delete", methods=["POST"])
def sales_delete(record_id):
    role_check = require_role("admin", "manager")
    if role_check:
        return role_check
    record = SalePurchaseRecord.query.get_or_404(record_id)
    archive_record(record, current_user().id)
    db.session.commit()
    log_activity("archive", "sale_purchase_record", record.id, f"Archived transaction {record.item_name}")
    flash("Transaction archived.")
    return redirect(url_for("sales_list"))


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

    def parse_money(value):
        if not value:
            return 0.0
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    sales_total = sum(parse_money(record.total_amount) for record in filtered_sales)
    purchases_total = sum(parse_money(record.total_amount) for record in filtered_purchases)
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
                {"label": "Total value", "value": f"${sales_total:,.2f}"},
            ],
        },
        {
            "title": "Purchases",
            "total": len(filtered_purchases),
            "rows": [
                {"label": "Transactions", "value": len(filtered_purchases)},
                {"label": "Total value", "value": f"${purchases_total:,.2f}"},
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
