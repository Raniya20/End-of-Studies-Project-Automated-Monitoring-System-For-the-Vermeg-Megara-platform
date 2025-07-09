# app/auth/routes.py
from flask import render_template, redirect, url_for, flash, request
from urllib.parse import urlsplit
from flask_login import login_user, logout_user, current_user, login_required
from app import db
from app.auth import bp
from app.models import Consultant
from app.auth.forms import LoginForm, RegistrationForm 
import jwt
from datetime import datetime, timezone
from flask import jsonify, current_app, g
import logging

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm() # Instantiate the login form

    # Process form submission and validation
    if form.validate_on_submit(): # Handles POST, CSRF check, and validation
        user = Consultant.query.filter_by(username=form.username.data).first()

        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password', 'danger')
            return redirect(url_for('auth.login'))

        login_user(user, remember=form.remember_me.data)
        flash(f'Welcome back, {user.username}!', 'success')

        next_page = request.args.get('next')
        if not next_page or urlsplit(next_page).netloc != '':
            next_page = url_for('index')
        return redirect(next_page)

    # GET request or validation failed: Render the template with the form object
    return render_template('auth/login.html', title='Sign In', form=form)

@bp.route('/logout') 
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegistrationForm() # Instantiate the registration form

    if form.validate_on_submit(): # Handles POST, CSRF check, and validation
        try:
            new_user = Consultant(username=form.username.data, email=form.email.data)
            new_user.set_password(form.password.data)
            db.session.add(new_user)
            db.session.commit()
            flash('Congratulations, you are now a registered user! Please log in.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred during registration: {e}', 'danger')
            print(f"Registration Error: {e}") # Log error

    # GET request or validation failed: Render the template with the form object
    return render_template('auth/register.html', title='Register', form=form)

@bp.route('/api/login', methods=['POST'])
def api_login():
    """API endpoint for authenticating and issuing a JWT."""
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"success": False, "message": "Username and password required"}), 400

    user = Consultant.query.filter_by(username=data['username']).first()

    if user is None or not user.check_password(data['password']):
        return jsonify({"success": False, "message": "Invalid username or password"}), 401 # Unauthorized

    # Credentials are valid, generate JWT
    try:
        payload = {
            'user_id': user.user_id,
            # 'exp': expiration time (UTC)
            'username': user.username,
            'exp': datetime.now(timezone.utc) + current_app.config['JWT_EXPIRATION_DELTA'],
            # 'iat': issued at time (UTC)
            'iat': datetime.now(timezone.utc)
        }
        token = jwt.encode(
            payload,
            current_app.config['JWT_SECRET_KEY'],
            algorithm="HS256" # Standard algorithm
        )
        logging.info(f"API Login successful for user {user.username}. JWT issued.")
        return jsonify({"success": True, "token": token}) # Return the token

    except Exception as e:
        logging.error(f"Error generating JWT for user {data['username']}: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Token generation failed"}), 500
