# Department Inventory & Student Item Issue Management System
## Technical Specification & Architecture Manual

---

### Executive Summary
This document provides a comprehensive, production-grade technical specification for the **Department Inventory & Student Item Issue Management System**. The system governs hardware allocations, tracking of high-value laboratory equipment and bulk consumable components, condition-based returns, multi-tiered renewal workflows, append-only auditing, and student self-service within an academic department.

The platform is built with **Python 3**, **Flask**, **Jinja2**, and a customized Vanilla CSS dark glassmorphic design system. It is strictly backed by an **11-collection MongoDB schema** with 17 compound, partial, and unique indexes conforming 100% to the Mongoose object data modeling (`models.js`).

---

## 1. Database Architecture & Schema Specifications

The MongoDB database (`department_inventory`) comprises **11 dedicated collections** and an application settings store. All schemas enforce strict validation, custom regular expressions, enum constraints, pre-save invariant hooks, and partial indexes to maintain relational and transactional integrity.

```
+-----------------------------------------------------------------------------------+
|                           MONGODB SCHEMA TOPOLOGY                                |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|   +---------------+         +---------------+         +-----------------------+   |
|   |   students    | <-------|     users     |         |       locations       |   |
|   +---------------+  (1:1)  +---------------+         +-----------------------+   |
|          ^                         ^                              ^ (hierarchical)|
|          |                         |                              |               |
|          | (1:N)                   | (audit/issue actor)          | (defaultLoc)  |
|          v                         v                              |               |
|   +---------------+         +---------------+         +-----------------------+   |
|   |    issues     | ------> |     items     | <-------|  inventory_policies   |   |
|   +---------------+ (N:1)   +---------------+  (1:1)  +-----------------------+   |
|      |         |                   ^                                              |
|      | (1:N)   | (optional 1:1)    | (parent item)                                |
|      v         v                   |                                              |
|   +------+  +-------+       +---------------+         +-----------------------+   |
|   |returns| |renewals|      |    assets     |         |   stock_adjustments   |   |
|   +------+  +-------+       +---------------+         +-----------------------+   |
|                                                                                   |
|   +---------------------------------------------------------------------------+   |
|   |                       audit_log (Append-Only Ledger)                      |   |
|   +---------------------------------------------------------------------------+   |
+-----------------------------------------------------------------------------------+
```

---

### 1.1 Collection Specifications

#### 1. `students` Collection
Stores registered student borrowers. Real-world records must never contain plain passwords.
- **Collection Name:** `students`
- **Model Reference:** `Student`
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Unique record identifier |
  | `enrolmentNo` | `String` | Yes | Unique, Trim, Regex: `/^[A-Za-z0-9\-\/]{4,20}$/` | Student institutional ID (e.g., `2024BCS042`) |
  | `name` | `String` | Yes | Trim, Maxlength: 100 | Full legal name of student |
  | `programme` | `String` | Yes | Trim | Academic degree program (e.g., `B.Tech CSE`) |
  | `semester` | `Number` | Yes | Integer, Min: 1, Max: 12 | Current academic semester |
  | `email` | `String` | No | Trim, Lowercase, Maxlength: 120 | University student email |
  | `phone` | `String` | No | Trim, Regex: `/^[0-9+\-\s]{7,15}$/` | Contact mobile number |
  | `isActive` | `Boolean` | Yes | Default: `true` | Status toggle (suspends borrowing if `false`) |
  | `createdAt` | `Date` | Yes | Auto timestamp | Timestamp of registration |
  | `updatedAt` | `Date` | Yes | Auto timestamp | Timestamp of last profile update |
- **Indexes:**
  1. `{ enrolmentNo: 1 }` (Unique)
  2. `{ programme: 1, semester: 1 }` (Compound)

---

#### 2. `users` Collection
Governs Role-Based Access Control (RBAC) and credentials.
- **Collection Name:** `users`
- **Model Reference:** `User`
- **Roles:** `coordinator`, `staff`, `student`
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Unique user identifier |
  | `username` | `String` | Yes | Unique, Trim, Regex: `/^[A-Za-z0-9_.\-]{3,40}$/` | Sign-in identifier |
  | `passwordHash` | `String` | Yes | Bcrypt / Argon2 / Werkzeug hash | Cryptographic password hash |
  | `role` | `String` | Yes | Enum: `['coordinator', 'staff', 'student']` | System access role |
  | `studentId` | `ObjectId` | Conditional | Ref: `students`, Default: `null` | Mandatory for `student`, forbidden for staff/coordinator |
  | `isActive` | `Boolean` | Yes | Default: `true` | Account active flag |
  | `failedAttempts` | `Number` | Yes | Default: `0`, Min: `0` | Consecutive failed logins counter |
  | `lockedUntil` | `Date` | No | Default: `null` | Lockout expiration timestamp (triggered at 5 fails) |
  | `lastLoginAt` | `Date` | No | Default: `null` | Last successful login timestamp |
  | `name` | `String` | No | Optional display name | Human-readable user display name |
- **Invariants & Pre-Validation:**
  - If `role === 'student'`, `studentId` MUST be populated.
  - If `role !== 'student'`, `studentId` MUST be `null`.
- **Indexes:**
  1. `{ username: 1 }` (Unique)
  2. `{ studentId: 1 }` (Unique, Partial Filter: `{ studentId: { $type: 'objectId' } }`)

---

#### 3. `locations` Collection
Hierarchical spatial topology for laboratory inventory navigation: `department` -> `laboratory` -> `room` -> `cupboard` -> `other`.
- **Collection Name:** `locations`
- **Model Reference:** `Location`
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Node identifier |
  | `name` | `String` | Yes | Trim, Maxlength: 100 | Location name |
  | `locType` | `String` | Yes | Enum: `['department', 'laboratory', 'room', 'cupboard', 'other']` | Hierarchy node classification |
  | `parentId` | `ObjectId` | No | Ref: `locations`, Default: `null` | Parent location node |
  | `description` | `String` | No | Maxlength: 300 | Placement instructions / remarks |
- **Indexes:**
  1. `{ name: 1, parentId: 1 }` (Unique Compound)

---

#### 4. `items` Collection
Central catalogue of inventory items. Supports dual tracking strategies: bulk `quantity` or serialized `asset`.
- **Collection Name:** `items`
- **Model Reference:** `Item`
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Catalogue item identifier |
  | `itemCode` | `String` | Yes | Unique, Trim, Uppercase, Max: 30 | Departmental SKU code (e.g. `RPI-4B-8G`) |
  | `name` | `String` | Yes | Trim, Maxlength: 100 | Commercial equipment name |
  | `category` | `String` | Yes | Trim | Category (e.g. `Microcontrollers`, `Measurement Tools`) |
  | `description` | `String` | No | Maxlength: 500 | Technical specs & component datasheet |
  | `makeModel` | `String` | No | Maxlength: 100 | Manufacturer make and model |
  | `trackingType` | `String` | Yes | Enum: `['asset', 'quantity']` | Unit custody strategy |
  | `defaultLocationId` | `ObjectId` | No | Ref: `locations` | Default storage location node |
  | `stock.total` | `Number` | Yes | Min: `0`, Default: `0` | Total owned volume in department |
  | `stock.available` | `Number` | Yes | Min: `0`, Default: `0` | Unallocated units ready for issue |
  | `stock.issued` | `Number` | Yes | Min: `0`, Default: `0` | Active units currently on loan |
  | `stock.damaged` | `Number` | Yes | Min: `0`, Default: `0` | Quarantined defective units |
  | `stock.lost` | `Number` | Yes | Min: `0`, Default: `0` | Unrecovered missing stock |
  | `stock.maintenance` | `Number` | Yes | Min: `0`, Default: `0` | Units out for repair or calibration |
  | `isRetired` | `Boolean` | Yes | Default: `false` | Deprecated item flag |
- **Invariants & Integrity Hooks:**
  - If `trackingType === 'quantity'`:
    $$\text{stock.available} + \text{stock.issued} + \text{stock.damaged} + \text{stock.lost} + \text{stock.maintenance} \equiv \text{stock.total}$$
  - If `trackingType === 'asset'`:
    $$\text{stock.total} = 0, \quad \text{stock.available} = 0, \quad \dots \quad (\text{units live in assets collection})$$
- **Indexes:**
  1. `{ itemCode: 1 }` (Unique)
  2. `{ category: 1 }`

---

#### 5. `assets` Collection
Individually serialized hardware units tracked by physical asset tag or serial number.
- **Collection Name:** `assets`
- **Model Reference:** `Asset`
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Physical unit identifier |
  | `assetId` | `String` | Yes | Unique, Trim, Uppercase | Department asset barcode tag (e.g. `DB-014`) |
  | `itemId` | `ObjectId` | Yes | Ref: `items` | Parent catalogue reference |
  | `serialNo` | `String` | No | Trim | Factory hardware serial number |
  | `locationId` | `ObjectId` | No | Ref: `locations` | Current physical placement |
  | `condition` | `String` | Yes | Enum: `['new', 'good', 'fair', 'poor', 'damaged']`, Default: `'good'` | Hardware physical grade |
  | `status` | `String` | Yes | Enum: `['available', 'issued', 'damaged', 'lost', 'maintenance', 'retired']`, Default: `'available'` | Operational allocation state |
  | `purchaseDate` | `Date` | No | ISO Date | Procurement intake date |
  | `remarks` | `String` | No | Maxlength: 300 | Calibration certificates, port notes |
- **Indexes:**
  1. `{ assetId: 1 }` (Unique)
  2. `{ itemId: 1, serialNo: 1 }` (Unique Compound, Partial Filter: `{ serialNo: { $type: 'string' } }`)
  3. `{ itemId: 1, status: 1 }`

---

#### 6. `inventory_policies` Collection
Loan limits and governance. A single record with `itemId: null` establishes global defaults; records with specific `itemId` override defaults.
- **Collection Name:** `inventory_policies`
- **Model Reference:** `InventoryPolicy`
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Policy rule identifier |
  | `itemId` | `ObjectId` | No | Ref: `items`, Default: `null` | Item SKU or `null` for global department default |
  | `issuePeriodDays` | `Number` | Yes | Default: `15`, Min: `1` | Base allowable issue duration |
  | `renewalExtensionDays` | `Number` | Yes | Default: `15`, Min: `1` | Additional days granted per approved renewal |
  | `maxQtyPerIssue` | `Number` | No | Min: `1` | Max units permitted per issue request |
  | `maxActiveIssuesPerStudent` | `Number` | No | Min: `1` | Max concurrent active loans per student |
  | `maxRenewals` | `Number` | Yes | Default: `2`, Min: `0` | Upper bound of renewal attempts permitted |
  | `issuableIfDamaged` | `Boolean` | Yes | Default: `false` | Safety lock: block issue of damaged units |
  | `issuableIfLost` | `Boolean` | Yes | Default: `false` | Safety lock: block issue of lost items |
  | `issuableIfMaintenance` | `Boolean` | Yes | Default: `false` | Safety lock: block issue of units in repair |
  | `updatedBy` | `ObjectId` | No | Ref: `users` | Coordinator who last modified policy |
- **Indexes:**
  1. `{ itemId: 1 }` (Unique, Partial Filter: `{ itemId: { $type: 'objectId' } }`)

---

#### 7. `issues` Collection
Active and historical student custody agreements.
- **Collection Name:** `issues`
- **Model Reference:** `Issue`
- **Important Note:** Overdue status is **never** statically stored in the database. It is derived in real-time as:
  $$\text{isActive} = \text{true} \quad \land \quad \text{dueDate} < \text{currentDate}$$
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Issue agreement identifier |
  | `studentId` | `ObjectId` | Yes | Ref: `students` | Borrower student reference |
  | `itemId` | `ObjectId` | Yes | Ref: `items` | Catalogue item issued |
  | `assetId` | `ObjectId` | No | Ref: `assets`, Default: `null` | Serialized unit (required if trackingType is asset) |
  | `qty` | `Number` | Yes | Integer, Min: `1` | Total units borrowed (always 1 for assets) |
  | `returnedQty` | `Number` | Yes | Default: `0`, Min: `0` | Units returned to date |
  | `purpose` | `String` | Yes | Trim, Maxlength: 300 | Academic project / thesis purpose |
  | `issueDate` | `Date` | Yes | UTC Date | Initial allocation date |
  | `originalDueDate` | `Date` | Yes | UTC Date | Initial due date ($\text{issueDate} + 15\text{ days}$) |
  | `dueDate` | `Date` | Yes | UTC Date | Current deadline (moves ONLY upon approved renewal) |
  | `renewalCount` | `Number` | Yes | Default: `0`, Min: `0` | Times successfully extended |
  | `status` | `String` | Yes | Enum: `['issued', 'partially_returned', 'returned']`, Default: `'issued'` | Loan lifecycle status |
  | `isActive` | `Boolean` | Yes | Default: `true` | True while $\text{returnedQty} < \text{qty}$ |
  | `issuedBy` | `ObjectId` | Yes | Ref: `users` | Staff/coordinator who disbursed equipment |
- **Invariants & Pre-Validation:**
  - $\text{returnedQty} \le \text{qty}$ (returns cannot exceed total borrowed volume).
  - If `assetId` is present, `qty` MUST equal 1.
  - $\text{dueDate} \ge \text{issueDate}$.
  - $\text{isActive} \iff \text{returnedQty} < \text{qty}$.
  - $\text{status} = \begin{cases} \text{'issued'} & \text{if } \text{returnedQty} = 0 \\ \text{'partially\_returned'} & \text{if } 0 < \text{returnedQty} < \text{qty} \\ \text{'returned'} & \text{if } \text{returnedQty} = \text{qty} \end{cases}$
- **Indexes:**
  1. `{ studentId: 1, isActive: 1 }` (Compound)
  2. `{ itemId: 1, isActive: 1 }` (Compound)
  3. `{ isActive: 1, dueDate: 1 }` (Compound — powers overdue / upcoming due queries)
  4. `{ assetId: 1 }` (Unique Partial Filter: `{ isActive: true, assetId: { $type: 'objectId' } }` — **Guarantees an asset unit can never be concurrently double-issued**)

---

#### 8. `returns` Collection
Discrete return transaction records supporting partial returns.
- **Collection Name:** `returns`
- **Model Reference:** `Return`
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Return receipt identifier |
  | `issueId` | `ObjectId` | Yes | Ref: `issues` | Associated parent issue agreement |
  | `qtyReturned` | `Number` | Yes | Integer, Min: `1` | Units returned in this intake batch |
  | `returnDate` | `Date` | Yes | UTC Date | Timestamp equipment received |
  | `conditionOnReturn` | `String` | Yes | Enum: `['good', 'fair', 'poor', 'damaged', 'lost', 'maintenance']` | Intake physical evaluation |
  | `receivedBy` | `ObjectId` | Yes | Ref: `users` | Staff technician receiving hardware |
  | `remarks` | `String` | No | Maxlength: 300 | Inspection remarks, missing cables, scratches |
- **Indexes:**
  1. `{ issueId: 1 }`

---

#### 9. `renewals` Collection
Formal renewal requests and coordinator review outcomes.
- **Collection Name:** `renewals`
- **Model Reference:** `Renewal`
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Renewal record identifier |
  | `issueId` | `ObjectId` | Yes | Ref: `issues` | Target loan agreement |
  | `requestedBy` | `ObjectId` | Yes | Ref: `users` | Student or staff initiating extension |
  | `requestDate` | `Date` | Yes | UTC Date | Timestamp request logged |
  | `reason` | `String` | No | Maxlength: 300 | Justification (e.g., project debugging) |
  | `status` | `String` | Yes | Enum: `['pending', 'approved', 'rejected']`, Default: `'pending'` | Review decision state |
  | `previousDueDate` | `Date` | Yes | UTC Date | Snapshot of deadline prior to decision |
  | `revisedDueDate` | `Date` | Conditional | UTC Date, Default: `null` | Extended deadline (populated ONLY if approved) |
  | `decidedBy` | `ObjectId` | Conditional | Ref: `users`, Default: `null` | Reviewing Coordinator |
  | `decidedAt` | `Date` | Conditional | UTC Date, Default: `null` | Decision timestamp |
  | `remarks` | `String` | No | Maxlength: 300 | Feedback from Coordinator |
- **Invariants & Pre-Validation:**
  - If `status === 'pending'`, `decidedBy` and `revisedDueDate` MUST be `null`.
  - If `status !== 'pending'`, `decidedBy` and `decidedAt` MUST be set.
  - If `status === 'approved'`, `revisedDueDate` MUST be set ($\text{previousDueDate} + \text{extensionDays}$).
  - If `status === 'rejected'`, `revisedDueDate` MUST NOT be set.
- **Indexes:**
  1. `{ issueId: 1 }`
  2. `{ issueId: 1 }` (Unique Partial Filter: `{ status: 'pending' }`, Name: `ux_one_pending_renewal` — **Guarantees only one active pending renewal per loan at a time**)

---

#### 10. `stock_adjustments` Collection
Mandatory ledger recording every administrative mutation to inventory counters.
- **Collection Name:** `stock_adjustments`
- **Model Reference:** `StockAdjustment`
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Adjustment entry identifier |
  | `itemId` | `ObjectId` | Yes | Ref: `items` | Target catalogue item |
  | `assetId` | `ObjectId` | No | Ref: `assets`, Default: `null` | Associated unit (if asset-tracked) |
  | `adjustmentType` | `String` | Yes | Enum: `['new_stock', 'correction', 'retirement', 'mark_damaged', 'mark_lost', 'mark_maintenance', 'restore_available']` | Categorical stock mutation reason |
  | `qtyChange` | `Number` | Yes | Integer | Magnitude of change |
  | `reason` | `String` | Yes | Trim, Minlength: 3, Maxlength: 300 | Mandatory explanation for audit compliance |
  | `adjustedBy` | `ObjectId` | Yes | Ref: `users` | Coordinator who authorized change |
  | `createdAt` | `Date` | Yes | UTC Date | Timestamp adjustment logged |
- **Indexes:**
  1. `{ itemId: 1, createdAt: -1 }` (Compound)

---

#### 11. `audit_log` Collection
Immutable, append-only security and operational audit trail.
- **Collection Name:** `audit_log`
- **Model Reference:** `AuditLog`
- **Security Constraint:** Updates and deletes are blocked at the application level.
- **Fields:**
  | Field | Type | Required | Constraints / Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Auto-generated | Audit entry identifier |
  | `action` | `String` | Yes | Uppercase | Event code (`LOGIN`, `ISSUE`, `RETURN`, `RENEW_REQUEST`, `RENEW_APPROVE`, `STOCK_ADJUST`, `RESTORE`) |
  | `entityType` | `String` | Yes | Lowercase | Target entity domain (`item`, `asset`, `issue`, `renewal`, `student`, `user`, `policy`) |
  | `entityId` | `ObjectId` | No | Target document ID | Primary key of affected document |
  | `details` | `Object` | Yes | Flexible JSON payload | Pre/post state diff or context data |
  | `userId` | `ObjectId` | No | Ref: `users` | Authenticated session actor |
  | `ipAddress` | `String` | No | Client IP address | Request origin IP |
  | `createdAt` | `Date` | Yes | UTC Date | Immutable event timestamp |
- **Indexes:**
  1. `{ entityType: 1, entityId: 1 }` (Compound)
  2. `{ userId: 1, createdAt: -1 }` (Compound)

---

#### 12. `app_settings` Collection
Runtime configuration and simulation metadata.
- **Collection Name:** `app_settings`
- **Model Reference:** `AppSetting`
- **Fields:**
  | Field | Type | Required | Description |
  | :--- | :--- | :--- | :--- |
  | `_id` | `ObjectId` | Yes | Setting identifier |
  | `key` | `String` | Yes | Unique configuration key (`simulated_today`, `reminder_window_days`) |
  | `value` | `String` | Yes | String representation of parameter |
- **Indexes:**
  1. `{ key: 1 }` (Unique)

---

### 1.2 Concurrency & Atomic Conditional Update Patterns

To guarantee consistency under concurrent multi-user access without overselling or race conditions, mutations use atomic conditional operations matching `models.js`:

#### A. Serialized Asset Issuance
Ensures an asset is only allocated if currently available and in acceptable physical condition:
```javascript
Asset.updateOne(
  {
    _id: assetId,
    status: 'available',
    condition: { $in: ['new', 'good', 'fair'] }
  },
  { $set: { status: 'issued' } }
);
```

#### B. Quantity Catalogue Item Issuance
Guarantees inventory is never oversold:
```javascript
Item.updateOne(
  {
    _id: itemId,
    'stock.available': { $gte: requestedQty }
  },
  {
    $inc: {
      'stock.available': -requestedQty,
      'stock.issued': requestedQty
    }
  }
);
```

#### C. Condition-Based Return Stock Routing
Restores stock based on returned physical condition:
```javascript
// For Good/Fair condition:
Item.updateOne(
  { _id: itemId },
  {
    $inc: {
      'stock.issued': -qtyReturned,
      'stock.available': qtyReturned
    }
  }
);

// For Damaged condition:
Item.updateOne(
  { _id: itemId },
  {
    $inc: {
      'stock.issued': -qtyReturned,
      'stock.damaged': qtyReturned
    }
  }
);
```

---

## 2. Web Application Architecture & Modules

```
========================================================================================
APPLICATION MODULE MAP (Python Flask / Jinja2 / PyMongo)
========================================================================================
   [ app.py ] <--- Main WSGI Controller & Global Handlers
       |
       +---> [ db.py ] <--- PyMongo / High-Fidelity Mock with Nested Dot Path Engine
       |
       +---> [ auth.py ] <--- Flask-Login Session Manager & RBAC Guards
       |
       +---> [ loan_routes.py ] <--- Issues, Returns, Renewals & UTC Demo Clock (loan_bp)
       |
       +---> [ inventory_routes.py ] <--- Items, Assets, Locations & Policies (inventory_bp)
       |
       +---> [ student_routes.py ] <--- Student Registry & IDOR Self-Service (student_bp)
       |
       +---> [ validators.py ] <--- Schema Validators & normalize_doc Bidirectional Engine
       |
       +---> [ audit.py ] <--- Append-Only Audit Trail & Stock Ledger Service
       |
       +---> [ seed.py ] <--- Demo Dataset Populator (11 collections)
       |
       +---> [ test_runner.py ] <--- Automated Test Suite (15 Unit Tests)
========================================================================================
```

---

### 2.1 Backend Modules Breakdown

#### 1. `app.py`
- **Role:** Application factory, global context injection, middleware, login/logout routes, and KPI aggregation.
- **Key Responsibilities:**
  - Configures `SECRET_KEY`, session cookie flags (`HttpOnly`, `SameSite=Lax`).
  - Registers Flask blueprints: `loan_bp`, `inventory_bp`, and `student_bp`.
  - Implements `_smart_url_for`: A Jinja2 environment global resolving unprefixed route names (e.g., `url_for('issues_view')`) to their respective blueprint names automatically (`loan.issues_view`, `inventory.inventory_view`).
  - `inject_global_data`: Injects `simulated_today`, active issues counters, pending renewals, overdue counts, and Atlas connectivity badge status into all Jinja2 templates.
  - `@app.route("/dashboard")`: Computes stock health breakdown metrics:
    $$\text{Health Pct} = \left(\frac{\text{Counter}}{\sum \text{stock.total}}\right) \times 100$$
  - `@app.route("/login")`: Implements 5-attempt brute-force lockout with a 15-minute lock window, matching `models.js` user schema constraints.

---

#### 2. `db.py`
- **Role:** Database layer, connection manager, and index engine.
- **Key Responsibilities:**
  - Manages MongoDB Atlas connectivity via `pymongo.MongoClient` and ServerApi('1').
  - Implements a high-fidelity in-memory mock engine with:
    - Nested dot-path traversal (`_get_nested`, `_set_nested`, `_inc_nested`) supporting queries like `'stock.available': { '$gte': qty }` and `$inc: { 'stock.damaged': 1 }`.
    - Deep document isolation using `copy.deepcopy` to prevent in-place reference mutations during testing.
    - Safe query operators: `$gte`, `$lte`, `$gt`, `$lt`, `$ne`, `$in`, `$or`, `$type`.
  - `init_indexes()`: Registers all 17 schema indexes from Section 1.1 on startup.
  - `get_overdue(today)`: Replicates the Mongoose `getOverdue(today)` helper function.

---

#### 3. `auth.py`
- **Role:** Session management, authorization guards, and IDOR protection.
- **Key Responsibilities:**
  - Defines the `User(UserMixin)` class wrapping database user documents. Exposes both `studentId` and `student_id`.
  - `@role_required(*allowed_roles)`: Decorator guarding endpoints against unauthorized access:
    ```python
    @role_required("coordinator")  # Restricted to departmental coordinators
    @role_required("coordinator", "staff")  # Accessible to lab technicians
    ```
  - `get_current_student_id()`: Returns `current_user.studentId` strictly for logged-in students to enforce server-side IDOR protection.

---

#### 4. `loan_routes.py` (`loan_bp`)
- **Role:** Equipment issuance, condition routing for returns, renewal governance, and simulated clock.
- **Key Routes:**
  - `GET /issues`: Displays active and historical loans with filterable status indicators (`on_time`, `due_soon`, `overdue`, `returned`).
  - `POST /issues/create`: Processes atomic issue creation with server-calculated due dates ($\text{issueDate} + 15\text{ days}$).
  - `GET /returns`: Returns desk with condition routing rules and recent return receipts.
  - `POST /returns/process`: Processes full and partial returns, updates the `Return` collection, and adjusts counters based on condition.
  - `GET /renewals`: Review queue of pending renewal requests with +15-day projected extension calculations.
  - `POST /renewals/request`: Submits renewal requests (enforces the single-pending-renewal rule).
  - `POST /renewals/approve/<renewal_id>`: Coordinator approval: updates `revisedDueDate` and increments `renewalCount`.
  - `POST /renewals/reject`: Coordinator rejection with mandatory student guidance remarks.
  - `POST /demo/set-clock`: Shifts `simulated_today` in UTC to test overdue derivations dynamically.

---

#### 5. `inventory_routes.py` (`inventory_bp`)
- **Role:** Catalogue administration, serialized unit registration, hierarchical location tree, stock adjustments, and policies.
- **Key Routes:**
  - `GET /inventory`: 3-tab inventory manager:
    1. Quantity-tracked items with 6-counter breakdown.
    2. Serialized assets with barcode IDs and condition badges.
    3. Location hierarchy tree.
  - `POST /inventory/item/create`: Registers catalogue SKUs with initial stock.
  - `POST /inventory/asset/create`: Registers physical asset units with barcode tags.
  - `POST /inventory/location/create`: Adds nodes to the departmental location hierarchy.
  - `POST /inventory/adjust`: Applies atomic stock adjustments with a mandatory reason ($\ge 3$ characters).
  - `POST /inventory/restore`: Restores damaged or maintenance quantity stock to available.
  - `POST /inventory/asset/restore`: Restores quarantined serialized units to `available` in `good` condition.
  - `GET /policies`: Global loan policies and item overrides view.
  - `POST /policies/global/update`: Updates baseline departmental loan durations and limits.
  - `POST /policies/override/create`: Configures item-specific overrides.

---

#### 6. `student_routes.py` (`student_bp`)
- **Role:** Student borrower directory and self-service custody portal.
- **Key Routes:**
  - `GET /students`: Student directory with semester badges (Sem 1–12), active status toggles, and allocation counts.
  - `POST /students/create`: Registers students with regex validation.
  - `POST /students/toggle/<student_id>`: Toggles active status (Coordinator only).
  - `GET /my-items`: Self-service portal (`/my-items`) strictly scoped to `current_user.studentId`. Provides:
    - Active custody agreements with days-remaining counters.
    - 1-click renewal requests with inline status tracking.
    - Historical return receipts.

---

#### 7. `validators.py`
- **Role:** Input validation, regular expressions, and bidirectional document normalization.
- **Key Functions:**
  - `validate_student_payload(enrolment_no, semester, phone)`: Validates format constraints.
  - `validate_user_payload(username, role, student_id)`: Enforces role-studentId constraints.
  - `normalize_doc(doc)`: Ensures bidirectional compatibility between `models.js` canonical `camelCase` keys and Jinja2 templates.

---

#### 8. `audit.py`
- **Role:** Append-only security and operational audit logging.
- **Key Functions:**
  - `log_audit(action, entity_type, entity_id, actor_id, details, ip)`: Appends an audit record to the `audit_log` collection.
  - `log_stock_adjustment(item_id, adjustment_type, qty_change, reason, actor_id, asset_id)`: Appends a stock mutation record.

---

#### 9. `seed.py`
- **Role:** Demo dataset generator.
- **Features:** Seeds realistic, anonymized academic hardware records conforming 100% to `models.js` (Arduino Uno kits, Raspberry Pi 4 boards, jumper wire packs, Rigol oscilloscopes, Dell workstations, active/overdue student loans, and audit trails).

---

#### 10. `test_runner.py`
- **Role:** Automated unit test suite using Python's standard `unittest` library.
- **Coverage:** 15 automated test cases testing authentication, role guards, catalogue views, stock invariants, atomic issuance, condition-based return quarantine, renewal extensions, and IDOR protection.

---

### 2.2 Frontend UI & Design System

The frontend is built with **custom Vanilla CSS** ([static/style.css](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/static/style.css)) and **Bootstrap Icons**:

```css
/* Core Color Palette Tokens */
:root {
  --bg-primary: #0a0e17;       /* Dark canvas base */
  --bg-surface: #121826;       /* Card & table surface */
  --bg-glass: rgba(18, 24, 38, 0.75); /* Glassmorphic panel backdrop */
  --border-glass: rgba(255, 255, 255, 0.08);
  --cyan-accent: #00f2fe;      /* Primary action accent */
  --purple-accent: #7928ca;    /* Secondary gradient accent */
  --status-available: #10b981;  /* Emerald green */
  --status-issued: #3b82f6;     /* Royal blue */
  --status-damaged: #ef4444;    /* Crimson red */
  --status-maint: #f59e0b;      /* Amber orange */
  --status-lost: #6b7280;       /* Cool gray */
}
```

#### Template Matrix:
| Template | URI | Access Level | Primary Features |
| :--- | :--- | :--- | :--- |
| [base.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/base.html) | Global Shell | All | Demo clock simulation bar, quick role switcher, Atlas status badge, responsive sidebar |
| [login.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/login.html) | `/login` | Public | Quick-fill demo credentials, account lockout banner |
| [dashboard.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/dashboard.html) | `/dashboard` | Staff, Coord | Operational KPI metrics, Stock Invariant Health Bar, Overdue Alerts, Pending Renewals Queue |
| [inventory.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/inventory.html) | `/inventory` | Authenticated | 3-Tab Explorer (Quantity, Asset, Location Tree), Add Item/Asset modals, Stock Adjustment modal, Stock Restoration modal |
| [students.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/students.html) | `/students` | Staff, Coord | Enrolled student registry, Semester badges (1–12), Active toggle, Registration modal |
| [issues.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/issues.html) | `/issues` | Authenticated | Allocation desk, Dynamic quantity/asset selector, Automatic 15-day due date calculation |
| [returns.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/returns.html) | `/returns` | Authenticated | Returns desk, Intake condition evaluation, Routing breakdown guide, Return receipts |
| [renewals.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/renewals.html) | `/renewals` | Authenticated | Renewal governance, +15-day projected extension, Approve/Reject modal with student remarks |
| [policies.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/policies.html) | `/policies` | Authenticated | Global policy editor, Safety invariant locks, Item-specific overrides table |
| [audit.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/audit.html) | `/audit` | Coordinator | Append-only audit log, Action filtering, Interactive JSON detail inspector modal |
| [my_items.html](file:///c:/Users/Divy%20Puranik/Desktop/inventory-mgmt/templates/my_items.html) | `/my-items` | Student | IDOR-scoped self-service portal, 1-click renewal requests, Custody history, Return receipts |

---

## 3. Security, Invariant Verification & Compliance

1. **Strict NoSQL Injection Prevention:**
   All queries parse and validate inputs as scalars or typed `ObjectId` instances. Input dictionaries are sanitized prior to filtering.
2. **Insecure Direct Object Reference (IDOR) Protection:**
   The student portal (`/my-items`) ignores client-supplied student IDs and binds queries strictly to `current_user.studentId`.
3. **Double-Allocation Prevention:**
   Enforced through MongoDB unique partial indexes:
   - `{ assetId: 1 }` where `{ isActive: true }` prevents concurrent double-issuance of physical units.
   - `{ issueId: 1 }` where `{ status: 'pending' }` limits loans to one active renewal request at a time.
4. **Append-Only Auditing:**
   Every login, allocation, return, stock adjustment, and policy update writes an immutable entry to `audit_log`.

---

## 4. Verification & Testing

The test suite validates all 15 operational flows:
```bash
python test_runner.py
```
```text
...............
----------------------------------------------------------------------
Ran 15 tests in 2.825s

OK (100% Pass Rate)
[MongoDB] All 17 schema indexes from models.js created successfully.
[Startup] Initializing demo data conforming strictly to models.js...
[Seed] Successfully seeded database conforming 100% to models.js!
[OK] Login page renders correctly with demo buttons
[OK] Dashboard KPIs, health invariant bars, and queue render successfully
[OK] Inventory catalogue (Quantity, Asset, Location tree) renders successfully
[OK] Student directory with active status and enrollment details verified
[OK] Issues management view and issue creation modal verified
[OK] Returns processing with condition routing rules verified
[OK] Renewal governance and pending requests queue verified
[OK] Global loan policies and item overrides verified
[OK] Append-only audit trail and transaction ledger verified
[OK] Student self-service portal loads with scoped student records (IDOR protected)
[OK] Demo clock time-jump (+17d) triggers dynamic overdue recalculation
[OK] Atomic quantity issue and stock invariant verified: sum(counters) == total
[OK] Serialized asset status atomically updated to 'issued'
[OK] Condition-based return routing quarantined 1 unit to damaged counter atomically
[OK] Coordinator renewal approval advanced dueDate and incremented renewalCount atomically
```
