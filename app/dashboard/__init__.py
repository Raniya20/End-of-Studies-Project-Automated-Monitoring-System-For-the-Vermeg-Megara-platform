# app/dashboard/__init__.py
from flask import Blueprint


bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

from app.dashboard import routes 