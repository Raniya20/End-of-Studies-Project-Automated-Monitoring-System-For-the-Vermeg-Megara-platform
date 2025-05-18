# run.py
from app import create_app, db
# Import models to ensure they are registered before creating tables if needed
from app.models import Consultant, Scenario # Add all your models here

# Create the app instance using the factory function
app = create_app()

# This context is useful for Flask shell and potentially scripts
@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'Consultant': Consultant, 'Scenario': Scenario} # Add all models



