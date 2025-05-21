# app/__init__.py
from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_mail import Mail

# Initialize extensions GLOBALLY
db = SQLAlchemy()
migrate = Migrate()
login = LoginManager() # Define login instance globally
mail = Mail() # Initialize Mail instance

login.login_view = 'auth.login'
login.login_message = 'Please log in to access this page.'
login.login_message_category = 'info'


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions with the app instance
    db.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app) # Initialize LoginManager with the app

    # --- Define user_loader HERE ---
    # Import the specific model needed for user loading
    from app.models import Consultant

    @login.user_loader
    def load_user(user_id):
        """Loads user object from user ID stored in session."""
        try:
            # Use the globally defined db instance to query
            return Consultant.query.get(int(user_id))
        except Exception as e:
            # Optional: Log the error
            # app.logger.error(f"Error loading user {user_id}: {e}")
            return None # Important for handling invalid IDs gracefully
    # --- End user_loader definition ---


    # Import and Register Blueprints
    from app.scenarios import bp as scenarios_bp
    app.register_blueprint(scenarios_bp)

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)

    from app.reports import bp as reports_bp
    app.register_blueprint(reports_bp)

    # You might still need this general models import if other parts
    # of create_app or blueprints registered here need other models
    # immediately upon app creation, but it's no longer causing
    # the specific circular import with the login instance.
    from app import models # noqa F401

    # --- Your existing routes defined within create_app ---
    @app.route('/hello')
    def hello():
        return "Hello, World!"

    @app.route('/')
    @app.route('/index')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('scenarios.list_scenarios'))
    # --- End existing routes ---

    return app