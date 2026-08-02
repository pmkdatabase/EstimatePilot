from flask import Flask, render_template, redirect, url_for, flash, request, abort, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date
import csv, io, os, secrets
from models import db, User, Customer, Material, Estimate, EstimateLineItem, Job, JobCostEntry

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///estimatepilot.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.is_role(*roles):
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("dashboard") if current_user.is_authenticated else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email    = request.form["email"].strip().lower()
        password = request.form["password"]
        user     = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Dashboard router ──────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == "owner":
        return redirect(url_for("owner_dashboard"))
    if current_user.role == "installer":
        return redirect(url_for("jobs_list"))
    return redirect(url_for("estimates_list"))


# ── Customers ─────────────────────────────────────────────────────────────────

@app.route("/customers", methods=["GET", "POST"])
@login_required
@roles_required("owner", "estimator")
def customers_list():
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Customer name is required.", "danger")
        else:
            db.session.add(Customer(name=name,
                                     email=request.form.get("email", "").strip(),
                                     phone=request.form.get("phone", "").strip(),
                                     address=request.form.get("address", "").strip()))
            db.session.commit()
            flash("Customer added.", "success")
        return redirect(url_for("customers_list"))
    customers = Customer.query.order_by(Customer.name).all()
    return render_template("estimator/customers.html", customers=customers)


@app.route("/customers/<int:customer_id>")
@login_required
@roles_required("owner", "estimator")
def customer_detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    estimates = sorted(customer.estimates, key=lambda e: e.created_at, reverse=True)
    return render_template("estimator/customer_detail.html", customer=customer, estimates=estimates)


@app.route("/customers/<int:customer_id>/export.csv")
@login_required
@roles_required("owner", "estimator")
def customer_export_csv(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Estimate", "Estimate Status", "Created", "Estimate Total",
                      "Job Status", "Job Revenue", "Job Actual Cost", "Job Profit"])
    for e in sorted(customer.estimates, key=lambda e: e.created_at):
        job = e.job
        writer.writerow([
            e.title, e.status, e.created_at.strftime("%Y-%m-%d"), f"{e.total:.2f}",
            job.status if job else "",
            f"{job.estimate.revenue:.2f}" if job else "",
            f"{job.actual_cost:.2f}" if job else "",
            f"{job.profit:.2f}" if job else "",
        ])
    filename = f"{customer.name.replace(' ', '_')}_history.csv"
    return Response(buf.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": f"attachment; filename={filename}"})


# ── Materials ─────────────────────────────────────────────────────────────────

@app.route("/materials", methods=["GET", "POST"])
@login_required
@roles_required("owner", "estimator")
def materials_list():
    if request.method == "POST":
        is_labor = bool(request.form.get("is_labor"))
        name = request.form["name"].strip()
        unit = "hr" if is_labor else request.form.get("unit", "").strip()
        try:
            unit_cost = float(request.form["unit_cost"])
        except (KeyError, ValueError):
            unit_cost = None
        if not name or not unit or unit_cost is None:
            flash("Name, unit and cost are required.", "danger")
        else:
            category = "Labor" if is_labor else request.form.get("category", "").strip()
            db.session.add(Material(name=name, unit=unit, unit_cost=unit_cost,
                                     category=category, is_labor=is_labor))
            db.session.commit()
            flash(("Labor rate" if is_labor else "Material") + " added.", "success")
        return redirect(url_for("materials_list"))
    materials    = Material.query.filter_by(is_labor=False).order_by(Material.category, Material.name).all()
    labor_rates  = Material.query.filter_by(is_labor=True).order_by(Material.name).all()
    return render_template("estimator/materials.html", materials=materials, labor_rates=labor_rates)


@app.route("/materials/<int:material_id>/delete", methods=["POST"])
@login_required
@roles_required("owner", "estimator")
def material_delete(material_id):
    m = Material.query.get_or_404(material_id)
    db.session.delete(m)
    db.session.commit()
    flash("Material removed.", "info")
    return redirect(url_for("materials_list"))


# ── Estimates / quote builder ────────────────────────────────────────────────

@app.route("/estimates")
@login_required
@roles_required("owner", "estimator")
def estimates_list():
    estimates = Estimate.query.order_by(Estimate.created_at.desc()).all()
    return render_template("estimator/estimates.html", estimates=estimates)


@app.route("/estimates/new", methods=["GET", "POST"])
@login_required
@roles_required("owner", "estimator")
def estimate_new():
    if request.method == "POST":
        customer_id = request.form.get("customer_id")
        title       = request.form["title"].strip()
        if not customer_id or not title:
            flash("Customer and title are required.", "danger")
            return redirect(url_for("estimate_new"))
        est = Estimate(customer_id=customer_id, created_by=current_user.id, title=title)
        db.session.add(est)
        db.session.commit()
        flash("Estimate created — add line items below.", "success")
        return redirect(url_for("estimate_detail", estimate_id=est.id))
    customers = Customer.query.order_by(Customer.name).all()
    if not customers:
        flash("Add a customer first.", "warning")
        return redirect(url_for("customers_list"))
    return render_template("estimator/estimate_new.html", customers=customers)


@app.route("/estimates/<int:estimate_id>")
@login_required
@roles_required("owner", "estimator")
def estimate_detail(estimate_id):
    est = Estimate.query.get_or_404(estimate_id)
    materials = Material.query.order_by(Material.category, Material.name).all()
    return render_template("estimator/estimate_detail.html", estimate=est, materials=materials)


@app.route("/estimates/<int:estimate_id>/line-item", methods=["POST"])
@login_required
@roles_required("owner", "estimator")
def estimate_add_line(estimate_id):
    est = Estimate.query.get_or_404(estimate_id)
    if est.status != "draft":
        flash("Only draft estimates can be edited.", "danger")
        return redirect(url_for("estimate_detail", estimate_id=estimate_id))

    material_id = request.form.get("material_id") or None
    description = request.form.get("description", "").strip()
    is_labor    = bool(request.form.get("is_labor"))
    try:
        quantity  = float(request.form["quantity"])
        unit_cost = float(request.form["unit_cost"])
    except (KeyError, ValueError):
        flash("Quantity and unit cost must be numbers.", "danger")
        return redirect(url_for("estimate_detail", estimate_id=estimate_id))

    if material_id:
        material = db.session.get(Material, int(material_id))
        if material:
            is_labor = material.is_labor
            if not description:
                description = material.name
    if not description or quantity <= 0:
        flash("A description and positive quantity are required.", "danger")
        return redirect(url_for("estimate_detail", estimate_id=estimate_id))

    db.session.add(EstimateLineItem(estimate_id=estimate_id, material_id=material_id or None,
                                     description=description, quantity=quantity,
                                     unit_cost=unit_cost, is_labor=is_labor))
    db.session.commit()
    return redirect(url_for("estimate_detail", estimate_id=estimate_id))


@app.route("/estimates/<int:estimate_id>/line-item/<int:line_id>/delete", methods=["POST"])
@login_required
@roles_required("owner", "estimator")
def estimate_delete_line(estimate_id, line_id):
    li = EstimateLineItem.query.get_or_404(line_id)
    if li.estimate_id != estimate_id:
        abort(404)
    db.session.delete(li)
    db.session.commit()
    return redirect(url_for("estimate_detail", estimate_id=estimate_id))


@app.route("/estimates/<int:estimate_id>/delete", methods=["POST"])
@login_required
@roles_required("owner", "estimator")
def estimate_delete(estimate_id):
    est = Estimate.query.get_or_404(estimate_id)
    if est.status != "draft":
        flash("Only draft estimates can be deleted — sent/approved/rejected estimates stay as a permanent record.", "danger")
        return redirect(url_for("estimate_detail", estimate_id=estimate_id))
    db.session.delete(est)
    db.session.commit()
    flash("Draft estimate deleted.", "info")
    return redirect(url_for("estimates_list"))


@app.route("/estimates/<int:estimate_id>/pricing", methods=["POST"])
@login_required
@roles_required("owner", "estimator")
def estimate_update_pricing(estimate_id):
    est = Estimate.query.get_or_404(estimate_id)
    try:
        est.markup_percent = float(request.form.get("markup_percent", 0) or 0)
        est.tax_rate       = float(request.form.get("tax_rate", 0) or 0)
    except ValueError:
        flash("Markup and tax must be numbers.", "danger")
        return redirect(url_for("estimate_detail", estimate_id=estimate_id))
    db.session.commit()
    flash("Pricing updated.", "success")
    return redirect(url_for("estimate_detail", estimate_id=estimate_id))


@app.route("/estimates/<int:estimate_id>/status/<action>", methods=["POST"])
@login_required
@roles_required("owner", "estimator")
def estimate_set_status(estimate_id, action):
    est = Estimate.query.get_or_404(estimate_id)
    if action == "send" and est.status == "draft":
        est.status = "sent"
    elif action == "approve" and est.status in ("draft", "sent"):
        if not est.line_items:
            flash("Add at least one line item before approving.", "danger")
            return redirect(url_for("estimate_detail", estimate_id=estimate_id))
        est.status = "approved"
        new_job = None
        if not est.job:
            new_job = Job(estimate_id=est.id, customer_id=est.customer_id)
            db.session.add(new_job)
        db.session.commit()
        if new_job:
            flash("Estimate approved — now set up the job.", "success")
            return redirect(url_for("job_setup", job_id=new_job.id))
        flash("Estimate approved.", "success")
        return redirect(url_for("estimate_detail", estimate_id=estimate_id))
    elif action == "reject" and est.status in ("draft", "sent"):
        est.status = "rejected"
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for("estimate_detail", estimate_id=estimate_id))


@app.route("/jobs/<int:job_id>/setup", methods=["GET", "POST"])
@login_required
@roles_required("owner", "estimator")
def job_setup(job_id):
    job = Job.query.get_or_404(job_id)
    if request.method == "POST":
        crew_size = request.form.get("crew_size", "").strip()
        scheduled = request.form.get("scheduled_date", "").strip()
        try:
            job.crew_size = int(crew_size) if crew_size else None
        except ValueError:
            flash("Crew size must be a whole number.", "danger")
            return redirect(url_for("job_setup", job_id=job.id))
        try:
            job.scheduled_date = datetime.strptime(scheduled, "%Y-%m-%d").date() if scheduled else None
        except ValueError:
            flash("Scheduled date is invalid.", "danger")
            return redirect(url_for("job_setup", job_id=job.id))
        job.site_notes = request.form.get("site_notes", "").strip()
        db.session.commit()
        flash("Job setup saved.", "success")
        return redirect(url_for("job_detail", job_id=job.id))
    return render_template("installer/job_setup.html", job=job)


# ── Jobs / job costing ────────────────────────────────────────────────────────

@app.route("/jobs")
@login_required
@roles_required("owner", "estimator", "installer")
def jobs_list():
    query = Job.query
    if current_user.role == "installer":
        query = query.filter_by(assigned_installer_id=current_user.id)
    jobs = query.order_by(Job.created_at.desc()).all()
    installers = User.query.filter_by(role="installer").order_by(User.full_name).all()
    return render_template("installer/jobs.html", jobs=jobs, installers=installers)


@app.route("/jobs/<int:job_id>")
@login_required
@roles_required("owner", "estimator", "installer")
def job_detail(job_id):
    job = Job.query.get_or_404(job_id)
    if current_user.role == "installer" and job.assigned_installer_id != current_user.id:
        abort(403)
    materials = Material.query.order_by(Material.category, Material.name).all()
    return render_template("installer/job_detail.html", job=job, materials=materials)


@app.route("/jobs/<int:job_id>/assign", methods=["POST"])
@login_required
@roles_required("owner", "estimator")
def job_assign(job_id):
    job = Job.query.get_or_404(job_id)
    installer_id = request.form.get("installer_id") or None
    job.assigned_installer_id = installer_id
    if installer_id and job.status == "unscheduled":
        job.status = "in_progress"
        job.start_date = date.today()
    db.session.commit()
    flash("Installer assigned.", "success")
    return redirect(url_for("jobs_list"))


@app.route("/jobs/<int:job_id>/cost", methods=["POST"])
@login_required
@roles_required("owner", "estimator", "installer")
def job_add_cost(job_id):
    job = Job.query.get_or_404(job_id)
    if current_user.role == "installer" and job.assigned_installer_id != current_user.id:
        abort(403)

    material_id = request.form.get("material_id") or None
    description = request.form.get("description", "").strip()

    if material_id:
        material = db.session.get(Material, int(material_id))
        if not material:
            abort(404)
        try:
            quantity = float(request.form["quantity"])
        except (KeyError, ValueError):
            flash("Quantity/hours must be a number.", "danger")
            return redirect(url_for("job_detail", job_id=job_id))
        if quantity <= 0:
            flash("Quantity/hours must be positive.", "danger")
            return redirect(url_for("job_detail", job_id=job_id))
        unit_cost = float(material.unit_cost)
        amount    = round(quantity * unit_cost, 2)
        category  = "labor" if material.is_labor else "material"
        entry = JobCostEntry(job_id=job_id, material_id=material.id, category=category,
                              description=description or material.name,
                              quantity=quantity, unit_cost=unit_cost, amount=amount,
                              entered_by=current_user.id)
    else:
        try:
            amount = float(request.form["amount"])
        except (KeyError, ValueError):
            amount = None
        if not description or amount is None or amount <= 0:
            flash("Description and a positive amount are required.", "danger")
            return redirect(url_for("job_detail", job_id=job_id))
        entry = JobCostEntry(job_id=job_id, category="other", description=description,
                              amount=amount, entered_by=current_user.id)

    db.session.add(entry)
    db.session.commit()
    flash("Cost logged.", "success")
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/jobs/<int:job_id>/status/<action>", methods=["POST"])
@login_required
@roles_required("owner", "estimator", "installer")
def job_set_status(job_id, action):
    job = Job.query.get_or_404(job_id)
    if current_user.role == "installer" and job.assigned_installer_id != current_user.id:
        abort(403)
    if action == "complete":
        job.status = "complete"
        job.end_date = date.today()
    elif action == "reopen":
        job.status = "in_progress"
        job.end_date = None
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for("job_detail", job_id=job_id))


# ── Schedule & installer sheets ───────────────────────────────────────────────

@app.route("/schedule")
@login_required
@roles_required("owner", "estimator", "installer")
def schedule():
    query = Job.query.filter(Job.status != "complete")
    if current_user.role == "installer":
        query = query.filter_by(assigned_installer_id=current_user.id)
    jobs = query.all()

    unscheduled = sorted([j for j in jobs if not j.scheduled_date], key=lambda j: j.created_at)
    groups = {}
    for j in jobs:
        if j.scheduled_date:
            groups.setdefault(j.scheduled_date, []).append(j)
    schedule_groups = sorted(groups.items())
    return render_template("installer/schedule.html", unscheduled=unscheduled, schedule_groups=schedule_groups)


@app.route("/jobs/<int:job_id>/reschedule", methods=["POST"])
@login_required
@roles_required("owner", "estimator")
def job_reschedule(job_id):
    job = Job.query.get_or_404(job_id)
    scheduled = request.form.get("scheduled_date", "").strip()
    try:
        job.scheduled_date = datetime.strptime(scheduled, "%Y-%m-%d").date() if scheduled else None
    except ValueError:
        flash("Invalid date.", "danger")
        return redirect(url_for("schedule"))
    db.session.commit()
    flash("Schedule updated.", "success")
    return redirect(url_for("schedule"))


@app.route("/jobs/<int:job_id>/sheet")
@login_required
@roles_required("owner", "estimator", "installer")
def job_sheet(job_id):
    job = Job.query.get_or_404(job_id)
    if current_user.role == "installer" and job.assigned_installer_id != current_user.id:
        abort(403)
    return render_template("installer/job_sheet.html", job=job)


# ── Owner: profit dashboard & user management ────────────────────────────────

@app.route("/owner/dashboard")
@login_required
@roles_required("owner")
def owner_dashboard():
    jobs = Job.query.order_by(Job.created_at.desc()).all()
    total_revenue = sum((j.estimate.revenue for j in jobs), 0.0)
    total_cost    = sum((j.actual_cost for j in jobs), 0.0)
    total_profit  = round(total_revenue - total_cost, 2)
    open_estimates = Estimate.query.filter(Estimate.status.in_(("draft", "sent"))).count()
    return render_template("owner/dashboard.html", jobs=jobs,
                            total_revenue=round(total_revenue, 2), total_cost=round(total_cost, 2),
                            total_profit=total_profit, open_estimates=open_estimates)


@app.route("/owner/users", methods=["GET", "POST"])
@login_required
@roles_required("owner")
def owner_users():
    if request.method == "POST":
        email     = request.form["email"].strip().lower()
        full_name = request.form["full_name"].strip()
        role      = request.form.get("role", "estimator")
        password  = request.form["password"]
        if role not in ("owner", "estimator", "installer"):
            role = "estimator"
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
        else:
            db.session.add(User(email=email, full_name=full_name, role=role,
                                 password_hash=generate_password_hash(password)))
            db.session.commit()
            flash("User added.", "success")
        return redirect(url_for("owner_users"))
    users = User.query.order_by(User.role, User.full_name).all()
    return render_template("owner/users.html", users=users)


@app.route("/owner/reports")
@login_required
@roles_required("owner")
def owner_reports():
    customers = Customer.query.order_by(Customer.name).all()
    return render_template("owner/reports.html", customers=customers)


@app.route("/owner/reports/export.csv")
@login_required
@roles_required("owner")
def owner_reports_export_csv():
    jobs = Job.query.order_by(Job.created_at).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Job", "Customer", "Status", "Scheduled Date", "Revenue", "Actual Cost", "Profit", "Margin %"])
    for j in jobs:
        writer.writerow([
            j.estimate.title, j.customer.name, j.status,
            j.scheduled_date.strftime("%Y-%m-%d") if j.scheduled_date else "",
            f"{j.estimate.revenue:.2f}", f"{j.actual_cost:.2f}", f"{j.profit:.2f}", j.margin_percent,
        ])
    return Response(buf.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": "attachment; filename=all_jobs_report.csv"})


# ── Seed & run ────────────────────────────────────────────────────────────────

def seed_demo():
    if User.query.first():
        return
    owner = User(email="owner@demo.com", full_name="Sam Reyes", role="owner",
                 password_hash=generate_password_hash("Owner@2026!"))
    estimator = User(email="estimator@demo.com", full_name="Jamie Lee", role="estimator",
                      password_hash=generate_password_hash("Estimator@2026!"))
    installer = User(email="installer@demo.com", full_name="Chris Park", role="installer",
                      password_hash=generate_password_hash("Installer@2026!"))
    db.session.add_all([owner, estimator, installer])
    db.session.flush()

    customer = Customer(name="Lakeside Retail Center", email="facilities@lakesideretail.com",
                         phone="555-0142", address="480 Lakeside Dr, Springfield")
    db.session.add(customer)
    db.session.flush()

    materials = [
        Material(name="TPO Roofing Membrane", category="Roofing", unit="sq ft", unit_cost=2.85),
        Material(name="Roof Insulation Board", category="Roofing", unit="sq ft", unit_cost=1.40),
        Material(name="Mineral Wool Pipe Insulation", category="Mechanical Insulation", unit="linear ft", unit_cost=4.10),
        Material(name="Insulation Jacketing (Aluminum)", category="Mechanical Insulation", unit="sq ft", unit_cost=1.95),
        Material(name="Roofing Labor", category="Labor", unit="hr", unit_cost=48.00, is_labor=True),
        Material(name="Insulation Labor", category="Labor", unit="hr", unit_cost=45.00, is_labor=True),
    ]
    db.session.add_all(materials)
    db.session.flush()

    est = Estimate(customer_id=customer.id, created_by=estimator.id,
                    title="Roof Replacement — Building A", status="approved",
                    markup_percent=18, tax_rate=7.5)
    db.session.add(est)
    db.session.flush()

    db.session.add_all([
        EstimateLineItem(estimate_id=est.id, material_id=materials[0].id,
                          description="TPO Roofing Membrane", quantity=4200, unit_cost=2.85),
        EstimateLineItem(estimate_id=est.id, material_id=materials[1].id,
                          description="Roof Insulation Board", quantity=4200, unit_cost=1.40),
        EstimateLineItem(estimate_id=est.id, material_id=materials[4].id,
                          description="Install labor", quantity=96, unit_cost=48.00, is_labor=True),
    ])

    job = Job(estimate_id=est.id, customer_id=customer.id,
              assigned_installer_id=installer.id, status="in_progress",
              start_date=date.today())
    db.session.add(job)
    db.session.flush()

    db.session.add_all([
        JobCostEntry(job_id=job.id, category="material", description="TPO membrane delivery",
                     amount=11500.00, entered_by=installer.id),
        JobCostEntry(job_id=job.id, category="labor", description="Week 1 crew hours",
                     amount=3200.00, entered_by=installer.id),
    ])

    est2 = Estimate(customer_id=customer.id, created_by=estimator.id,
                     title="Mechanical Room Pipe Insulation", status="draft",
                     markup_percent=15, tax_rate=7.5)
    db.session.add(est2)
    db.session.flush()
    db.session.add(EstimateLineItem(estimate_id=est2.id, material_id=materials[2].id,
                                     description="Mineral Wool Pipe Insulation",
                                     quantity=850, unit_cost=4.10))

    db.session.commit()
    print("Demo data seeded.")
    print("  owner@demo.com / Owner@2026!")
    print("  estimator@demo.com / Estimator@2026!")
    print("  installer@demo.com / Installer@2026!")


with app.app_context():
    db.create_all()
    seed_demo()

if __name__ == "__main__":
    app.run(debug=True)
