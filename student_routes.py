"""
Student management and IDOR-protected self-service portal conforming to models.js.
"""

from datetime import datetime, timezone
from bson import ObjectId
from flask import Blueprint, request, redirect, url_for, flash, render_template
from flask_login import current_user, login_required
from db import Student, Issue, Item, Renewal, Return, User as UserModel
from auth import role_required, get_current_student_id
from audit import log_audit
from loan_routes import get_today, enrich_issue
from validators import (
    parse_object_id, validate_positive_int, sanitize_string,
    normalize_doc, validate_student_payload
)

student_bp = Blueprint("student", __name__)

@student_bp.route("/students")
@login_required
@role_required("coordinator", "staff")
def students_view():
    today = get_today()
    all_students = Student.find({}, sort=[("enrolmentNo", 1)])
    
    # Enrich with count of active issues
    enriched = []
    for s in all_students:
        sd = normalize_doc(s)
        act_cnt = Issue.count_documents({
            "$or": [{"studentId": s["_id"]}, {"student_id": s["_id"]}],
            "$or": [{"isActive": True}, {"status": {"$in": ["issued", "partially_returned"]}}]
        })
        sd["active_issues_count"] = act_cnt
        enriched.append(sd)

    return render_template(
        "students.html",
        active_page="students",
        students=enriched,
        simulated_today_str=today.strftime("%Y-%m-%d")
    )

@student_bp.route("/students/create", methods=["POST"])
@login_required
@role_required("coordinator", "staff")
def create_student():
    enrolment_no = sanitize_string(request.form.get("enrolment_no", "")).upper()
    name = sanitize_string(request.form.get("name", ""))
    programme = sanitize_string(request.form.get("programme", ""))
    semester = validate_positive_int(request.form.get("semester"), min_val=1)
    email = sanitize_string(request.form.get("email", "")).lower()
    phone = sanitize_string(request.form.get("phone", ""))
    is_active = bool(request.form.get("is_active"))

    if not enrolment_no or not name or not semester:
        flash("Enrolment number, student name, and semester are required.", "error")
        return redirect(url_for("student.students_view"))

    valid, err = validate_student_payload(enrolment_no, semester, phone)
    if not valid:
        flash(err, "error")
        return redirect(url_for("student.students_view"))

    # Unique index check
    if Student.find_one({"$or": [{"enrolmentNo": enrolment_no}, {"enrolment_no": enrolment_no}]}):
        flash(f"Duplicate Error: Enrolment number '{enrolment_no}' already exists in registry.", "error")
        return redirect(url_for("student.students_view"))

    new_stu = {
        "_id": ObjectId(),
        "enrolmentNo": enrolment_no,
        "name": name,
        "programme": programme,
        "semester": semester,
        "email": email,
        "phone": phone,
        "isActive": is_active,
        # compatibility aliases
        "enrolment_no": enrolment_no,
        "is_active": is_active
    }
    Student.insert_one(new_stu)

    log_audit(
        action="REGISTER_STUDENT",
        entity_type="student",
        entity_id=new_stu["_id"],
        actor_id=current_user._id,
        details={"enrolmentNo": enrolment_no, "name": name}
    )

    flash(f"Student '{name}' ({enrolment_no}) registered successfully!", "success")
    return redirect(url_for("student.students_view"))

@student_bp.route("/students/toggle/<student_id>", methods=["POST"])
@login_required
@role_required("coordinator")
def toggle_student_status(student_id):
    sid = parse_object_id(student_id)
    stu = Student.find_one({"_id": sid})
    if not stu:
        flash("Student record not found.", "error")
        return redirect(url_for("student.students_view"))

    stu_norm = normalize_doc(stu)
    new_status = not stu_norm.get("isActive", True)
    Student.update_one({"_id": sid}, {"$set": {"isActive": new_status, "is_active": new_status}})

    log_audit(
        action="UPDATE_STUDENT_STATUS",
        entity_type="student",
        entity_id=sid,
        actor_id=current_user._id,
        details={"enrolmentNo": stu_norm.get("enrolmentNo"), "new_status": new_status}
    )

    action_text = "activated" if new_status else "suspended"
    flash(f"Student '{stu_norm.get('name')}' has been {action_text}.", "info")
    return redirect(url_for("student.students_view"))

@student_bp.route("/my-items")
@login_required
def my_items_view():
    """
    Student Self-Service Portal
    Scope every student query strictly to the studentId linked to the logged-in user.
    Prevents Insecure Direct Object Reference (IDOR).
    """
    today = get_today()

    if current_user.role != "student":
        return redirect(url_for("loan.issues_view"))

    student_id = get_current_student_id()
    if not student_id:
        flash("No student profile linked to this login account.", "error")
        return redirect(url_for("dashboard"))

    stu_profile = Student.find_one({"_id": student_id})
    if not stu_profile:
        flash("Linked student record not found.", "error")
        return redirect(url_for("dashboard"))
    stu_profile_norm = normalize_doc(stu_profile)

    # Only fetch issues belonging to this student
    my_active_issues = Issue.find({
        "$or": [{"studentId": student_id}, {"student_id": student_id}],
        "$or": [{"isActive": True}, {"status": {"$in": ["issued", "partially_returned"]}}]
    })
    enriched_active = []
    overdue_count = 0
    for doc in my_active_issues:
        enr = enrich_issue(doc, today)
        has_pending = Renewal.find_one({
            "$or": [{"issueId": enr["_id"]}, {"issue_id": enr["_id"]}],
            "status": "pending"
        }) is not None
        enr["has_pending_renewal"] = has_pending
        if enr.get("due_state") == "overdue":
            overdue_count += 1
        enriched_active.append(enr)

    # Return receipts for this student
    my_issues = Issue.find({"$or": [{"studentId": student_id}, {"student_id": student_id}]})
    my_issue_ids = [i["_id"] for i in my_issues]
    all_returns = Return.find({"$or": [{"issueId": {"$in": my_issue_ids}}, {"issue_id": {"$in": my_issue_ids}}]})
    past_returns = []
    for r in all_returns:
        r_norm = normalize_doc(r)
        iss = Issue.find_one({"_id": r_norm.get("issueId") or r_norm.get("issue_id")})
        iss_norm = normalize_doc(iss) if iss else {}
        itm = Item.find_one({"_id": iss_norm.get("itemId") or iss_norm.get("item_id")})
        itm_norm = normalize_doc(itm) if itm else {}
        r_date = r_norm.get("returnDate") or r_norm.get("return_date")
        past_returns.append({
            "item_name": itm_norm.get("name", "Item"),
            "qty_returned": r_norm.get("qtyReturned", r_norm.get("qty_returned", 1)),
            "condition_on_return": r_norm.get("conditionOnReturn", r_norm.get("condition_on_return", "good")),
            "return_date_str": r_date.strftime("%Y-%m-%d") if r_date else "",
            "remarks": r_norm.get("remarks", "")
        })

    return render_template(
        "my_items.html",
        active_page="my_items",
        student_profile=stu_profile_norm,
        active_loans=enriched_active,
        my_overdue_count=overdue_count,
        past_returns=past_returns,
        simulated_today_str=today.strftime("%Y-%m-%d")
    )
