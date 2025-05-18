# app/dashboard/__init__.py
from flask import Blueprint

# Use template_folder='templates' if you put templates in app/dashboard/templates/
# Or omit if using app/templates/dashboard/
bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

from app.dashboard import routes # Import routes last