"""
Demo seed data generator for Department Inventory & Student Item Issue Management System.
Conforms 100% strictly to the 11 Mongoose collections and schemas in models.js.
"""

from datetime import datetime, timezone, timedelta
from bson import ObjectId
from werkzeug.security import generate_password_hash
from db import (
    Student, User, Location, Item, Asset,
    InventoryPolicy, Issue, Return, Renewal,
    StockAdjustment, AuditLog, AppSetting
)

def seed_database():
    # Clear collections
    for col in [Student, User, Location, Item, Asset, InventoryPolicy, Issue, Return, Renewal, StockAdjustment, AuditLog, AppSetting]:
        if hasattr(col, "docs"):
            col.docs = []
        else:
            col.delete_many({})

    now = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc)

    # 1. APP SETTINGS (models.js Section 12)
    AppSetting.insert_many([
        {"_id": ObjectId(), "key": "simulated_today", "value": "2026-10-13"},
        {"_id": ObjectId(), "key": "reminder_window_days", "value": "3"}
    ])

    # 2. LOCATIONS (models.js Section 3: department > laboratory > room > cupboard)
    loc_dept = ObjectId()
    loc_lab = ObjectId()
    loc_room = ObjectId()
    loc_cupboard = ObjectId()

    Location.insert_many([
        {
            "_id": loc_dept,
            "name": "Department of Computer Science & Engineering",
            "locType": "department",
            "parentId": None,
            "description": "Main CSE Academic & Research Department Building"
        },
        {
            "_id": loc_lab,
            "name": "IoT & Embedded Systems Research Lab",
            "locType": "laboratory",
            "parentId": loc_dept,
            "description": "Lab dedicated to microcontrollers, sensors, and hardware research"
        },
        {
            "_id": loc_room,
            "name": "Hardware Testing & Robotics Room 204",
            "locType": "room",
            "parentId": loc_lab,
            "description": "Workbenches with oscilloscopes and testing stations"
        },
        {
            "_id": loc_cupboard,
            "name": "Component Cupboard A-03",
            "locType": "cupboard",
            "parentId": loc_room,
            "description": "Secured locker for microcontroller boards and wire packs"
        }
    ])

    # 3. STUDENTS (models.js Section 1)
    sid_priya = ObjectId()
    sid_rohan = ObjectId()
    sid_ananya = ObjectId()

    Student.insert_many([
        {
            "_id": sid_priya,
            "enrolmentNo": "2024BCS042",
            "name": "Priya Sharma",
            "programme": "B.Tech Computer Science & Engineering",
            "semester": 4,
            "email": "priya.sharma@uni.edu",
            "phone": "+91-9876543210",
            "isActive": True
        },
        {
            "_id": sid_rohan,
            "enrolmentNo": "2023BCS108",
            "name": "Rohan Verma",
            "programme": "B.Tech Computer Science & Engineering",
            "semester": 6,
            "email": "rohan.verma@uni.edu",
            "phone": "+91-9876512345",
            "isActive": True
        },
        {
            "_id": sid_ananya,
            "enrolmentNo": "2024BEC015",
            "name": "Ananya Patel",
            "programme": "B.Tech Electronics & Communication",
            "semester": 4,
            "email": "ananya.patel@uni.edu",
            "phone": "+91-9876567890",
            "isActive": True
        }
    ])

    # 4. USERS (models.js Section 2)
    coord_user_id = ObjectId()
    staff_user_id = ObjectId()
    student_user_id = ObjectId()

    User.insert_many([
        {
            "_id": coord_user_id,
            "username": "coordinator",
            "passwordHash": generate_password_hash("admin123"),
            "role": "coordinator",
            "studentId": None,
            "isActive": True,
            "failedAttempts": 0,
            "lockedUntil": None,
            "lastLoginAt": now,
            "name": "Dr. Evelyn Reed (Coordinator)"
        },
        {
            "_id": staff_user_id,
            "username": "staff",
            "passwordHash": generate_password_hash("admin123"),
            "role": "staff",
            "studentId": None,
            "isActive": True,
            "failedAttempts": 0,
            "lockedUntil": None,
            "lastLoginAt": now,
            "name": "Alex Chen (Lab Technician)"
        },
        {
            "_id": student_user_id,
            "username": "student",
            "passwordHash": generate_password_hash("student123"),
            "role": "student",
            "studentId": sid_priya,
            "isActive": True,
            "failedAttempts": 0,
            "lockedUntil": None,
            "lastLoginAt": now,
            "name": "Priya Sharma (Student)"
        }
    ])

    # 5. ITEMS (models.js Section 4: catalogue & nested stock invariant)
    item_rpi = ObjectId()
    item_ard = ObjectId()
    item_jmp = ObjectId()
    item_osc = ObjectId()
    item_lap = ObjectId()

    Item.insert_many([
        # Quantity Tracked Items
        {
            "_id": item_rpi,
            "itemCode": "RPI-4B-8G",
            "name": "Raspberry Pi 4 Model B (8GB RAM)",
            "category": "Microcontrollers",
            "description": "Broadcom BCM2711, quad-core Cortex-A72 (ARM v8) 64-bit SoC @ 1.5GHz",
            "makeModel": "Raspberry Pi Foundation Model 4B",
            "trackingType": "quantity",
            "defaultLocationId": loc_cupboard,
            "stock": {
                "total": 20,
                "available": 12,
                "issued": 6,
                "damaged": 1,
                "lost": 0,
                "maintenance": 1
            },
            "isRetired": False
        },
        {
            "_id": item_ard,
            "itemCode": "ARD-UNO-R3",
            "name": "Arduino Uno R3 Microcontroller Board",
            "category": "Microcontrollers",
            "description": "ATmega328P 16MHz board with 14 digital I/O pins",
            "makeModel": "Arduino LLC R3",
            "trackingType": "quantity",
            "defaultLocationId": loc_cupboard,
            "stock": {
                "total": 35,
                "available": 27,
                "issued": 6,
                "damaged": 2,
                "lost": 0,
                "maintenance": 0
            },
            "isRetired": False
        },
        {
            "_id": item_jmp,
            "itemCode": "JMP-WIR-65P",
            "name": "Jumper Wires Premium Pack (65pcs M-M)",
            "category": "Cables & Wiring",
            "description": "Flexible solderless breadboard jumper cables",
            "makeModel": "Generic Premium Male-Male",
            "trackingType": "quantity",
            "defaultLocationId": loc_cupboard,
            "stock": {
                "total": 50,
                "available": 42,
                "issued": 8,
                "damaged": 0,
                "lost": 0,
                "maintenance": 0
            },
            "isRetired": False
        },
        # Asset Tracked Items (Counters stay 0)
        {
            "_id": item_osc,
            "itemCode": "OSC-RIGOL-50",
            "name": "Rigol DS1054Z 50MHz Digital Oscilloscope",
            "category": "Measurement Tools",
            "description": "4 Analog Channels, 50 MHz Bandwidth, 1 GSa/s Real-time Sample Rate",
            "makeModel": "Rigol DS1054Z 4CH",
            "trackingType": "asset",
            "defaultLocationId": loc_room,
            "stock": {
                "total": 0,
                "available": 0,
                "issued": 0,
                "damaged": 0,
                "lost": 0,
                "maintenance": 0
            },
            "isRetired": False
        },
        {
            "_id": item_lap,
            "itemCode": "LAP-DELL-PRC",
            "name": "Dell Precision 3560 Mobile Workstation",
            "category": "Computing Hardware",
            "description": "Intel Core i7-1185G7, 32GB RAM, NVIDIA T500, Linux Workstation",
            "makeModel": "Dell Precision 3560",
            "trackingType": "asset",
            "defaultLocationId": loc_room,
            "stock": {
                "total": 0,
                "available": 0,
                "issued": 0,
                "damaged": 0,
                "lost": 0,
                "maintenance": 0
            },
            "isRetired": False
        }
    ])

    # 6. ASSETS (models.js Section 5: individually tracked units)
    ast_osc1 = ObjectId()
    ast_osc2 = ObjectId()
    ast_osc3 = ObjectId()
    ast_lap1 = ObjectId()
    ast_lap2 = ObjectId()

    Asset.insert_many([
        {
            "_id": ast_osc1,
            "assetId": "DB-014",
            "itemId": item_osc,
            "serialNo": "DS1ZA224001924",
            "locationId": loc_room,
            "condition": "good",
            "status": "available",
            "purchaseDate": now - timedelta(days=180),
            "remarks": "Calibrated on delivery, station 1"
        },
        {
            "_id": ast_osc2,
            "assetId": "DB-015",
            "itemId": item_osc,
            "serialNo": "DS1ZA224001925",
            "locationId": loc_room,
            "condition": "fair",
            "status": "issued",
            "purchaseDate": now - timedelta(days=180),
            "remarks": "Probe 2 ground clip missing"
        },
        {
            "_id": ast_osc3,
            "assetId": "DB-016",
            "itemId": item_osc,
            "serialNo": "DS1ZA224001926",
            "locationId": loc_room,
            "condition": "damaged",
            "status": "damaged",
            "purchaseDate": now - timedelta(days=120),
            "remarks": "Screen flickering / CH1 unstable, quarantined"
        },
        {
            "_id": ast_lap1,
            "assetId": "WS-101",
            "itemId": item_lap,
            "serialNo": "CN0G81928374",
            "locationId": loc_room,
            "condition": "good",
            "status": "available",
            "purchaseDate": now - timedelta(days=90),
            "remarks": "Ubuntu 22.04 LTS pre-installed"
        },
        {
            "_id": ast_lap2,
            "assetId": "WS-102",
            "itemId": item_lap,
            "serialNo": "CN0G81928375",
            "locationId": loc_room,
            "condition": "good",
            "status": "issued",
            "purchaseDate": now - timedelta(days=90),
            "remarks": "Issued for senior AI thesis project"
        }
    ])

    # 7. INVENTORY POLICIES (models.js Section 6)
    InventoryPolicy.insert_many([
        {
            "_id": ObjectId(),
            "itemId": None,  # Global default
            "issuePeriodDays": 15,
            "renewalExtensionDays": 15,
            "maxQtyPerIssue": 5,
            "maxActiveIssuesPerStudent": 3,
            "maxRenewals": 2,
            "issuableIfDamaged": False,
            "issuableIfLost": False,
            "issuableIfMaintenance": False,
            "updatedBy": coord_user_id
        },
        {
            "_id": ObjectId(),
            "itemId": item_osc,  # Item override for expensive oscilloscope
            "issuePeriodDays": 7,
            "renewalExtensionDays": 7,
            "maxQtyPerIssue": 1,
            "maxActiveIssuesPerStudent": 1,
            "maxRenewals": 1,
            "issuableIfDamaged": False,
            "issuableIfLost": False,
            "issuableIfMaintenance": False,
            "updatedBy": coord_user_id
        }
    ])

    # 8. ISSUES (models.js Section 7)
    iss_rpi = ObjectId()
    iss_osc = ObjectId()
    iss_lap = ObjectId()
    iss_jmp = ObjectId()

    # Priya: 2 RPi (Active, on-time)
    due_priya = now - timedelta(days=5) + timedelta(days=15)
    # Rohan: 1 Oscilloscope (Active, OVERDUE: issued 18 days ago with 7-day limit)
    due_rohan = now - timedelta(days=18) + timedelta(days=7)
    # Ananya: 1 Laptop (Active, due soon)
    due_ananya = now - timedelta(days=10) + timedelta(days=15)
    # Priya: returned jumper wires
    due_jmp = now - timedelta(days=25) + timedelta(days=15)

    Issue.insert_many([
        {
            "_id": iss_rpi,
            "studentId": sid_priya,
            "itemId": item_rpi,
            "assetId": None,
            "qty": 2,
            "returnedQty": 0,
            "purpose": "Embedded IoT Gateway course project",
            "issueDate": now - timedelta(days=5),
            "originalDueDate": due_priya,
            "dueDate": due_priya,
            "renewalCount": 0,
            "status": "issued",
            "isActive": True,
            "issuedBy": staff_user_id
        },
        {
            "_id": iss_osc,
            "studentId": sid_rohan,
            "itemId": item_osc,
            "assetId": ast_osc2,
            "qty": 1,
            "returnedQty": 0,
            "purpose": "Digital signal processing lab coursework",
            "issueDate": now - timedelta(days=18),
            "originalDueDate": due_rohan,
            "dueDate": due_rohan,
            "renewalCount": 0,
            "status": "issued",
            "isActive": True,
            "issuedBy": staff_user_id
        },
        {
            "_id": iss_lap,
            "studentId": sid_ananya,
            "itemId": item_lap,
            "assetId": ast_lap2,
            "qty": 1,
            "returnedQty": 0,
            "purpose": "FPGA synthesis and robotic simulation",
            "issueDate": now - timedelta(days=10),
            "originalDueDate": due_ananya,
            "dueDate": due_ananya,
            "renewalCount": 0,
            "status": "issued",
            "isActive": True,
            "issuedBy": staff_user_id
        },
        {
            "_id": iss_jmp,
            "studentId": sid_priya,
            "itemId": item_jmp,
            "assetId": None,
            "qty": 4,
            "returnedQty": 4,
            "purpose": "Robotics breadboard prototyping",
            "issueDate": now - timedelta(days=25),
            "originalDueDate": due_jmp,
            "dueDate": due_jmp,
            "renewalCount": 0,
            "status": "returned",
            "isActive": False,
            "issuedBy": staff_user_id
        }
    ])

    # 9. RETURNS (models.js Section 8: separate returns collection)
    Return.insert_one({
        "_id": ObjectId(),
        "issueId": iss_jmp,
        "qtyReturned": 4,
        "returnDate": now - timedelta(days=12),
        "conditionOnReturn": "good",
        "receivedBy": staff_user_id,
        "remarks": "Returned in full, intact connector pins"
    })

    # 10. RENEWALS (models.js Section 9)
    Renewal.insert_one({
        "_id": ObjectId(),
        "issueId": iss_lap,
        "requestedBy": student_user_id,
        "requestDate": now - timedelta(days=1),
        "reason": "Need extra days to complete FPGA synthesis compile runs",
        "status": "pending",
        "previousDueDate": due_ananya,
        "revisedDueDate": None,
        "decidedBy": None,
        "decidedAt": None,
        "remarks": None
    })

    # 11. STOCK ADJUSTMENTS (models.js Section 10)
    StockAdjustment.insert_many([
        {
            "_id": ObjectId(),
            "itemId": item_rpi,
            "assetId": None,
            "adjustmentType": "new_stock",
            "qtyChange": 20,
            "reason": "Initial laboratory intake purchase order #PO-2026-881",
            "adjustedBy": coord_user_id,
            "createdAt": now - timedelta(days=60)
        },
        {
            "_id": ObjectId(),
            "itemId": item_rpi,
            "assetId": None,
            "adjustmentType": "mark_damaged",
            "qtyChange": 1,
            "reason": "Short-circuit damage on GPIO pin 4 during student lab session",
            "adjustedBy": staff_user_id,
            "createdAt": now - timedelta(days=10)
        }
    ])

    # 12. AUDIT LOG (models.js Section 11: append-only)
    AuditLog.insert_many([
        {
            "_id": ObjectId(),
            "action": "LOGIN",
            "entityType": "user",
            "entityId": coord_user_id,
            "details": {"username": "coordinator", "status": "success"},
            "userId": coord_user_id,
            "ipAddress": "127.0.0.1",
            "createdAt": now - timedelta(hours=2)
        },
        {
            "_id": ObjectId(),
            "action": "ISSUE",
            "entityType": "issue",
            "entityId": iss_osc,
            "details": {"assetId": "DB-015", "student": "Rohan Verma", "qty": 1},
            "userId": staff_user_id,
            "ipAddress": "127.0.0.1",
            "createdAt": now - timedelta(days=18)
        },
        {
            "_id": ObjectId(),
            "action": "RENEW_REQUEST",
            "entityType": "renewal",
            "entityId": iss_lap,
            "details": {"reason": "FPGA synthesis compile runs", "issueId": str(iss_lap)},
            "userId": student_user_id,
            "ipAddress": "127.0.0.1",
            "createdAt": now - timedelta(days=1)
        }
    ])

    print("[Seed] Successfully seeded database conforming 100% to models.js!")

if __name__ == "__main__":
    seed_database()
