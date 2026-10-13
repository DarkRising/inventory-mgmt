"""
Authentication, Flask-Login, role guards, and lockout enforcement.
Matches User model in models.js.
"""

from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import redirect, url_for, flash, abort, session
from flask_login import LoginManager, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from bson import ObjectId
from db import User as UserModel, Student as StudentModel
from audit import log_audit

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to access this departmental area."
login_manager.login_message_category = "warning"

class User(UserMixin):
    def __init__(self, doc):
        self.doc = doc
        self.id = str(doc["_id"])
        self._id = doc["_id"]
        self.username = doc.get("username", "")
        self.role = doc.get("role", "student")
        self.student_id = doc.get("studentId") or doc.get("student_id")
        self.studentId = self.student_id
        self.name = doc.get("name", self.username)
        self._is_active = doc.get("isActive", doc.get("is_active", True))

    @property
    def is_active(self):
        return bool(self._is_active)

@login_manager.user_loader
def load_user(user_id):
    try:
        doc = UserModel.find_one({"_id": ObjectId(user_id)})
        if doc:
            return User(doc)
    except Exception:
        pass
    return None

def role_required(*allowed_roles):
    """Enforce server-side role authorization decorator."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))
            if current_user.role not in allowed_roles:
                flash(f"Access Denied: You do not have permission for this action ({current_user.role}).", "error")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_current_student_id():
    """IDOR protection: return studentId strictly linked to logged-in user."""
    if not current_user.is_authenticated or current_user.role != "student":
        return None
    return current_user.student_id
