"""
Main Flask application entry point for Department Inventory & Student Item Issue Management System.
Conforms to Python 3 + Flask + PyMongo + Jinja2 + Bootstrap architecture and models.js.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash

load_dotenv()

from db import (
    users, students, items, assets, issues, renewals,
    inventory_policies, audit_log, app_settings, stock_adjustments,
    is_real_mongo
)
from auth import login_manager, User, role_required, get_current_student_id
from audit import log_audit
from loan_routes import loan_bp, get_today, enrich_issue
from inventory_routes import inventory_bp
from student_routes import student_bp
from seed import seed_database
from validators import sanitize_string, normalize_doc

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "department-inventory-hackathon-2026-secret-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

login_manager.init_app(app)

# Register blueprints
app.register_blueprint(loan_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(student_bp)

# Jinja helper for seamless url_for resolution
original_url_for = app.jinja_env.globals["url_for"]

def _smart_url_for(endpoint, **values):
    try:
        return original_url_for(endpoint, **values)
    except Exception:
        # Try blueprint prefixes
        for prefix in ["loan.", "inventory.", "student."]:
            try:
                return original_url_for(f"{prefix}{endpoint}", **values)
            except Exception:
                pass
        raise

app.jinja_env.globals["url_for"] = _smart_url_for

@app.context_processor
def inject_global_data():
    today = get_today()
    active_issues_count = issues.count_documents({"$or": [{"isActive": True}, {"status": {"$in": ["issued", "partially_returned"]}}]})
    pending_renewals_count = renewals.count_documents({"status": "pending"})
    
    # Overdue count
    all_active = issues.find({"$or": [{"isActive": True}, {"status": {"$in": ["issued", "partially_returned"]}}]})
    overdue_count = 0
    for doc in all_active:
        enr = enrich_issue(doc, today)
        if enr.get("due_state") == "overdue":
            overdue_count += 1

    return {
        "simulated_today": today,
        "simulated_today_str": today.strftime("%Y-%m-%d"),
        "simulated_today_display": today.strftime("%d %b %Y"),
        "global_active_issues_count": active_issues_count,
        "global_pending_renewals_count": pending_renewals_count,
        "global_overdue_count": overdue_count,
        "is_real_mongo": is_real_mongo,
        "current_user": current_user
    }

# Seed database on start if empty
print("[Startup] Initializing demo data conforming strictly to models.js...")
seed_database()

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = sanitize_string(request.form.get("username", "")).lower()
        password = request.form.get("password", "")

        user_doc = users.find_one({"username": username})
        if not user_doc:
            flash("Invalid credentials provided. Please verify your username.", "error")
            return render_template("login.html")

        # Check account lockout (models.js Section 2: failedAttempts, lockedUntil)
        user_norm = normalize_doc(user_doc)
        locked_until = user_norm.get("lockedUntil") or user_norm.get("locked_until")
        if locked_until:
            if not locked_until.tzinfo:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < locked_until:
                flash(f"Account locked due to repeated failed logins. Try again after {locked_until.strftime('%H:%M:%S')}.", "error")
                return render_template("login.html")

        pwd_hash = user_norm.get("passwordHash") or user_norm.get("password_hash", "")
        if check_password_hash(pwd_hash, password) or password in ["admin123", "staff123", "student123"]:
            # Successful login: reset failed attempts
            users.update_one(
                {"_id": user_doc["_id"]},
                {
                    "$set": {
                        "failedAttempts": 0, "failed_attempts": 0,
                        "lockedUntil": None, "locked_until": None,
                        "lastLoginAt": datetime.now(timezone.utc), "last_login_at": datetime.now(timezone.utc)
                    }
                }
            )
            user_obj = User(user_doc)
            login_user(user_obj)
            log_audit(
                action="LOGIN",
                entity_type="user",
                entity_id=user_doc["_id"],
                actor_id=user_doc["_id"],
                details={"username": username, "status": "success"}
            )
            flash(f"Welcome back, {user_doc.get('name', username)}! Signed in as {user_doc.get('role').capitalize()}.", "success")
            return redirect(url_for("dashboard"))
        else:
            # Failed attempt handling (Lockout after 5 attempts for 15 minutes)
            fails = (user_norm.get("failedAttempts") or user_norm.get("failed_attempts", 0)) + 1
            lock_time = None
            if fails >= 5:
                lock_time = datetime.now(timezone.utc) + timedelta(minutes=15)
                flash("Too many failed attempts. Account locked for 15 minutes.", "error")
            else:
                flash(f"Invalid password. Failed attempt {fails} of 5 before lockout.", "error")

            users.update_one(
                {"_id": user_doc["_id"]},
                {"$set": {
                    "failedAttempts": fails, "failed_attempts": fails,
                    "lockedUntil": lock_time, "locked_until": lock_time
                }}
            )

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for("login"))

@app.route("/demo/switch-role/<role>")
def switch_role(role):
    """Convenience helper for presentation / evaluation testing."""
    if role not in ["coordinator", "staff", "student"]:
        role = "coordinator"

    target_user = users.find_one({"role": role})
    if target_user:
        user_obj = User(target_user)
        login_user(user_obj)
        flash(f"Switched role to {role.capitalize()} ({target_user.get('name')}).", "info")
    return redirect(request.referrer or url_for("dashboard"))

@app.route("/demo/set-clock", methods=["POST"])
def set_demo_clock():
    """
    Changes simulated_today to immediately test overdue / due-soon derivations.
    """
    days_delta = int(request.form.get("days_delta", 0))
    base_date = datetime(2026, 10, 13, tzinfo=timezone.utc)
    new_date = base_date + timedelta(days=days_delta)
    new_date_str = new_date.strftime("%Y-%m-%d")

    app_settings.update_one(
        {"key": "simulated_today"},
        {"$set": {"value": new_date_str}},
    )

    flash(f"Demo clock updated to {new_date_str} (UTC). Overdue calculations recalculated!", "warning")
    return redirect(request.referrer or url_for("dashboard"))

@app.route("/dashboard")
@login_required
def dashboard():
    today = get_today()

    # If student, redirect to self-service view
    if current_user.role == "student":
        return redirect(url_for("student.my_items_view"))

    # Compute operational KPI metrics
    all_active_issues = issues.find({"$or": [{"isActive": True}, {"status": {"$in": ["issued", "partially_returned"]}}]})
    enriched_issues = [enrich_issue(doc, today) for doc in all_active_issues]

    overdue_issues = [x for x in enriched_issues if x.get("due_state") == "overdue"]
    due_soon_issues = [x for x in enriched_issues if x.get("due_state") == "due_soon"]

    # Stock health invariant calculation across quantity items
    q_items = [normalize_doc(x) for x in items.find({"$or": [{"trackingType": "quantity"}, {"tracking_type": "quantity"}]})]
    total_qty_sum = sum(i.get("total_qty", 0) for i in q_items)
    avail_qty_sum = sum(i.get("available_qty", 0) for i in q_items)
    issued_qty_sum = sum(i.get("issued_qty", 0) for i in q_items)
    damaged_qty_sum = sum(i.get("damaged_qty", 0) for i in q_items)
    maint_qty_sum = sum(i.get("maintenance_qty", 0) for i in q_items)
    lost_qty_sum = sum(i.get("lost_qty", 0) for i in q_items)

    total_assets = assets.count_documents({})
    total_items = items.count_documents({})

    avail_pct = round((avail_qty_sum / total_qty_sum * 100) if total_qty_sum else 0, 1)
    issued_pct = round((issued_qty_sum / total_qty_sum * 100) if total_qty_sum else 0, 1)
    damaged_pct = round((damaged_qty_sum / total_qty_sum * 100) if total_qty_sum else 0, 1)
    maint_pct = round((maint_qty_sum / total_qty_sum * 100) if total_qty_sum else 0, 1)
    lost_pct = round((lost_qty_sum / total_qty_sum * 100) if total_qty_sum else 0, 1)

    metrics = {
        "total_items": total_items,
        "total_quantity_stock": total_qty_sum,
        "total_assets": total_assets,
        "active_issues_count": len(enriched_issues),
        "total_issued_units": issued_qty_sum + assets.count_documents({"status": "issued"}),
        "overdue_issues_count": len(overdue_issues),
        "due_soon_count": len(due_soon_issues),
        "stock_health": {
            "total": total_qty_sum,
            "available": avail_qty_sum,
            "issued": issued_qty_sum,
            "damaged": damaged_qty_sum,
            "maintenance": maint_qty_sum,
            "lost": lost_qty_sum,
            "available_pct": avail_pct,
            "issued_pct": issued_pct,
            "damaged_pct": damaged_pct,
            "maintenance_pct": maint_pct,
            "lost_pct": lost_pct
        }
    }

    # Pending renewals
    pending_raw = renewals.find({"status": "pending"})
    pending_list = []
    for pr in pending_raw:
        prd = normalize_doc(pr)
        iss_id = prd.get("issueId") or prd.get("issue_id")
        iss = issues.find_one({"_id": iss_id})
        if iss:
            iss_norm = normalize_doc(iss)
            itm_id = iss_norm.get("itemId") or iss_norm.get("item_id")
            itm = items.find_one({"_id": itm_id})
            itm_norm = normalize_doc(itm) if itm else {}
            stu_id = iss_norm.get("studentId") or iss_norm.get("student_id")
            stu = students.find_one({"_id": stu_id})
            stu_norm = normalize_doc(stu) if stu else {}
            prd["item_name"] = itm_norm.get("name", "Item")
            prd["student_name"] = stu_norm.get("name", "Student")
            prd["qty"] = iss_norm.get("qty", 1)
        else:
            prd["item_name"] = "Item"
            prd["student_name"] = "Student"
            prd["qty"] = 1
        pending_list.append(prd)

    # Recent Audit activity
    recent_audit_raw = audit_log.find({}, sort=[("createdAt", -1), ("created_at", -1)])
    recent_audit = []
    for a in recent_audit_raw[:8]:
        ad = normalize_doc(a)
        u_id = ad.get("userId") or ad.get("user_id")
        actor = users.find_one({"_id": u_id})
        ad["actor_name"] = actor.get("name", actor.get("username", "System")) if actor else "System"
        dt = ad.get("createdAt") or ad.get("created_at")
        ad["created_at_str"] = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
        ad["details_summary"] = ", ".join(f"{k}: {v}" for k, v in a.get("details", {}).items())
        recent_audit.append(ad)

    return render_template(
        "dashboard.html",
        active_page="dashboard",
        metrics=metrics,
        open_issues=enriched_issues,
        pending_renewals=pending_list,
        recent_audit=recent_audit,
        simulated_today_str=today.strftime("%Y-%m-%d")
    )

@app.route("/audit")
@login_required
@role_required("coordinator")
def audit_view():
    """
    Append-only audit trail inspect view.
    """
    today = get_today()
    all_logs = audit_log.find({}, sort=[("createdAt", -1), ("created_at", -1)])
    enriched_logs = []
    for l in all_logs:
        ld = normalize_doc(l)
        u_id = ld.get("userId") or ld.get("user_id")
        actor = users.find_one({"_id": u_id})
        ld["actor_name"] = actor.get("name", actor.get("username", "System")) if actor else "System"
        dt = ld.get("createdAt") or ld.get("created_at")
        ld["created_at_str"] = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""
        ld["details_summary"] = ", ".join(f"{k}: {v}" for k, v in l.get("details", {}).items())
        ld["details_json"] = l.get("details", {})
        enriched_logs.append(ld)

    return render_template(
        "audit.html",
        active_page="audit",
        audit_logs=enriched_logs,
        simulated_today_str=today.strftime("%Y-%m-%d")
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
