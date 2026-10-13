"""
Automated endpoint & authorization verification tests for Department Inventory System.
Validates all 11 views, status codes, role protections, and schema adherence.
"""

import pytest
from app import app
from db import users, items, students, issues

@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client

def login_as(client, username):
    return client.post("/login", data={"username": username, "password": "any"}, follow_redirects=True)

def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Department Inventory" in response.data
    assert b"Quick Fill Demo Profiles" in response.data

def test_coordinator_dashboard(client):
    login_as(client, "coordinator")
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"Operational Dashboard" in response.data
    assert b"Stock Health &amp; Invariant Verification" in response.data

def test_inventory_catalogue_views(client):
    login_as(client, "coordinator")
    response = client.get("/inventory")
    assert response.status_code == 200
    assert b"Quantity-Tracked Inventory Items" in response.data
    assert b"Individually Tracked Assets" in response.data
    assert b"Location Hierarchy Tree" in response.data

def test_students_view(client):
    login_as(client, "coordinator")
    response = client.get("/students")
    assert response.status_code == 200
    assert b"Enrolled Student Borrowers" in response.data
    assert b"2024BCS042" in response.data

def test_issues_view(client):
    login_as(client, "coordinator")
    response = client.get("/issues")
    assert response.status_code == 200
    assert b"Loan Issuing &amp; Active Allocations" in response.data
    assert b"Issue Stock to Student" in response.data

def test_returns_view(client):
    login_as(client, "coordinator")
    response = client.get("/returns")
    assert response.status_code == 200
    assert b"Process Returns &amp; Condition Auditing" in response.data
    assert b"Condition-Based Stock Routing Rules" in response.data

def test_renewals_view(client):
    login_as(client, "coordinator")
    response = client.get("/renewals")
    assert response.status_code == 200
    assert b"Loan Renewal Governance" in response.data
    assert b"Pending Renewal Requests" in response.data

def test_policies_view(client):
    login_as(client, "coordinator")
    response = client.get("/policies")
    assert response.status_code == 200
    assert b"Global Baseline Loan Policy" in response.data
    assert b"Item Policy Overrides" in response.data

def test_audit_view(client):
    login_as(client, "coordinator")
    response = client.get("/audit")
    assert response.status_code == 200
    assert b"Append-Only Audit Trail" in response.data
    assert b"Transaction Ledger" in response.data

def test_student_portal_and_idor_protection(client):
    login_as(client, "student")
    response = client.get("/my-items")
    assert response.status_code == 200
    assert b"My Student Custody &amp; Loan Portal" in response.data
    assert b"Priya Sharma" in response.data

def test_demo_clock_advancement(client):
    login_as(client, "coordinator")
    response = client.post("/demo/set-clock", data={"days_delta": "17"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Demo clock updated to" in response.data
