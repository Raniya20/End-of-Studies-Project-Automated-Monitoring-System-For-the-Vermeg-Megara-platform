# config.py
import ast
import os
from dotenv import load_dotenv
from datetime import timedelta

# Determine the absolute path of the directory containing this file
basedir = os.path.abspath(os.path.dirname(__file__))
# Load environment variables from .env file located in the base directory
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess' # Default if not in .env

    # Database configuration using the URL from .env
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db') # Fallback to SQLite if DATABASE_URL not set

    # Disable SQLAlchemy event system notifications (often not needed and consumes resources)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Add other configurations here later (e.g., Mail server settings)
    # --- Add Mail Configurations ---
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 25) # Default port 25 if not set
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', '1', 't']
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() in ['true', '1', 't']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

    # Safely parse MAIL_DEFAULT_SENDER if it's set as a tuple string
    mail_sender_str = os.environ.get('MAIL_DEFAULT_SENDER')
    if mail_sender_str:
        try:
             # Try parsing as tuple: ('Display Name', 'email@example.com')
             parsed_sender = ast.literal_eval(mail_sender_str)
             if isinstance(parsed_sender, tuple) and len(parsed_sender) == 2:
                  MAIL_DEFAULT_SENDER = parsed_sender
             else: # Otherwise treat as simple email string
                  MAIL_DEFAULT_SENDER = mail_sender_str
        except (ValueError, SyntaxError):
             # If parsing fails, treat as simple email string
             MAIL_DEFAULT_SENDER = mail_sender_str
    else:
         MAIL_DEFAULT_SENDER = os.environ.get('MAIL_USERNAME') # Fallback to username if not set

    ADMINS = [MAIL_DEFAULT_SENDER] if MAIL_DEFAULT_SENDER else [] # Optional: For error emails later

    # --- NEW: JWT Configuration ---
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'default-jwt-secret-please-change'
    JWT_EXPIRATION_DELTA = timedelta(hours=24) # How long tokens are valid (e.g., 24 hours)
    # --- End JWT Config ---

    # --- UPLOAD FOLDER Configuration ---
    # Define upload path relative to instance folder for security
    # The instance folder is created automatically by Flask if needed and is outside the app package
    UPLOAD_FOLDER_RELATIVE = os.environ.get('UPLOAD_FOLDER') or 'uploads/templates'
    # We'll construct the absolute path inside the app context where instance_path is known
    # For now, just store the relative path.

    # Report output directory (if not already here)
    REPORT_OUTPUT_DIR = os.environ.get('REPORT_OUTPUT_DIR', './generated_reports')