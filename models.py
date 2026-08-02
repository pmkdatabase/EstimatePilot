from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

ROLES = ("owner", "estimator", "installer")


class User(UserMixin, db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name     = db.Column(db.String(150), nullable=False)
    role          = db.Column(db.String(20), nullable=False, default="estimator")
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def is_role(self, *roles):
        return self.role in roles


class Customer(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(150), nullable=False)
    email      = db.Column(db.String(150))
    phone      = db.Column(db.String(50))
    address    = db.Column(db.String(250))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    estimates  = db.relationship("Estimate", backref="customer", lazy=True)

    @property
    def jobs(self):
        return [e.job for e in self.estimates if e.job]

    @property
    def lifetime_revenue(self):
        return round(sum((j.estimate.revenue for j in self.jobs), 0.0), 2)

    @property
    def lifetime_actual_cost(self):
        return round(sum((j.actual_cost for j in self.jobs), 0.0), 2)

    @property
    def lifetime_profit(self):
        return round(self.lifetime_revenue - self.lifetime_actual_cost, 2)


class Material(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(150), nullable=False)
    category   = db.Column(db.String(100))
    unit       = db.Column(db.String(30), nullable=False)   # sq ft, linear ft, each, hr
    unit_cost  = db.Column(db.Numeric(10, 2), nullable=False)
    is_labor   = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Estimate(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    customer_id    = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    created_by     = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title          = db.Column(db.String(200), nullable=False)
    status         = db.Column(db.String(20), default="draft")  # draft, sent, approved, rejected
    markup_percent = db.Column(db.Numeric(6, 2), default=0)
    tax_rate       = db.Column(db.Numeric(6, 2), default=0)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    author         = db.relationship("User", foreign_keys=[created_by])
    line_items     = db.relationship("EstimateLineItem", backref="estimate",
                                      lazy=True, cascade="all, delete-orphan",
                                      order_by="EstimateLineItem.id")
    job            = db.relationship("Job", backref="estimate", uselist=False)

    @property
    def subtotal(self):
        return sum((li.line_total for li in self.line_items), 0)

    @property
    def revenue(self):
        """Subtotal plus markup — what the job is sold for, before tax."""
        return round(float(self.subtotal) * (1 + float(self.markup_percent) / 100), 2)

    @property
    def tax_amount(self):
        return round(self.revenue * (float(self.tax_rate) / 100), 2)

    @property
    def total(self):
        return round(self.revenue + self.tax_amount, 2)


class EstimateLineItem(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    estimate_id = db.Column(db.Integer, db.ForeignKey("estimate.id"), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id"))
    description = db.Column(db.String(200), nullable=False)
    quantity    = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    unit_cost   = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_labor    = db.Column(db.Boolean, default=False)

    material    = db.relationship("Material")

    @property
    def line_total(self):
        return round(float(self.quantity) * float(self.unit_cost), 2)


class Job(db.Model):
    id                    = db.Column(db.Integer, primary_key=True)
    estimate_id           = db.Column(db.Integer, db.ForeignKey("estimate.id"), unique=True, nullable=False)
    customer_id           = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    assigned_installer_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    status                = db.Column(db.String(20), default="unscheduled")  # unscheduled, in_progress, complete
    crew_size             = db.Column(db.Integer)
    site_notes            = db.Column(db.Text)
    scheduled_date        = db.Column(db.Date)   # target/planned start, set during job setup
    start_date            = db.Column(db.Date)   # actual start, stamped when an installer is assigned
    end_date              = db.Column(db.Date)   # actual completion
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)

    customer              = db.relationship("Customer")
    installer             = db.relationship("User", foreign_keys=[assigned_installer_id])
    cost_entries          = db.relationship("JobCostEntry", backref="job", lazy=True,
                                             cascade="all, delete-orphan",
                                             order_by="JobCostEntry.created_at")

    @property
    def is_setup(self):
        return self.crew_size is not None and self.scheduled_date is not None

    @property
    def actual_cost(self):
        return round(sum((float(c.amount) for c in self.cost_entries), 0.0), 2)

    @property
    def profit(self):
        return round(self.estimate.revenue - self.actual_cost, 2)

    @property
    def margin_percent(self):
        revenue = self.estimate.revenue
        return round((self.profit / revenue) * 100, 1) if revenue else 0.0

    def usage_rows(self):
        """Estimated vs. actual quantity/cost, grouped by material/labor rate."""
        rows = {}
        for li in self.estimate.line_items:
            key = li.material_id or f"line-{li.id}"
            row = rows.setdefault(key, {
                "description": li.material.name if li.material else li.description,
                "unit": li.material.unit if li.material else "",
                "trackable": li.material_id is not None,
                "est_qty": 0.0, "est_amount": 0.0, "actual_qty": 0.0, "actual_amount": 0.0,
            })
            row["est_qty"] += float(li.quantity)
            row["est_amount"] += li.line_total
        for c in self.cost_entries:
            if not c.material_id:
                continue
            row = rows.setdefault(c.material_id, {
                "description": c.material.name, "unit": c.material.unit, "trackable": True,
                "est_qty": 0.0, "est_amount": 0.0, "actual_qty": 0.0, "actual_amount": 0.0,
            })
            row["actual_qty"] += float(c.quantity or 0)
            row["actual_amount"] += float(c.amount)
        return sorted(rows.values(), key=lambda r: (-r["trackable"], r["description"]))


class JobCostEntry(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    job_id      = db.Column(db.Integer, db.ForeignKey("job.id"), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id"))  # set when tied to a material/labor rate
    category    = db.Column(db.String(20), nullable=False, default="material")  # material, labor, other
    description = db.Column(db.String(200), nullable=False)
    quantity    = db.Column(db.Numeric(10, 2))   # units used or hours worked; null for "other" entries
    unit_cost   = db.Column(db.Numeric(10, 2))   # cost per unit at time of entry; null for "other" entries
    amount      = db.Column(db.Numeric(10, 2), nullable=False)  # total — computed for material/labor, typed for "other"
    entered_by  = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    material    = db.relationship("Material")
    author      = db.relationship("User", foreign_keys=[entered_by])
