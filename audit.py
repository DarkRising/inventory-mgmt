"""
Audit logging and stock adjustments helpers conforming to models.js.
Collections: AuditLog (audit_log) and StockAdjustment (stock_adjustments).
"""

from datetime import datetime, timezone
from bson import ObjectId
from flask import request
from db import AuditLog, StockAdjustment

def utcnow():
    return datetime.now(timezone.utc)

def log_audit(action, entity_type, entity_id, actor_id, details=None, session=None, ip=None):
    """
    Append an entry to the append-only AuditLog collection.
    Matches schema in models.js Section 11.
    """
    if details is None:
        details = {}

    entry = {
        "_id": ObjectId(),
        "action": str(action).upper(),
        "entityType": str(entity_type).lower(),
        "entityId": ObjectId(entity_id) if isinstance(entity_id, (str, ObjectId)) and entity_id else None,
        "details": details,
        "userId": ObjectId(actor_id) if actor_id else None,
        "ipAddress": ip or (request.remote_addr if request else "127.0.0.1"),
        "createdAt": utcnow()
    }
    # Provide backward compatibility aliases
    entry["entity_type"] = entry["entityType"]
    entry["entity_id"] = entry["entityId"]
    entry["user_id"] = entry["userId"]
    entry["created_at"] = entry["createdAt"]

    AuditLog.insert_one(entry, session=session)
    return entry

def log_stock_adjustment(item_id, adjustment_type, qty_change, reason, actor_id, asset_id=None, session=None):
    """
    Record mandatory stock adjustment conforming to models.js Section 10.
    """
    if len(reason.strip()) < 3:
        raise ValueError("Adjustment reason must be at least 3 characters long.")

    adj = {
        "_id": ObjectId(),
        "itemId": ObjectId(item_id),
        "assetId": ObjectId(asset_id) if asset_id else None,
        "adjustmentType": adjustment_type,
        "qtyChange": int(qty_change),
        "reason": reason.strip(),
        "adjustedBy": ObjectId(actor_id),
        "createdAt": utcnow()
    }
    # Compatibility aliases
    adj["item_id"] = adj["itemId"]
    adj["asset_id"] = adj["assetId"]
    adj["adjustment_type"] = adj["adjustmentType"]
    adj["qty_change"] = adj["qtyChange"]
    adj["adjusted_by"] = adj["adjustedBy"]

    StockAdjustment.insert_one(adj, session=session)
    return adj
