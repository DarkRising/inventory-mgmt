"""
Loan routes, issuing, returns, renewal logic, and Section 6 demo clock / overdue calculations.
Matches 100% strictly with models.js schemas, hooks, and atomic patterns.
"""

from datetime import datetime, timezone, timedelta
from bson import ObjectId
from flask import Blueprint, request, redirect, url_for, flash, render_template, session
from flask_login import current_user, login_required
from db import (
    client, Item, Asset, Student, Issue, Renewal, Return,
    InventoryPolicy, AppSetting, AuditLog, User as UserModel
)
from auth import role_required, get_current_student_id
from audit import log_audit
from validators import (
    parse_object_id, validate_positive_int, sanitize_string,
    normalize_doc, ALLOWED_RETURN_CONDITIONS
)

loan_bp = Blueprint("loan", __name__)

def get_today():
    """
    Returns simulated_today if present, current UTC date otherwise.
    Used by all overdue and due-date logic.
    """
    sim_setting = AppSetting.find_one({"key": "simulated_today"})
    if sim_setting and sim_setting.get("value"):
        val = sim_setting["value"]
        if isinstance(val, str):
            try:
                dt = datetime.fromisoformat(val)
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass
        elif isinstance(val, datetime):
            if not val.tzinfo:
                val = val.replace(tzinfo=timezone.utc)
            return val
    return datetime.now(timezone.utc)

def get_policy_for_item(item_id=None):
    """Fetch item specific policy if present, fallback to global (itemId null)."""
    if item_id:
        p = InventoryPolicy.find_one({"$or": [{"itemId": ObjectId(item_id)}, {"item_id": ObjectId(item_id)}]})
        if p:
            p_norm = normalize_doc(p)
            p_norm["issue_period_days"] = p.get("issuePeriodDays", p.get("issue_period_days", 15))
            p_norm["renewal_extension_days"] = p.get("renewalExtensionDays", p.get("renewal_extension_days", 15))
            p_norm["max_renewals"] = p.get("maxRenewals", p.get("max_renewals", 2))
            return p_norm
    global_p = InventoryPolicy.find_one({"$or": [{"itemId": None}, {"item_id": None}]})
    if not global_p:
        return {
            "issuePeriodDays": 15,
            "renewalExtensionDays": 15,
            "maxRenewals": 2,
            "issue_period_days": 15,
            "renewal_extension_days": 15,
            "max_renewals": 2,
            "issuableIfDamaged": False,
            "issuableIfLost": False,
            "issuableIfMaintenance": False
        }
    global_p_norm = normalize_doc(global_p)
    global_p_norm["issue_period_days"] = global_p.get("issuePeriodDays", global_p.get("issue_period_days", 15))
    global_p_norm["renewal_extension_days"] = global_p.get("renewalExtensionDays", global_p.get("renewal_extension_days", 15))
    global_p_norm["max_renewals"] = global_p.get("maxRenewals", global_p.get("max_renewals", 2))
    return global_p_norm

def enrich_issue(doc, today_dt, reminder_days=3):
    """
    Calculates outstanding_qty, days_past_due, and due_state.
    Overdue is derived: isActive && dueDate < today (models.js).
    """
    d = normalize_doc(doc)
    qty = d.get("qty", 1)
    ret_qty = d.get("returnedQty", d.get("returned_qty", 0))
    outstanding = max(0, qty - ret_qty)
    due_date = d.get("dueDate") or d.get("due_date")

    if not due_date:
        days_past_due = 0
        due_state = "on_time"
    else:
        if not due_date.tzinfo:
            due_date = due_date.replace(tzinfo=timezone.utc)
        delta_days = (today_dt.date() - due_date.date()).days
        days_past_due = delta_days

        if outstanding == 0 or d.get("status") == "returned":
            due_state = "returned"
        elif days_past_due > 0:
            due_state = "overdue"
        elif days_past_due >= -reminder_days:
            due_state = "due_soon"
        else:
            due_state = "on_time"

    d["outstanding_qty"] = outstanding
    d["days_past_due"] = days_past_due
    d["due_state"] = due_state
    issue_date_val = d.get("issueDate") or d.get("issue_date")
    d["issue_date_str"] = issue_date_val.strftime("%Y-%m-%d") if issue_date_val else ""
    d["due_date_str"] = due_date.strftime("%Y-%m-%d") if due_date else ""

    # Look up item and student names
    itm_id = d.get("itemId") or d.get("item_id")
    if itm_id:
        itm = Item.find_one({"_id": itm_id})
        itm_norm = normalize_doc(itm) if itm else {}
        d["item_name"] = itm_norm.get("name", "Unknown Item")
        d["item_code"] = itm_norm.get("itemCode", "")

    stu_id = d.get("studentId") or d.get("student_id")
    if stu_id:
        stu = Student.find_one({"_id": stu_id})
        stu_norm = normalize_doc(stu) if stu else {}
        d["student_name"] = stu_norm.get("name", "Unknown Student")
        d["student_enrolment"] = stu_norm.get("enrolmentNo", "")

    ast_id = d.get("assetId") or d.get("asset_id")
    if ast_id:
        ast = Asset.find_one({"_id": ast_id})
        ast_norm = normalize_doc(ast) if ast else {}
        d["asset_tag"] = ast_norm.get("assetId", "")

    return d

@loan_bp.route("/issues")
@login_required
def issues_view():
    today = get_today()
    all_issues = Issue.find({}, sort=[("createdAt", -1)])
    enriched = [enrich_issue(x, today) for x in all_issues]

    preselect_item = request.args.get("preselect_item", "")
    preselect_asset = request.args.get("preselect_asset", "")
    preselect_student = request.args.get("preselect_student", "")

    active_issues = [x for x in enriched if x.get("isActive", x.get("status") != "returned")]
    overdue_count = len([x for x in active_issues if x["due_state"] == "overdue"])
    returned_count = len([x for x in enriched if x.get("status") == "returned"])

    # Load active students & available items for issue modal
    active_stu = [normalize_doc(s) for s in Student.find({"$or": [{"isActive": True}, {"is_active": True}]})]
    q_items = [normalize_doc(i) for i in Item.find({
        "$or": [{"trackingType": "quantity"}, {"tracking_type": "quantity"}],
        "isRetired": False,
        "$or": [{"stock.available": {"$gt": 0}}, {"available_qty": {"$gt": 0}}]
    })]
    avail_assets = []
    raw_assets = Asset.find({"status": "available"})
    for a in raw_assets:
        a_norm = normalize_doc(a)
        parent_id = a_norm.get("itemId") or a_norm.get("item_id")
        itm = Item.find_one({"_id": parent_id})
        itm_norm = normalize_doc(itm) if itm else {}
        avail_assets.append({
            "_id": a["_id"],
            "asset_id": a_norm.get("assetId"),
            "item_name": itm_norm.get("name", "Asset Item"),
            "serial_no": a_norm.get("serialNo"),
            "condition": a_norm.get("condition")
        })

    return render_template(
        "issues.html",
        active_page="issues",
        issues=enriched,
        active_issues_count=len(active_issues),
        overdue_count=overdue_count,
        returned_count=returned_count,
        active_students=active_stu,
        raw_quantity_items=q_items,
        available_assets=avail_assets,
        preselect_item=preselect_item,
        preselect_asset=preselect_asset,
        preselect_student=preselect_student,
        simulated_today_str=today.strftime("%Y-%m-%d")
    )

@loan_bp.route("/issues/create", methods=["POST"])
@login_required
@role_required("coordinator", "staff")
def create_issue():
    """
    Atomic Issue Operation matching models.js atomic patterns:
    Asset: Asset.updateOne({ _id: assetId, status: 'available', condition: { $in: ['new', 'good', 'fair'] } }, { $set: { status: 'issued' } })
    Quantity: Item.updateOne({ _id: itemId, 'stock.available': { $gte: qty } }, { $inc: { 'stock.available': -qty, 'stock.issued': qty } })
    """
    student_id = parse_object_id(request.form.get("student_id"))
    item_id = parse_object_id(request.form.get("item_id"))
    asset_id = parse_object_id(request.form.get("asset_id"))
    purpose = sanitize_string(request.form.get("purpose", ""))

    if not student_id:
        flash("Invalid or missing student borrower.", "error")
        return redirect(url_for("loan.issues_view"))

    stu = Student.find_one({"_id": student_id, "$or": [{"isActive": True}, {"is_active": True}]})
    if not stu:
        flash("Student is not registered or is currently inactive.", "error")
        return redirect(url_for("loan.issues_view"))
    stu_norm = normalize_doc(stu)

    today = get_today()

    # Asset tracked issue flow
    if asset_id:
        ast = Asset.find_one({"_id": asset_id})
        if not ast:
            flash("Selected asset was not found.", "error")
            return redirect(url_for("loan.issues_view"))
        ast_norm = normalize_doc(ast)
        parent_item_id = ast_norm.get("itemId") or ast_norm.get("item_id")

        # Atomic conditional update from models.js: condition in ['new', 'good', 'fair']
        res = Asset.update_one(
            {"_id": asset_id, "status": "available", "condition": {"$in": ["new", "good", "fair"]}},
            {"$set": {"status": "issued"}}
        )
        if res.modified_count != 1:
            flash("Asset is not available for issue (must be available in new/good/fair condition).", "error")
            return redirect(url_for("loan.issues_view"))

        policy = get_policy_for_item(parent_item_id)
        period_days = policy.get("issuePeriodDays", 15)
        due_date = today + timedelta(days=period_days)

        new_issue = {
            "_id": ObjectId(),
            "studentId": student_id,
            "itemId": parent_item_id,
            "assetId": asset_id,
            "qty": 1,
            "returnedQty": 0,
            "purpose": purpose,
            "issueDate": today,
            "originalDueDate": due_date,
            "dueDate": due_date,
            "renewalCount": 0,
            "status": "issued",
            "isActive": True,
            "issuedBy": current_user._id,
            # compatibility aliases
            "student_id": student_id,
            "item_id": parent_item_id,
            "asset_id": asset_id,
            "returned_qty": 0,
            "issue_date": today,
            "original_due_date": due_date,
            "due_date": due_date,
            "renewal_count": 0,
            "is_active": True,
            "issued_by": current_user._id,
            "returns": [],
            "createdAt": today
        }
        Issue.insert_one(new_issue)

        log_audit(
            action="ISSUE",
            entity_type="issue",
            entity_id=new_issue["_id"],
            actor_id=current_user._id,
            details={"assetId": ast_norm.get("assetId"), "student": stu_norm["name"], "qty": 1}
        )

        flash(f"Asset '{ast_norm.get('assetId')}' successfully issued to {stu_norm['name']}! Due {due_date.strftime('%Y-%m-%d')}.", "success")
        return redirect(url_for("loan.issues_view"))

    # Quantity tracked issue flow
    qty = validate_positive_int(request.form.get("qty"), min_val=1)
    if not qty or not item_id:
        flash("Invalid quantity or missing item selection.", "error")
        return redirect(url_for("loan.issues_view"))

    policy = get_policy_for_item(item_id)
    period_days = policy.get("issuePeriodDays", 15)

    # Atomic conditional update from models.js: stock.available >= qty
    res = Item.update_one(
        {"_id": item_id, "stock.available": {"$gte": qty}},
        {
            "$inc": {
                "stock.available": -qty,
                "stock.issued": qty,
                "available_qty": -qty,
                "issued_qty": qty
            }
        }
    )

    if res.modified_count != 1:
        flash("Issue Rejected: Insufficient usable stock available in catalogue.", "error")
        return redirect(url_for("loan.issues_view"))

    due_date = today + timedelta(days=period_days)
    new_issue = {
        "_id": ObjectId(),
        "studentId": student_id,
        "itemId": item_id,
        "assetId": None,
        "qty": qty,
        "returnedQty": 0,
        "purpose": purpose,
        "issueDate": today,
        "originalDueDate": due_date,
        "dueDate": due_date,
        "renewalCount": 0,
        "status": "issued",
        "isActive": True,
        "issuedBy": current_user._id,
        # compatibility aliases
        "student_id": student_id,
        "item_id": item_id,
        "asset_id": None,
        "returned_qty": 0,
        "issue_date": today,
        "original_due_date": due_date,
        "due_date": due_date,
        "renewal_count": 0,
        "is_active": True,
        "issued_by": current_user._id,
        "returns": [],
        "createdAt": today
    }
    Issue.insert_one(new_issue)

    itm_doc = Item.find_one({"_id": item_id})
    itm_norm = normalize_doc(itm_doc) if itm_doc else {}

    log_audit(
        action="ISSUE",
        entity_type="issue",
        entity_id=new_issue["_id"],
        actor_id=current_user._id,
        details={"itemCode": itm_norm.get("itemCode"), "qty": qty, "student": stu_norm["name"]}
    )

    flash(f"Issued {qty} unit(s) of '{itm_norm.get('name')}' to {stu_norm['name']}! Due {due_date.strftime('%Y-%m-%d')}.", "success")
    return redirect(url_for("loan.issues_view"))

@loan_bp.route("/returns")
@login_required
def returns_view():
    today = get_today()
    active_issues = Issue.find({"$or": [{"isActive": True}, {"status": {"$in": ["issued", "partially_returned"]}}]})
    eligible = [enrich_issue(x, today) for x in active_issues if x.get("status") != "returned"]

    raw_returns = Return.find({}, sort=[("returnDate", -1)])
    receipts = []
    for ret in raw_returns:
        r_dict = normalize_doc(ret)
        iss = Issue.find_one({"_id": r_dict.get("issueId") or r_dict.get("issue_id")})
        if iss:
            iss_norm = normalize_doc(iss)
            itm = Item.find_one({"_id": iss_norm.get("itemId") or iss_norm.get("item_id")})
            itm_norm = normalize_doc(itm) if itm else {}
            stu = Student.find_one({"_id": iss_norm.get("studentId") or iss_norm.get("student_id")})
            stu_norm = normalize_doc(stu) if stu else {}
            rec_by = UserModel.find_one({"_id": r_dict.get("receivedBy") or r_dict.get("received_by")})
            r_date = r_dict.get("returnDate") or r_dict.get("return_date")
            receipts.append({
                "item_name": itm_norm.get("name", "Item"),
                "student_name": stu_norm.get("name", "Student"),
                "student_enrolment": stu_norm.get("enrolmentNo", ""),
                "qty_returned": r_dict.get("qtyReturned", r_dict.get("qty_returned", 1)),
                "condition": r_dict.get("conditionOnReturn", r_dict.get("condition_on_return", "good")),
                "received_by_name": rec_by.get("name", "Staff") if rec_by else "Staff",
                "return_date_str": r_date.strftime("%Y-%m-%d %H:%M") if r_date else "",
                "remarks": r_dict.get("remarks", "")
            })

    preselect_issue_id = request.args.get("issue_id", "")
    return render_template(
        "returns.html",
        active_page="returns",
        eligible_issues=eligible,
        return_receipts=receipts[:15],
        preselect_issue_id=preselect_issue_id,
        simulated_today_str=today.strftime("%Y-%m-%d")
    )

@loan_bp.route("/returns/process", methods=["POST"])
@login_required
@role_required("coordinator", "staff")
def process_return():
    """
    Process Full & Partial Returns conforming strictly to models.js:
    - Inserts record into `returns` collection (Return)
    - Conditionally increments returnedQty on Issue
    - Updates isActive = returnedQty < qty; status = returned | partially_returned
    - Routes stock to stock.available for good/fair, or into stock.damaged / stock.maintenance / stock.lost
    """
    issue_id = parse_object_id(request.form.get("issue_id"))
    qty_returned = validate_positive_int(request.form.get("qty_returned"), min_val=1)
    condition = sanitize_string(request.form.get("condition_on_return", "good"))
    remarks = sanitize_string(request.form.get("remarks", ""))

    if not issue_id or not qty_returned:
        flash("Invalid return payload.", "error")
        return redirect(url_for("loan.returns_view"))

    iss = Issue.find_one({"_id": issue_id})
    if not iss:
        flash("Issue record not found.", "error")
        return redirect(url_for("loan.returns_view"))
    iss_norm = normalize_doc(iss)

    current_ret = iss_norm.get("returnedQty", 0)
    total_qty = iss_norm.get("qty", 1)
    rem = total_qty - current_ret

    if qty_returned > rem:
        flash(f"Cannot return {qty_returned} units; only {rem} units outstanding.", "error")
        return redirect(url_for("loan.returns_view"))

    today = get_today()
    new_ret_total = current_ret + qty_returned
    is_active = new_ret_total < total_qty
    new_status = "issued" if new_ret_total == 0 else ("partially_returned" if is_active else "returned")

    # 1. Insert into Return collection (models.js Section 8)
    return_entry = {
        "_id": ObjectId(),
        "issueId": issue_id,
        "qtyReturned": qty_returned,
        "returnDate": today,
        "conditionOnReturn": condition if condition in ALLOWED_RETURN_CONDITIONS else "good",
        "receivedBy": current_user._id,
        "remarks": remarks,
        # compatibility
        "issue_id": issue_id,
        "qty_returned": qty_returned,
        "return_date": today,
        "condition_on_return": condition,
        "received_by": current_user._id
    }
    Return.insert_one(return_entry)

    # 2. Update issue document
    Issue.update_one(
        {"_id": issue_id},
        {
            "$set": {
                "returnedQty": new_ret_total,
                "returned_qty": new_ret_total,
                "isActive": is_active,
                "is_active": is_active,
                "status": new_status
            },
            "$push": {"returns": return_entry}
        }
    )

    # 3. Update stock counters or asset status based on condition
    item_id = iss_norm.get("itemId") or iss_norm.get("item_id")
    asset_id = iss_norm.get("assetId") or iss_norm.get("asset_id")

    if asset_id:
        target_status = "available" if condition in ["good", "fair", "poor"] else condition
        Asset.update_one({"_id": asset_id}, {"$set": {"status": target_status, "condition": condition}})
    else:
        inc_dest = "available" if condition in ["good", "fair", "poor"] else condition
        Item.update_one(
            {"_id": item_id},
            {
                "$inc": {
                    "stock.issued": -qty_returned,
                    f"stock.{inc_dest}": qty_returned,
                    "issued_qty": -qty_returned,
                    f"{inc_dest}_qty": qty_returned
                }
            }
        )

    log_audit(
        action="RETURN",
        entity_type="issue",
        entity_id=issue_id,
        actor_id=current_user._id,
        details={
            "qtyReturned": qty_returned,
            "conditionOnReturn": condition,
            "newStatus": new_status,
            "remarks": remarks
        }
    )

    flash(f"Successfully processed return of {qty_returned} unit(s) ({condition}). Issue is now '{new_status}'.", "success")
    return redirect(url_for("loan.returns_view"))

@loan_bp.route("/renewals")
@login_required
def renewals_view():
    today = get_today()
    pending = Renewal.find({"status": "pending"})
    past = Renewal.find({"status": {"$in": ["approved", "rejected"]}}, sort=[("decidedAt", -1)])

    enriched_pending = []
    for r in pending:
        rd = normalize_doc(r)
        iss = Issue.find_one({"_id": rd.get("issueId") or rd.get("issue_id")})
        if iss:
            iss_norm = normalize_doc(iss)
            rd["item_id"] = iss_norm.get("itemId")
            rd["qty"] = iss_norm.get("qty", 1)
            rd["renewal_count"] = iss_norm.get("renewalCount", 0)
            itm = Item.find_one({"_id": iss_norm.get("itemId") or iss_norm.get("item_id")})
            itm_norm = normalize_doc(itm) if itm else {}
            rd["item_name"] = itm_norm.get("name", "Item")
            rd["item_code"] = itm_norm.get("itemCode", "")
            stu = Student.find_one({"_id": iss_norm.get("studentId") or iss_norm.get("student_id")})
            stu_norm = normalize_doc(stu) if stu else {}
            rd["student_name"] = stu_norm.get("name", "Student")
            rd["student_enrolment"] = stu_norm.get("enrolmentNo", "")

            cur_due = iss_norm.get("dueDate") or iss_norm.get("due_date", today)
            rd["previous_due_date_str"] = cur_due.strftime("%Y-%m-%d") if cur_due else ""
            rd["projected_due_date_str"] = (cur_due + timedelta(days=15)).strftime("%Y-%m-%d") if cur_due else ""
            enriched_pending.append(rd)

    enriched_past = []
    for h in past:
        hd = normalize_doc(h)
        iss = Issue.find_one({"_id": hd.get("issueId") or hd.get("issue_id")})
        if iss:
            iss_norm = normalize_doc(iss)
            itm = Item.find_one({"_id": iss_norm.get("itemId") or iss_norm.get("item_id")})
            itm_norm = normalize_doc(itm) if itm else {}
            stu = Student.find_one({"_id": iss_norm.get("studentId") or iss_norm.get("student_id")})
            stu_norm = normalize_doc(stu) if stu else {}
            hd["item_name"] = itm_norm.get("name", "Item")
            hd["student_name"] = stu_norm.get("name", "Student")
        dec_u = UserModel.find_one({"_id": hd.get("decidedBy") or hd.get("decided_by")})
        hd["decided_by_name"] = dec_u.get("name", "Coordinator") if dec_u else "Coordinator"
        p_due = hd.get("previousDueDate") or hd.get("previous_due_date")
        r_due = hd.get("revisedDueDate") or hd.get("revised_due_date")
        d_at = hd.get("decidedAt") or hd.get("decided_at")
        hd["previous_due_date_str"] = p_due.strftime("%Y-%m-%d") if p_due else ""
        hd["revised_due_date_str"] = r_due.strftime("%Y-%m-%d") if r_due else ""
        hd["decided_at_str"] = d_at.strftime("%Y-%m-%d") if d_at else ""
        hd["decision_remarks"] = hd.get("remarks", "")
        enriched_past.append(hd)

    return render_template(
        "renewals.html",
        active_page="renewals",
        pending_renewals=enriched_pending,
        renewal_history=enriched_past,
        simulated_today_str=today.strftime("%Y-%m-%d")
    )

@loan_bp.route("/renewals/request", methods=["POST"])
@login_required
def request_renewal():
    """
    Student or Staff initiates renewal request.
    Enforces models.js invariant: request never changes dueDate; approval does.
    Only ONE pending renewal per issue (models.js ux_one_pending_renewal index).
    """
    issue_id = parse_object_id(request.form.get("issue_id"))
    reason = sanitize_string(request.form.get("reason", ""))

    if not issue_id:
        flash("Invalid loan record for renewal.", "error")
        return redirect(request.referrer or url_for("dashboard"))

    iss = Issue.find_one({"_id": issue_id})
    if not iss:
        flash("Loan record not found.", "error")
        return redirect(request.referrer or url_for("dashboard"))
    iss_norm = normalize_doc(iss)

    # Policy limit on max renewals
    parent_item_id = iss_norm.get("itemId") or iss_norm.get("item_id")
    policy = get_policy_for_item(parent_item_id)
    max_ren = policy.get("maxRenewals", 2)
    cur_ren_count = iss_norm.get("renewalCount", 0)

    if cur_ren_count >= max_ren:
        flash(f"Policy Rejection: This loan has already reached the maximum limit of {max_ren} renewals.", "error")
        return redirect(request.referrer or url_for("dashboard"))

    # Partial index enforcement: only 1 pending renewal per issue
    if Renewal.find_one({"issueId": issue_id, "status": "pending"}):
        flash("A renewal request for this loan is already pending review by the coordinator.", "warning")
        return redirect(request.referrer or url_for("dashboard"))

    today = get_today()
    cur_due = iss_norm.get("dueDate") or iss_norm.get("due_date", today)

    new_ren = {
        "_id": ObjectId(),
        "issueId": issue_id,
        "requestedBy": current_user._id,
        "requestDate": today,
        "reason": reason,
        "status": "pending",
        "previousDueDate": cur_due,
        "revisedDueDate": None,
        "decidedBy": None,
        "decidedAt": None,
        "remarks": None,
        # compatibility
        "issue_id": issue_id,
        "requested_by": current_user._id,
        "request_date": today,
        "previous_due_date": cur_due,
        "revised_due_date": None,
        "decided_by": None,
        "decided_at": None
    }
    Renewal.insert_one(new_ren)

    log_audit(
        action="RENEW_REQUEST",
        entity_type="renewal",
        entity_id=new_ren["_id"],
        actor_id=current_user._id,
        details={"issueId": str(issue_id), "reason": reason}
    )

    flash("Renewal request submitted successfully! It is now pending Coordinator approval.", "success")
    return redirect(request.referrer or url_for("dashboard"))

@loan_bp.route("/renewals/approve/<renewal_id>", methods=["POST"], endpoint="approve_renewal")
@loan_bp.route("/renewals/reject", methods=["POST"], endpoint="reject_renewal")
@loan_bp.route("/renewals/decide", methods=["POST"])
@login_required
@role_required("coordinator")
def decide_renewal(renewal_id=None):
    """
    Coordinator approves or rejects renewal.
    On approval: dueDate moves by renewalExtensionDays (default +15 days) and renewalCount increments.
    """
    if not renewal_id:
        renewal_id = parse_object_id(request.form.get("renewal_id"))
    else:
        renewal_id = parse_object_id(renewal_id)

    if request.endpoint and "approve" in request.endpoint:
        decision = "approved"
    elif request.endpoint and "reject" in request.endpoint:
        decision = "rejected"
    else:
        decision = sanitize_string(request.form.get("decision", "approved")).lower()

    remarks = sanitize_string(request.form.get("remarks", ""))

    if not renewal_id or decision not in ["approved", "rejected"]:
        flash("Invalid decision request.", "error")
        return redirect(url_for("loan.renewals_view"))

    ren = Renewal.find_one({"_id": renewal_id, "status": "pending"})
    if not ren:
        flash("Renewal request not found or has already been reviewed.", "error")
        return redirect(url_for("loan.renewals_view"))
    ren_norm = normalize_doc(ren)

    issue_id = ren_norm.get("issueId") or ren_norm.get("issue_id")
    iss = Issue.find_one({"_id": issue_id})
    if not iss:
        flash("Associated loan record not found.", "error")
        return redirect(url_for("loan.renewals_view"))
    iss_norm = normalize_doc(iss)

    today = get_today()
    parent_item_id = iss_norm.get("itemId") or iss_norm.get("item_id")
    policy = get_policy_for_item(parent_item_id)
    ext_days = policy.get("renewalExtensionDays", 15)

    if decision == "approved":
        prev_due = iss_norm.get("dueDate") or iss_norm.get("due_date", today)
        new_due = prev_due + timedelta(days=ext_days)

        # Update renewal (models.js pre-validate: approved requires revisedDueDate and decidedBy)
        Renewal.update_one(
            {"_id": renewal_id},
            {
                "$set": {
                    "status": "approved",
                    "decidedBy": current_user._id,
                    "decidedAt": today,
                    "revisedDueDate": new_due,
                    "remarks": remarks,
                    "decided_by": current_user._id,
                    "decided_at": today,
                    "revised_due_date": new_due
                }
            }
        )

        # Move dueDate and increment renewalCount
        Issue.update_one(
            {"_id": issue_id},
            {
                "$set": {"dueDate": new_due, "due_date": new_due},
                "$inc": {"renewalCount": 1, "renewal_count": 1}
            }
        )

        log_audit(
            action="RENEW_APPROVE",
            entity_type="renewal",
            entity_id=renewal_id,
            actor_id=current_user._id,
            details={"issueId": str(issue_id), "revisedDueDate": new_due.strftime("%Y-%m-%d"), "remarks": remarks}
        )

        flash(f"Renewal approved! Due date pushed to {new_due.strftime('%Y-%m-%d')} (+{ext_days} days).", "success")
    else:
        # Rejected (models.js pre-validate: rejected cannot have revisedDueDate)
        Renewal.update_one(
            {"_id": renewal_id},
            {
                "$set": {
                    "status": "rejected",
                    "decidedBy": current_user._id,
                    "decidedAt": today,
                    "revisedDueDate": None,
                    "remarks": remarks,
                    "decided_by": current_user._id,
                    "decided_at": today,
                    "revised_due_date": None
                }
            }
        )

        log_audit(
            action="RENEW_REJECT",
            entity_type="renewal",
            entity_id=renewal_id,
            actor_id=current_user._id,
            details={"issueId": str(issue_id), "remarks": remarks}
        )

        flash("Renewal request has been rejected.", "info")

    return redirect(url_for("loan.renewals_view"))
