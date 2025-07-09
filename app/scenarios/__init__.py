# app/scenarios/__init__.py 
from flask import Blueprint

bp = Blueprint('scenarios', __name__, url_prefix='/scenarios')

from app.scenarios import routes # noqa F401