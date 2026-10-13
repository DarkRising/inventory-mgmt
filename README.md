# Department Inventory & Student Item Issue Management System

A production-ready Departmental Equipment & Inventory Issue Management web application built with **Python 3**, **Flask**, **Jinja2**, and **Vanilla CSS (Glassmorphism)**, backed by an **11-collection MongoDB schema** with 17 compound, partial, and unique indexes conforming 100% to Mongoose models (`models.js`).

---

## 🚀 Quickstart Guide for Any PC (Windows / macOS / Linux)

### 1. Prerequisites
- **Python 3.10+** installed on your system ([Download Python](https://www.python.org/downloads/)).
- **Git** installed on your system ([Download Git](https://git-scm.com/downloads)).
- *(Optional)* **MongoDB Atlas cluster** or **local MongoDB instance** (if omitted, the system runs out-of-the-box using the built-in standalone database store).

---

### 2. Clone the Repository
Open your terminal (PowerShell, Command Prompt, or Bash) and run:
```bash
git clone https://github.com/DarkRising/inventory-mgmt.git
cd inventory-mgmt
```

---

### 3. Set Up a Virtual Environment (Recommended)

#### On Windows (PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
*(If PowerShell blocks scripts, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` or use Command Prompt: `venv\Scripts\activate.bat`)*

#### On macOS / Linux:
```bash
python3 -m venv venv
source venv/bin/activate
```

---

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

---

### 5. Configure Environment Variables (Optional)
Copy the example environment file:
- **Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```
- **macOS / Linux:**
  ```bash
  cp .env.example .env
  ```

Open `.env` in any text editor:
```env
# Optional: Connect to your MongoDB Atlas cluster (leave empty to use the zero-setup built-in store)
MONGO_URI=mongodb+srv://<username>:<password>@<cluster>.mongodb.net/department_inventory?retryWrites=true&w=majority

# Flask secret key
SECRET_KEY=super-secret-random-key-change-this
```

> **Note:** If `MONGO_URI` is left blank, the application automatically launches in **standalone demo mode** with a built-in store pre-seeded with sample lab hardware, active student loans, and audit records. **No MongoDB installation required.**

---

### 6. Run the Application
```bash
python app.py
```

You should see output similar to:
```text
[MongoDB] All 17 schema indexes from models.js created successfully.
[Startup] Initializing demo data conforming strictly to models.js...
[Seed] Successfully seeded database conforming 100% to models.js!
 * Running on http://127.0.0.1:5000
```

---

### 7. Open in Your Browser
Open your browser and navigate to:
👉 **[http://localhost:5000](http://localhost:5000)** (or **http://127.0.0.1:5000**)

---

### 🔑 Demo Login Accounts

*(The login page features 1-click **Quick Fill** buttons for instant testing)*

| Role | Username | Password | Permissions & Views |
| :--- | :--- | :--- | :--- |
| **Coordinator** | `coordinator` | `admin123` | Full access: Dashboard, Catalogue, Approve/Reject Renewals, Policy Locks, Stock Adjustments, Append-only Audit Log |
| **Staff** | `staff` | `admin123` | Operations: Issue Stock, Process Returns with condition routing, View Students & Inventory |
| **Student** | `student` | `student123` | Student Self-Service Portal (`/my-items`): View issued items, 1-click renewal requests, return receipts (IDOR protected) |

---

### 8. Run Automated Test Suite
To verify that all 11 views, atomic stock operations, condition routing, and schema invariants are working correctly:
```bash
python test_runner.py
```
Expected output:
```text
Ran 15 tests in ~2.8s — OK (100% Pass Rate)
```

---

## 📁 Repository Structure
```
inventory-mgmt/
├── app.py                     # Main Flask WSGI application & dashboard KPIs
├── db.py                      # MongoDB connection layer, index builder, in-memory mock engine
├── auth.py                    # Session manager & role authorization decorators
├── loan_routes.py             # Issue, Return, Renewal workflows & UTC demo clock
├── inventory_routes.py        # Item catalogue, serialized assets, locations & policies
├── student_routes.py          # Student borrower directory & IDOR self-service portal
├── audit.py                   # Append-only security audit log & stock adjustment ledger
├── validators.py              # Input sanitizers, regex validators, document normalizer
├── seed.py                    # Realistic department demo data generator (11 collections)
├── test_runner.py             # Automated unit tests (15 test cases)
├── TECHNICAL_SPECIFICATION.md # Full database schema & module manual
├── requirements.txt           # Python dependencies
├── static/
│   └── style.css              # Dark glassmorphic design system
└── templates/                 # 11 Jinja2 HTML templates
    ├── base.html              # Shell layout with demo clock banner & role switcher
    ├── login.html             # Login screen with quick-fill buttons
    ├── dashboard.html         # Operational KPIs & stock health invariant bar
    ├── inventory.html         # 3-tab catalogue (Quantity, Assets, Location tree)
    ├── students.html          # Student directory with semester badges
    ├── issues.html            # Equipment issue desk
    ├── returns.html           # Condition-based returns processing desk
    ├── renewals.html          # Renewal requests & Coordinator governance
    ├── policies.html          # Department baseline policies & item overrides
    ├── audit.html             # Append-only audit trail with modal JSON viewer
    └── my_items.html          # Student self-service custody portal
```
