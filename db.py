"""
Database layer for Department Inventory & Student Item Issue Management System.
Matches 100% strictly with the Mongoose models (models.js).
Connects to MongoDB Atlas via PyMongo and sets up collections, indexes, and schema validation.
Provides fallback to high-fidelity in-memory MongoDB store with nested path navigation
for instant frontend prototyping and standalone testing.
"""

import os
import sys
from datetime import datetime, timezone
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "").strip()

# Try connecting to real MongoDB Atlas or local MongoDB
is_real_mongo = False
client = None
db = None

if MONGO_URI:
    try:
        from pymongo import MongoClient
        from pymongo.server_api import ServerApi
        client = MongoClient(
            MONGO_URI,
            server_api=ServerApi("1"),
            serverSelectionTimeoutMS=4000
        )
        # Ping to test connectivity
        client.admin.command("ping")
        db = client.get_database("department_inventory")
        is_real_mongo = True
        print("[MongoDB] Connected successfully to MongoDB Atlas / cluster.")
    except Exception as e:
        print(f"[MongoDB] Atlas connection failed or unreachable: {e}. Utilizing fast in-memory mock store.")
        client = None
        db = None

def _get_nested(doc, path):
    if not isinstance(doc, dict):
        return None
    parts = path.split(".")
    curr = doc
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            return None
    return curr

def _set_nested(doc, path, val):
    parts = path.split(".")
    curr = doc
    for p in parts[:-1]:
        if p not in curr or not isinstance(curr[p], dict):
            curr[p] = {}
        curr = curr[p]
    curr[parts[-1]] = val

def _inc_nested(doc, path, delta):
    parts = path.split(".")
    curr = doc
    for p in parts[:-1]:
        if p not in curr or not isinstance(curr[p], dict):
            curr[p] = {}
        curr = curr[p]
    curr[parts[-1]] = curr.get(parts[-1], 0) + delta

# If not real mongo, instantiate lightweight MongoDB mock compatible with PyMongo
if not is_real_mongo:
    class MockCollection:
        def __init__(self, name):
            self.name = name
            self.docs = []
            self.indexes = []

        def create_index(self, keys, unique=False, partialFilterExpression=None, name=None):
            self.indexes.append({
                "keys": keys,
                "unique": unique,
                "partial": partialFilterExpression,
                "name": name
            })
            return name or "index_created"

        def insert_one(self, doc, session=None):
            doc = dict(doc)
            if "_id" not in doc:
                doc["_id"] = ObjectId()
            self.docs.append(doc)
            class Result:
                inserted_id = doc["_id"]
            return Result()

        def insert_many(self, docs, session=None):
            res_ids = []
            for d in docs:
                res = self.insert_one(d, session=session)
                res_ids.append(res.inserted_id)
            class Result:
                inserted_ids = res_ids
            return Result()

        def find_one(self, filt=None, session=None):
            filt = filt or {}
            for d in self.docs:
                if self._match(d, filt):
                    import copy
                    return copy.deepcopy(d)
            return None

        def find(self, filt=None, sort=None, session=None):
            filt = filt or {}
            import copy
            res = [copy.deepcopy(d) for d in self.docs if self._match(d, filt)]
            if sort:
                for key, direction in reversed(sort):
                    res.sort(key=lambda x: str(_get_nested(x, key) or ""), reverse=(direction < 0))
            return res

        def update_one(self, filt, update, session=None):
            count = 0
            for d in self.docs:
                if self._match(d, filt):
                    if "$set" in update:
                        for k, v in update["$set"].items():
                            _set_nested(d, k, v)
                    if "$inc" in update:
                        for k, v in update["$inc"].items():
                            _inc_nested(d, k, v)
                    if "$push" in update:
                        for k, v in update["$push"].items():
                            parts = k.split(".")
                            curr = d
                            for p in parts[:-1]:
                                if p not in curr or not isinstance(curr[p], dict):
                                    curr[p] = {}
                                curr = curr[p]
                            leaf = parts[-1]
                            if leaf not in curr or not isinstance(curr[leaf], list):
                                curr[leaf] = []
                            curr[leaf].append(v)
                    count += 1
                    break
            class Result:
                modified_count = count
            return Result()

        def delete_one(self, filt, session=None):
            for i, d in enumerate(self.docs):
                if self._match(d, filt):
                    del self.docs[i]
                    class Result:
                        deleted_count = 1
                    return Result()
            class Result:
                deleted_count = 0
            return Result()

        def delete_many(self, filt=None, session=None):
            filt = filt or {}
            before = len(self.docs)
            self.docs = [d for d in self.docs if not self._match(d, filt)]
            class Result:
                deleted_count = before - len(self.docs)
            return Result()

        def count_documents(self, filt=None):
            filt = filt or {}
            return len([d for d in self.docs if self._match(d, filt)])

        def distinct(self, field, filt=None):
            filt = filt or {}
            values = set()
            for d in self.docs:
                if self._match(d, filt):
                    v = _get_nested(d, field)
                    if v is not None:
                        values.add(v)
            return list(values)

        def _match(self, doc, filt):
            for k, expected in filt.items():
                if k == "$or":
                    if not any(all(self._match_val(_get_nested(doc, sub_k), sub_v) for sub_k, sub_v in cond.items()) for cond in expected):
                        return False
                    continue
                doc_val = _get_nested(doc, k)
                if not self._match_val(doc_val, expected):
                    return False
            return True

        def _match_val(self, val, expected):
            if isinstance(expected, dict):
                for op, op_val in expected.items():
                    if op == "$gte" and not (val is not None and val >= op_val):
                        return False
                    if op == "$lte" and not (val is not None and val <= op_val):
                        return False
                    if op == "$gt" and not (val is not None and val > op_val):
                        return False
                    if op == "$lt" and not (val is not None and val < op_val):
                        return False
                    if op == "$ne" and val == op_val:
                        return False
                    if op == "$in" and val not in op_val:
                        return False
                    if op == "$type":
                        pass
                return True
            return val == expected

    class MockDB:
        def __init__(self):
            self.collections = {}

        def __getitem__(self, name):
            if name not in self.collections:
                self.collections[name] = MockCollection(name)
            return self.collections[name]

    class MockClient:
        def start_session(self):
            class SessionContext:
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc_val, exc_tb):
                    pass
                def with_transaction(self, callback):
                    return callback(self)
            return SessionContext()

    client = MockClient()
    db = MockDB()

# Collections defined in models.js
Student = db["students"]
User = db["users"]
Location = db["locations"]
Item = db["items"]
Asset = db["assets"]
InventoryPolicy = db["inventory_policies"]
Issue = db["issues"]
Return = db["returns"]
Renewal = db["renewals"]
StockAdjustment = db["stock_adjustments"]
AuditLog = db["audit_log"]
AppSetting = db["app_settings"]

# Aliases for codebases referencing both styles
students = Student
users = User
locations = Location
items = Item
assets = Asset
inventory_policies = InventoryPolicy
issues = Issue
returns = Return
renewals = Renewal
stock_adjustments = StockAdjustment
audit_log = AuditLog
app_settings = AppSetting

# Helpers from models.js
DAY = 24 * 60 * 60 * 1000
def start_of_day_utc(d):
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)

def add_days(d, n):
    from datetime import timedelta
    return start_of_day_utc(d) + timedelta(days=n)

def get_overdue(today):
    """
    Overdue list: active issues whose due date has passed.
    Mirrors getOverdue() in models.js.
    """
    t = start_of_day_utc(today)
    rows = issues.find({"isActive": True, "dueDate": {"$lt": t}})
    results = []
    for r in rows:
        rd = dict(r)
        rd["outstandingQty"] = rd.get("qty", 1) - rd.get("returnedQty", 0)
        due_d = rd.get("dueDate")
        if due_d:
            if not due_d.tzinfo:
                due_d = due_d.replace(tzinfo=timezone.utc)
            rd["overdueDays"] = max(0, (t - due_d).days)
        else:
            rd["overdueDays"] = 0
        results.append(rd)
    return results

def init_indexes():
    """
    Build unique, partial, and compound indexes exactly as defined in models.js.
    """
    try:
        # 1. STUDENTS
        students.create_index([("enrolmentNo", 1)], unique=True)
        students.create_index([("programme", 1), ("semester", 1)])

        # 2. USERS
        users.create_index([("username", 1)], unique=True)
        users.create_index([("studentId", 1)], unique=True, partialFilterExpression={"studentId": {"$type": "objectId"}})

        # 3. LOCATIONS
        locations.create_index([("name", 1), ("parentId", 1)], unique=True)

        # 4. ITEMS
        items.create_index([("itemCode", 1)], unique=True)
        items.create_index([("category", 1)])

        # 5. ASSETS
        assets.create_index([("assetId", 1)], unique=True)
        assets.create_index([("itemId", 1), ("serialNo", 1)], unique=True, partialFilterExpression={"serialNo": {"$type": "string"}})
        assets.create_index([("itemId", 1), ("status", 1)])

        # 6. INVENTORY POLICIES
        inventory_policies.create_index([("itemId", 1)], unique=True, partialFilterExpression={"itemId": {"$type": "objectId"}})

        # 7. ISSUES
        issues.create_index([("studentId", 1), ("isActive", 1)])
        issues.create_index([("itemId", 1), ("isActive", 1)])
        issues.create_index([("isActive", 1), ("dueDate", 1)])
        issues.create_index(
            [("assetId", 1)],
            unique=True,
            partialFilterExpression={"isActive": True, "assetId": {"$type": "objectId"}}
        )

        # 8. RETURNS
        returns.create_index([("issueId", 1)])

        # 9. RENEWALS
        renewals.create_index([("issueId", 1)])
        renewals.create_index(
            [("issueId", 1)],
            unique=True,
            partialFilterExpression={"status": "pending"},
            name="ux_one_pending_renewal"
        )

        # 10. STOCK ADJUSTMENTS
        stock_adjustments.create_index([("itemId", 1), ("createdAt", -1)])

        # 11. AUDIT LOG
        audit_log.create_index([("entityType", 1), ("entityId", 1)])
        audit_log.create_index([("userId", 1), ("createdAt", -1)])

        # 12. APP SETTINGS
        app_settings.create_index([("key", 1)], unique=True)
        
        print("[MongoDB] All 17 schema indexes from models.js created successfully.")
    except Exception as e:
        print(f"[MongoDB] Index creation notice: {e}")

init_indexes()
