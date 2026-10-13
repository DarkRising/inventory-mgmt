"""
Inventory routes: items, assets, locations, stock adjustments, and policies.
Conforms 100% strictly to models.js.
"""

from datetime import datetime, timezone
from bson import ObjectId
from flask import Blueprint, request, redirect, url_for, flash, render_template
from flask_login import current_user, login_required
from db import (
    Item, Asset, Location, InventoryPolicy,
    StockAdjustment, AuditLog
)
from auth import role_required
from audit import log_audit, log_stock_adjustment
from loan_routes import get_today
from validators import (
    parse_object_id, validate_positive_int, sanitize_string,
    normalize_doc, ALLOWED_LOC_TYPES, ALLOWED_ASSET_CONDITIONS
)

inventory_bp = Blueprint("inventory", __name__)

def build_location_tree():
    """Build hierarchy: department -> laboratory -> room -> cupboard."""
    all_locs = Location.find({})
    normalized = [normalize_doc(l) for l in all_locs]
    by_id = {str(l["_id"]): dict(l, children=[]) for l in normalized}
    tree = []
    for loc_id, loc_dict in by_id.items():
        parent = loc_dict.get("parentId") or loc_dict.get("parent_id")
        if parent and str(parent) in by_id:
            by_id[str(parent)]["children"].append(loc_dict)
        else:
            tree.append(loc_dict)
    return tree

def get_location_path(loc_id):
    """Return formatted path string: Dept > Lab > Room > Cupboard."""
    path = []
    curr = Location.find_one({"_id": loc_id})
    while curr:
        path.append(curr.get("name", ""))
        p_id = curr.get("parentId") or curr.get("parent_id")
        curr = Location.find_one({"_id": p_id}) if p_id else None
    return " > ".join(reversed(path)) if path else "Unassigned"

@inventory_bp.route("/inventory")
@login_required
def inventory_view():
    today = get_today()
    q_items = [normalize_doc(x) for x in Item.find({"$or": [{"trackingType": "quantity"}, {"tracking_type": "quantity"}]})]
    for qi in q_items:
        qi["location_path"] = get_location_path(qi.get("defaultLocationId") or qi.get("location_id"))

    all_assets = [normalize_doc(x) for x in Asset.find({})]
    for a in all_assets:
        parent_id = a.get("itemId") or a.get("item_id")
        itm = Item.find_one({"_id": parent_id})
        itm_norm = normalize_doc(itm) if itm else {}
        a["item_name"] = itm_norm.get("name", "Unknown Item")
        a["item_code"] = itm_norm.get("itemCode", "")
        a["location_path"] = get_location_path(a.get("locationId") or a.get("location_id"))

    raw_locs = [normalize_doc(x) for x in Location.find({})]
    loc_tree = build_location_tree()
    categories = sorted(list(set(Item.distinct("category"))))

    asset_parents = [normalize_doc(x) for x in Item.find({"$or": [{"trackingType": "asset"}, {"tracking_type": "asset"}]})]

    return render_template(
        "inventory.html",
        active_page="inventory",
        quantity_items=q_items,
        assets=all_assets,
        raw_locations=raw_locs,
        locations_tree=loc_tree,
        categories=categories,
        raw_asset_items=asset_parents,
        simulated_today_str=today.strftime("%Y-%m-%d")
    )

@inventory_bp.route("/inventory/item/create", methods=["POST"])
@login_required
@role_required("coordinator")
def create_item():
    item_code = sanitize_string(request.form.get("item_code", "")).upper()
    name = sanitize_string(request.form.get("name", ""))
    category = sanitize_string(request.form.get("category", "Hardware"))
    description = sanitize_string(request.form.get("description", ""))
    make_model = sanitize_string(request.form.get("make_model", ""))
    tracking_type = sanitize_string(request.form.get("tracking_type", "quantity"))
    location_id = parse_object_id(request.form.get("location_id"))
    initial_qty = validate_positive_int(request.form.get("initial_qty", 0), min_val=0, default=0)

    if not item_code or not name:
        flash("Item code and name are mandatory.", "error")
        return redirect(url_for("inventory.inventory_view"))

    # Unique index check
    if Item.find_one({"$or": [{"itemCode": item_code}, {"item_code": item_code}]}):
        flash(f"Duplicate Error: Item code '{item_code}' already exists.", "error")
        return redirect(url_for("inventory.inventory_view"))

    new_item = {
        "_id": ObjectId(),
        "itemCode": item_code,
        "name": name,
        "category": category,
        "description": description,
        "makeModel": make_model,
        "trackingType": tracking_type,
        "defaultLocationId": location_id,
        "stock": {
            "total": initial_qty if tracking_type == "quantity" else 0,
            "available": initial_qty if tracking_type == "quantity" else 0,
            "issued": 0,
            "damaged": 0,
            "lost": 0,
            "maintenance": 0
        },
        "isRetired": False
    }
    # Backward compatibility aliases
    new_item["item_code"] = item_code
    new_item["tracking_type"] = tracking_type
    new_item["location_id"] = location_id
    new_item["total_qty"] = new_item["stock"]["total"]
    new_item["available_qty"] = new_item["stock"]["available"]
    new_item["issued_qty"] = 0
    new_item["damaged_qty"] = 0
    new_item["lost_qty"] = 0
    new_item["maintenance_qty"] = 0
    new_item["is_retired"] = False

    Item.insert_one(new_item)

    log_audit(
        action="CREATE_ITEM",
        entity_type="item",
        entity_id=new_item["_id"],
        actor_id=current_user._id,
        details={"itemCode": item_code, "trackingType": tracking_type, "initial_qty": initial_qty}
    )

    flash(f"Item '{name}' ({item_code}) added to catalogue successfully!", "success")
    return redirect(url_for("inventory.inventory_view"))

@inventory_bp.route("/inventory/asset/create", methods=["POST"])
@login_required
@role_required("coordinator")
def create_asset():
    item_id = parse_object_id(request.form.get("item_id"))
    asset_id = sanitize_string(request.form.get("asset_id", "")).upper()
    serial_no = sanitize_string(request.form.get("serial_no", ""))
    condition = sanitize_string(request.form.get("condition", "good"))
    location_id = parse_object_id(request.form.get("location_id"))
    remarks = sanitize_string(request.form.get("remarks", ""))

    if not item_id or not asset_id:
        flash("Parent item and Asset ID are required.", "error")
        return redirect(url_for("inventory.inventory_view"))

    if Asset.find_one({"$or": [{"assetId": asset_id}, {"asset_id": asset_id}]}):
        flash(f"Duplicate Error: Asset ID '{asset_id}' is already registered.", "error")
        return redirect(url_for("inventory.inventory_view"))

    today = get_today()
    new_asset = {
        "_id": ObjectId(),
        "assetId": asset_id,
        "itemId": item_id,
        "serialNo": serial_no or None,
        "locationId": location_id,
        "condition": condition if condition in ALLOWED_ASSET_CONDITIONS else "good",
        "status": "available",
        "purchaseDate": today,
        "remarks": remarks
    }
    new_asset["asset_id"] = asset_id
    new_asset["item_id"] = item_id
    new_asset["serial_no"] = serial_no
    new_asset["location_id"] = location_id

    Asset.insert_one(new_asset)

    log_audit(
        action="CREATE_ASSET",
        entity_type="asset",
        entity_id=new_asset["_id"],
        actor_id=current_user._id,
        details={"assetId": asset_id, "itemId": str(item_id), "condition": condition}
    )

    flash(f"Serialized Asset '{asset_id}' registered successfully!", "success")
    return redirect(url_for("inventory.inventory_view"))

@inventory_bp.route("/inventory/location/create", methods=["POST"])
@login_required
@role_required("coordinator")
def create_location():
    name = sanitize_string(request.form.get("name", ""))
    loc_type = sanitize_string(request.form.get("loc_type", "laboratory"))
    parent_id = parse_object_id(request.form.get("parent_id"))

    if not name:
        flash("Location name cannot be blank.", "error")
        return redirect(url_for("inventory.inventory_view"))

    new_loc = {
        "_id": ObjectId(),
        "name": name,
        "locType": loc_type if loc_type in ALLOWED_LOC_TYPES else "other",
        "parentId": parent_id,
        "description": sanitize_string(request.form.get("description", ""))
    }
    new_loc["loc_type"] = new_loc["locType"]
    new_loc["parent_id"] = parent_id

    Location.insert_one(new_loc)
    flash(f"Location node '{name}' created successfully.", "success")
    return redirect(url_for("inventory.inventory_view"))

@inventory_bp.route("/inventory/adjust", methods=["POST"])
@login_required
@role_required("coordinator")
def adjust_stock():
    """
    Section 2, 8 & models.js Section 10: Stock Adjustment with Mandatory Reason (>= 3 chars)
    Preserves invariant: stock.available + stock.issued + stock.damaged + stock.lost + stock.maintenance = stock.total
    """
    item_id = parse_object_id(request.form.get("item_id"))
    adj_type = sanitize_string(request.form.get("adjustment_type", "new_stock"))
    qty_change = validate_positive_int(request.form.get("qty_change"), min_val=1)
    reason = sanitize_string(request.form.get("reason", ""))

    if len(reason) < 3:
        flash("Adjustment rejected: A mandatory reason of at least 3 characters is required.", "error")
        return redirect(url_for("inventory.inventory_view"))

    if not item_id or not qty_change:
        flash("Invalid adjustment data.", "error")
        return redirect(url_for("inventory.inventory_view"))

    itm = Item.find_one({"_id": item_id})
    if not itm:
        flash("Item not found.", "error")
        return redirect(url_for("inventory.inventory_view"))

    itm_norm = normalize_doc(itm)
    avail = itm_norm.get("available_qty", 0)

    # Apply changes atomically per models.js
    if adj_type == "new_stock":
        Item.update_one(
            {"_id": item_id},
            {"$inc": {"stock.total": qty_change, "stock.available": qty_change, "total_qty": qty_change, "available_qty": qty_change}}
        )
        canonical_type = "new_stock"
    elif adj_type in ["damage", "mark_damaged"]:
        if avail < qty_change:
            flash("Cannot mark damaged: Not enough available stock.", "error")
            return redirect(url_for("inventory.inventory_view"))
        Item.update_one(
            {"_id": item_id, "stock.available": {"$gte": qty_change}},
            {"$inc": {"stock.available": -qty_change, "stock.damaged": qty_change, "available_qty": -qty_change, "damaged_qty": qty_change}}
        )
        canonical_type = "mark_damaged"
    elif adj_type in ["maintenance", "mark_maintenance"]:
        if avail < qty_change:
            flash("Cannot send to maintenance: Not enough available stock.", "error")
            return redirect(url_for("inventory.inventory_view"))
        Item.update_one(
            {"_id": item_id, "stock.available": {"$gte": qty_change}},
            {"$inc": {"stock.available": -qty_change, "stock.maintenance": qty_change, "available_qty": -qty_change, "maintenance_qty": qty_change}}
        )
        canonical_type = "mark_maintenance"
    elif adj_type in ["lost", "mark_lost"]:
        if avail < qty_change:
            flash("Cannot mark lost: Not enough available stock.", "error")
            return redirect(url_for("inventory.inventory_view"))
        Item.update_one(
            {"_id": item_id, "stock.available": {"$gte": qty_change}},
            {"$inc": {"stock.available": -qty_change, "stock.lost": qty_change, "available_qty": -qty_change, "lost_qty": qty_change}}
        )
        canonical_type = "mark_lost"
    else:
        canonical_type = "correction"

    log_stock_adjustment(item_id, canonical_type, qty_change, reason, current_user._id)
    log_audit(
        action="STOCK_ADJUST",
        entity_type="item",
        entity_id=item_id,
        actor_id=current_user._id,
        details={"type": canonical_type, "qty": qty_change, "reason": reason}
    )

    flash(f"Stock adjustment '{canonical_type}' ({qty_change} units) recorded with audit reason.", "success")
    return redirect(url_for("inventory.inventory_view"))

@inventory_bp.route("/inventory/restore", methods=["POST"])
@login_required
@role_required("coordinator")
def restore_stock():
    """
    Restore Quarantined Stock to Available (Coordinator Only)
    Atomic conditional update restoring damaged or maintenance to available.
    """
    item_id = parse_object_id(request.form.get("item_id"))
    source = sanitize_string(request.form.get("source_counter", "damaged"))
    qty = validate_positive_int(request.form.get("qty"), min_val=1)
    reason = sanitize_string(request.form.get("reason", ""))

    if len(reason) < 3:
        flash("Restoration rejected: Mandatory reason of at least 3 characters required.", "error")
        return redirect(url_for("inventory.inventory_view"))

    field_path = f"stock.{source}"
    res = Item.update_one(
        {"_id": item_id, field_path: {"$gte": qty}},
        {
            "$inc": {
                field_path: -qty,
                "stock.available": qty,
                f"{source}_qty": -qty,
                "available_qty": qty
            }
        }
    )

    if res.modified_count != 1:
        flash(f"Restoration failed: Selected source does not contain {qty} unit(s).", "error")
        return redirect(url_for("inventory.inventory_view"))

    log_stock_adjustment(item_id, "restore_available", qty, f"Restored from {source}: {reason}", current_user._id)
    log_audit(
        action="RESTORE",
        entity_type="item",
        entity_id=item_id,
        actor_id=current_user._id,
        details={"source": source, "qty": qty, "reason": reason}
    )

    flash(f"Successfully restored {qty} unit(s) from {source} back to available stock!", "success")
    return redirect(url_for("inventory.inventory_view"))

@inventory_bp.route("/policies")
@login_required
def policies_view():
    today = get_today()
    global_p = InventoryPolicy.find_one({"itemId": None})
    if not global_p:
        global_p = {
            "issuePeriodDays": 15,
            "renewalExtensionDays": 15,
            "maxRenewals": 2,
            "issuableIfDamaged": False,
            "issuableIfLost": False,
            "issuableIfMaintenance": False
        }
    global_p_norm = normalize_doc(global_p)
    global_p_norm["issue_period_days"] = global_p.get("issuePeriodDays", 15)
    global_p_norm["renewal_extension_days"] = global_p.get("renewalExtensionDays", 15)
    global_p_norm["max_renewals"] = global_p.get("maxRenewals", 2)

    overrides_raw = InventoryPolicy.find({"itemId": {"$ne": None}})
    overrides = []
    for o in overrides_raw:
        od = normalize_doc(o)
        od["issue_period_days"] = o.get("issuePeriodDays", 15)
        od["renewal_extension_days"] = o.get("renewalExtensionDays", 15)
        od["max_renewals"] = o.get("maxRenewals", 2)
        itm = Item.find_one({"_id": o.get("itemId") or o.get("item_id")})
        itm_norm = normalize_doc(itm) if itm else {}
        od["item_name"] = itm_norm.get("name", "Item")
        od["item_code"] = itm_norm.get("itemCode", "")
        overrides.append(od)

    all_itm = [normalize_doc(x) for x in Item.find({})]

    return render_template(
        "policies.html",
        active_page="policies",
        global_policy=global_p_norm,
        override_policies=overrides,
        all_items=all_itm,
        simulated_today_str=today.strftime("%Y-%m-%d")
    )

@inventory_bp.route("/policies/global/update", methods=["POST"])
@login_required
@role_required("coordinator")
def update_global_policy():
    issue_period = validate_positive_int(request.form.get("issue_period_days"), min_val=1, default=15)
    renewal_ext = validate_positive_int(request.form.get("renewal_extension_days"), min_val=1, default=15)
    max_ren = validate_positive_int(request.form.get("max_renewals"), min_val=0, default=2)
    max_per_issue = validate_positive_int(request.form.get("max_qty_per_issue"), min_val=1)
    max_per_student = validate_positive_int(request.form.get("max_active_issues_student"), min_val=1)

    now = datetime.now(timezone.utc)
    InventoryPolicy.update_one(
        {"itemId": None},
        {
            "$set": {
                "itemId": None,
                "issuePeriodDays": issue_period,
                "renewalExtensionDays": renewal_ext,
                "maxRenewals": max_ren,
                "maxQtyPerIssue": max_per_issue,
                "maxActiveIssuesPerStudent": max_per_student,
                "updatedBy": current_user._id,
                "updatedAt": now,
                # compatibility aliases
                "issue_period_days": issue_period,
                "renewal_extension_days": renewal_ext,
                "max_renewals": max_ren,
                "item_id": None
            }
        }
    )

    log_audit(
        action="UPDATE_POLICY",
        entity_type="policy",
        entity_id=None,
        actor_id=current_user._id,
        details={"issuePeriodDays": issue_period, "renewalExtensionDays": renewal_ext, "maxRenewals": max_ren}
    )

    flash("Global inventory policy updated successfully!", "success")
    return redirect(url_for("inventory.policies_view"))

@inventory_bp.route("/policies/override/create", methods=["POST"])
@login_required
@role_required("coordinator")
def create_policy_override():
    item_id = parse_object_id(request.form.get("item_id"))
    issue_period = validate_positive_int(request.form.get("issue_period_days"), min_val=1, default=7)
    renewal_ext = validate_positive_int(request.form.get("renewal_extension_days"), min_val=1, default=7)
    max_ren = validate_positive_int(request.form.get("max_renewals"), min_val=0, default=1)

    if not item_id:
        flash("Invalid item specified.", "error")
        return redirect(url_for("inventory.policies_view"))

    now = datetime.now(timezone.utc)
    InventoryPolicy.update_one(
        {"itemId": item_id},
        {
            "$set": {
                "itemId": item_id,
                "issuePeriodDays": issue_period,
                "renewalExtensionDays": renewal_ext,
                "maxRenewals": max_ren,
                "updatedBy": current_user._id,
                "updatedAt": now,
                # compatibility
                "item_id": item_id,
                "issue_period_days": issue_period,
                "renewal_extension_days": renewal_ext,
                "max_renewals": max_ren
            }
        }
    )

    flash("Item policy override created successfully!", "success")
    return redirect(url_for("inventory.policies_view"))

@inventory_bp.route("/inventory/asset/restore", methods=["POST"])
@login_required
@role_required("coordinator")
def restore_asset():
    asset_id = parse_object_id(request.form.get("asset_id"))
    reason = sanitize_string(request.form.get("reason", ""))

    if not asset_id:
        flash("Invalid asset identifier.", "error")
        return redirect(url_for("inventory.inventory_view"))

    if len(reason) < 3:
        flash("Restoration rejected: Mandatory reason of at least 3 characters required.", "error")
        return redirect(url_for("inventory.inventory_view"))

    ast = Asset.find_one({"_id": asset_id})
    if not ast:
        flash("Asset record not found.", "error")
        return redirect(url_for("inventory.inventory_view"))
    ast_norm = normalize_doc(ast)

    Asset.update_one(
        {"_id": asset_id},
        {"$set": {"status": "available", "condition": "good"}}
    )

    parent_item_id = ast_norm.get("itemId") or ast_norm.get("item_id")
    log_stock_adjustment(
        parent_item_id,
        "restore_available",
        1,
        f"Serialized unit {ast_norm.get('assetId')} restored: {reason}",
        current_user._id,
        asset_id=asset_id
    )
    log_audit(
        action="RESTORE_ASSET",
        entity_type="asset",
        entity_id=asset_id,
        actor_id=current_user._id,
        details={"assetId": ast_norm.get("assetId"), "status": "available", "reason": reason}
    )

    flash(f"Asset unit '{ast_norm.get('assetId')}' successfully restored to Available!", "success")
    return redirect(url_for("inventory.inventory_view"))

