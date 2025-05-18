# app/scenarios/__init__.py (Updated)
from flask import Blueprint

# REMOVE the template_folder argument
bp = Blueprint('scenarios', __name__, url_prefix='/scenarios')

from app.scenarios import routes # noqa F401