# app/auth/__init__.py
from flask import Blueprint

bp = Blueprint('auth', __name__, url_prefix='/auth') # No template_folder

from app.auth import routes # noqa F401