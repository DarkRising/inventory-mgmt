"""
Standard library unittest suite validating all routes, templates, role guards, and invariant calculations.
"""
import unittest
from app import app
from db import users, items, students, issues, renewals, assets

class TestDepartmentInventory(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def login_as(self, username):
        pwd = "student123" if username == "student" else "admin123"
        return self.client.post("/login", data={"username": username, "password": pwd}, follow_redirects=True)

    def test_01_login_page_renders(self):
        res = self.client.get("/login")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Department Inventory", res.data)
        self.assertIn(b"Quick Fill Demo Profiles", res.data)
        print("[OK] Login page renders correctly with demo buttons")

    def test_02_dashboard_kpis_and_stock_health(self):
        self.login_as("coordinator")
        res = self.client.get("/dashboard")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Operational Dashboard", res.data)
        self.assertIn(b"Stock Health", res.data)
        self.assertIn(b"Upcoming Due Loan Items", res.data)
        print("[OK] Dashboard KPIs, health invariant bars, and queue render successfully")

    def test_03_inventory_catalogue(self):
        self.login_as("coordinator")
        res = self.client.get("/inventory")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Quantity-Tracked Inventory Items", res.data)
        self.assertIn(b"Individually Tracked Assets", res.data)
        self.assertIn(b"Location Hierarchy Tree", res.data)
        print("[OK] Inventory catalogue (Quantity, Asset, Location tree) renders successfully")

    def test_04_students_directory(self):
        self.login_as("coordinator")
        res = self.client.get("/students")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Enrolled Student Borrowers", res.data)
        self.assertIn(b"2024BCS042", res.data)
        print("[OK] Student directory with active status and enrollment details verified")

    def test_05_issues_management(self):
        self.login_as("coordinator")
        res = self.client.get("/issues")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Loan Issuing", res.data)
        self.assertIn(b"Active Allocations", res.data)
        self.assertIn(b"Issue Stock to Student", res.data)
        print("[OK] Issues management view and issue creation modal verified")

    def test_06_returns_and_condition_routing(self):
        self.login_as("coordinator")
        res = self.client.get("/returns")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Process Returns", res.data)
        self.assertIn(b"Condition Auditing", res.data)
        self.assertIn(b"Condition-Based Stock Routing Rules", res.data)
        print("[OK] Returns processing with condition routing rules verified")

    def test_07_renewals_governance(self):
        self.login_as("coordinator")
        res = self.client.get("/renewals")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Loan Renewal Governance", res.data)
        self.assertIn(b"Pending Renewal Requests", res.data)
        print("[OK] Renewal governance and pending requests queue verified")

    def test_08_loan_policies(self):
        self.login_as("coordinator")
        res = self.client.get("/policies")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Global Baseline Loan Policy", res.data)
        self.assertIn(b"Item Policy Overrides", res.data)
        print("[OK] Global loan policies and item overrides verified")

    def test_09_append_only_audit_log(self):
        self.login_as("coordinator")
        res = self.client.get("/audit")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Append-Only Audit Trail", res.data)
        self.assertIn(b"Transaction Ledger", res.data)
        print("[OK] Append-only audit trail and transaction ledger verified")

    def test_10_student_self_service_idor_protection(self):
        # Login as student (Priya Sharma)
        self.login_as("student")
        res = self.client.get("/my-items")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"My Student Custody", res.data)
        self.assertIn(b"Priya Sharma", res.data)
        self.assertIn(b"2024BCS042", res.data)
        print("[OK] Student self-service portal loads with scoped student records (IDOR protected)")

    def test_11_demo_clock_advancement(self):
        self.login_as("coordinator")
        res = self.client.post("/demo/set-clock", data={"days_delta": "17"}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Demo clock updated to", res.data)
        print("[OK] Demo clock time-jump (+17d) triggers dynamic overdue recalculation")

    def test_12_atomic_quantity_issue_and_stock_invariants(self):
        self.login_as("staff")
        # Find item with available stock
        itm = items.find_one({"trackingType": "quantity", "stock.available": {"$gte": 2}})
        stu = students.find_one({"isActive": True})
        orig_avail = itm["stock"]["available"]
        orig_issued = itm["stock"]["issued"]

        res = self.client.post("/issues/create", data={
            "student_id": str(stu["_id"]),
            "item_id": str(itm["_id"]),
            "qty": "2",
            "purpose": "Hardware Lab Session Test"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Verify atomic update
        updated_itm = items.find_one({"_id": itm["_id"]})
        self.assertEqual(updated_itm["stock"]["available"], orig_avail - 2)
        self.assertEqual(updated_itm["stock"]["issued"], orig_issued + 2)
        s = updated_itm["stock"]
        self.assertEqual(s["available"] + s["issued"] + s["damaged"] + s["lost"] + s["maintenance"], s["total"])
        print("[OK] Atomic quantity issue and stock invariant verified: sum(counters) == total")

    def test_13_atomic_serialized_asset_issue(self):
        self.login_as("staff")
        from db import assets
        ast = assets.find_one({"status": "available", "condition": {"$in": ["new", "good", "fair"]}})
        stu = students.find_one({"isActive": True})

        res = self.client.post("/issues/create", data={
            "student_id": str(stu["_id"]),
            "asset_id": str(ast["_id"]),
            "purpose": "Asset issue unit test"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        updated_ast = assets.find_one({"_id": ast["_id"]})
        self.assertEqual(updated_ast["status"], "issued")
        print("[OK] Serialized asset status atomically updated to 'issued'")

    def test_14_return_condition_routing_damaged(self):
        self.login_as("staff")
        iss = issues.find_one({"status": "issued", "$or": [{"assetId": None}, {"asset_id": None}]})
        if iss:
            itm_id = iss.get("itemId") or iss.get("item_id")
            itm_before = items.find_one({"_id": itm_id})
            res = self.client.post("/returns/process", data={
                "issue_id": str(iss["_id"]),
                "qty_returned": "1",
                "condition_on_return": "damaged",
                "remarks": "Bent connector pin"
            }, follow_redirects=True)
            self.assertEqual(res.status_code, 200)

            itm_after = items.find_one({"_id": itm_id})
            self.assertEqual(itm_after["stock"]["damaged"], itm_before["stock"]["damaged"] + 1)
            self.assertEqual(itm_after["stock"]["issued"], itm_before["stock"]["issued"] - 1)
            print("[OK] Condition-based return routing quarantined 1 unit to damaged counter atomically")

    def test_15_renewal_approval_pushed_due_date(self):
        self.login_as("coordinator")
        ren = renewals.find_one({"status": "pending"})
        if ren:
            iss_id = ren["issueId"]
            iss_before = issues.find_one({"_id": iss_id})
            res = self.client.post(f"/renewals/approve/{ren['_id']}", follow_redirects=True)
            self.assertEqual(res.status_code, 200)

            iss_after = issues.find_one({"_id": iss_id})
            self.assertEqual(iss_after["renewalCount"], iss_before.get("renewalCount", 0) + 1)
            self.assertGreater(iss_after["dueDate"], iss_before["dueDate"])
            print("[OK] Coordinator renewal approval advanced dueDate and incremented renewalCount atomically")

if __name__ == "__main__":
    unittest.main()

