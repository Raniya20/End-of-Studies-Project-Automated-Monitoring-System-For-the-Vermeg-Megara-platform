# app/reports/__init__.py
from flask import Blueprint

bp = Blueprint('reports', __name__, url_prefix='/reports')

from app.reports import routes # Import routes last