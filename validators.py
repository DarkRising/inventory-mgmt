"""
Validators and schema invariants matching models.js.
Enforces regex constraints, enum values, and Mongoose pre-validate hook logic.
"""

import re
from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId

ALLOWED_ROLES = {"coordinator", "staff", "student"}
ALLOWED_TRACKING_TYPES = {"quantity", "asset"}
ALLOWED_LOC_TYPES = {"department", "laboratory", "room", "cupboard", "other"}
ALLOWED_ASSET_CONDITIONS = {"new", "good", "fair", "poor", "damaged"}
ALLOWED_ASSET_STATUSES = {"available", "issued", "damaged", "lost", "maintenance", "retired"}
ALLOWED_RETURN_CONDITIONS = {"good", "fair", "poor", "damaged", "lost", "maintenance"}
ALLOWED_ISSUE_STATUSES = {"issued", "partially_returned", "returned"}
ALLOWED_RENEWAL_STATUSES = {"pending", "approved", "rejected"}
ALLOWED_ADJUSTMENT_TYPES = {
    "new_stock", "correction", "retirement",
    "mark_damaged", "mark_lost", "mark_maintenance", "restore_available"
}

ENROLMENT_REGEX = re.compile(r"^[A-Za-z0-9\-\/]{4,20}$")
USERNAME_REGEX = re.compile(r"^[A-Za-z0-9_.\-]{3,40}$")
PHONE_REGEX = re.compile(r"^[0-9+\-\s]{7,15}$")

def parse_object_id(val):
    """Safely validate and parse an ObjectId string. Returns ObjectId or None."""
    if not val:
        return None
    if isinstance(val, ObjectId):
        return val
    if not isinstance(val, str):
        return None
    val = val.strip()
    try:
        return ObjectId(val)
    except (InvalidId, TypeError):
        return None

def validate_positive_int(val, min_val=1, default=None):
    """Ensure integer is scalar and >= min_val."""
    if val is None or val == "":
        return default
    try:
        num = int(val)
        if num < min_val:
            return None
        return num
    except (ValueError, TypeError):
        return None

def sanitize_string(val, max_length=255):
    """Ensure scalar string and strip whitespace."""
    if val is None:
        return ""
    if not isinstance(val, str):
        return ""
    return val.strip()[:max_length]

def validate_student_payload(enrolment_no, semester, phone=None):
    if not ENROLMENT_REGEX.match(enrolment_no):
        return False, "Enrolment number must match alphanumeric format (4-20 chars)."
    if not (1 <= semester <= 12):
        return False, "Semester must be an integer between 1 and 12."
    if phone and not PHONE_REGEX.match(phone):
        return False, "Phone number format invalid (7-15 digits/symbols)."
    return True, None

def validate_user_payload(username, role, student_id=None):
    if not USERNAME_REGEX.match(username):
        return False, "Username must be 3-40 alphanumeric characters, underscores, dashes, or dots."
    if role not in ALLOWED_ROLES:
        return False, f"Invalid role '{role}'."
    # Mongoose pre-validate hook:
    if role == "student" and not student_id:
        return False, "Student account needs studentId"
    if role != "student" and student_id:
        return False, "Staff/coordinator account must not have studentId"
    return True, None

def normalize_doc(doc):
    """
    Ensures bidirectional compatibility for Jinja2 templates and Python helpers.
    Exposes both camelCase (canonical in models.js) and snake_case convenience aliases.
    """
    if not isinstance(doc, dict):
        return doc
    d = dict(doc)
    
    # Students
    if "enrolmentNo" in d:
        d["enrolment_no"] = d["enrolmentNo"]
    elif "enrolment_no" in d:
        d["enrolmentNo"] = d["enrolment_no"]

    if "isActive" in d:
        d["is_active"] = d["isActive"]
    elif "is_active" in d:
        d["isActive"] = d["is_active"]

    # Items & Stock
    if "itemCode" in d:
        d["item_code"] = d["itemCode"]
    elif "item_code" in d:
        d["itemCode"] = d["item_code"]

    if "trackingType" in d:
        d["tracking_type"] = d["trackingType"]
    elif "tracking_type" in d:
        d["trackingType"] = d["tracking_type"]

    if "defaultLocationId" in d:
        d["default_location_id"] = d["defaultLocationId"]
        d["location_id"] = d["defaultLocationId"]
    elif "location_id" in d:
        d["defaultLocationId"] = d["location_id"]

    if "stock" in d and isinstance(d["stock"], dict):
        s = d["stock"]
        d["total_qty"] = s.get("total", 0)
        d["available_qty"] = s.get("available", 0)
        d["issued_qty"] = s.get("issued", 0)
        d["damaged_qty"] = s.get("damaged", 0)
        d["lost_qty"] = s.get("lost", 0)
        d["maintenance_qty"] = s.get("maintenance", 0)
    elif "available_qty" in d:
        d["stock"] = {
            "total": d.get("total_qty", 0),
            "available": d.get("available_qty", 0),
            "issued": d.get("issued_qty", 0),
            "damaged": d.get("damaged_qty", 0),
            "lost": d.get("lost_qty", 0),
            "maintenance": d.get("maintenance_qty", 0)
        }

    # Assets
    if "assetId" in d:
        d["asset_id"] = d["assetId"]
    elif "asset_id" in d:
        d["assetId"] = d["asset_id"]

    if "serialNo" in d:
        d["serial_no"] = d["serialNo"]
    elif "serial_no" in d:
        d["serialNo"] = d["serial_no"]

    if "locationId" in d:
        d["location_id"] = d["locationId"]
    elif "location_id" in d:
        d["locationId"] = d["location_id"]

    # Locations
    if "locType" in d:
        d["loc_type"] = d["locType"]
    elif "loc_type" in d:
        d["locType"] = d["loc_type"]

    if "parentId" in d:
        d["parent_id"] = d["parentId"]
    elif "parent_id" in d:
        d["parentId"] = d["parent_id"]

    # Issues
    if "studentId" in d:
        d["student_id"] = d["studentId"]
    elif "student_id" in d:
        d["studentId"] = d["student_id"]

    if "itemId" in d:
        d["item_id"] = d["itemId"]
    elif "item_id" in d:
        d["itemId"] = d["item_id"]

    if "assetId" in d:
        d["asset_id"] = d["assetId"]
    elif "asset_id" in d:
        d["assetId"] = d["asset_id"]

    if "returnedQty" in d:
        d["returned_qty"] = d["returnedQty"]
    elif "returned_qty" in d:
        d["returnedQty"] = d["returned_qty"]

    if "dueDate" in d:
        d["due_date"] = d["dueDate"]
    elif "due_date" in d:
        d["dueDate"] = d["due_date"]

    if "issueDate" in d:
        d["issue_date"] = d["issueDate"]
    elif "issue_date" in d:
        d["issueDate"] = d["issue_date"]

    if "originalDueDate" in d:
        d["original_due_date"] = d["originalDueDate"]
    elif "original_due_date" in d:
        d["originalDueDate"] = d["original_due_date"]

    if "renewalCount" in d:
        d["renewal_count"] = d["renewalCount"]
    elif "renewal_count" in d:
        d["renewalCount"] = d["renewalCount"]

    return d
