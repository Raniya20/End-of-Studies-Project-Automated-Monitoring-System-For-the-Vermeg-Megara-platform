# app/auth/decorators.py
import jwt
from functools import wraps
from flask import request, jsonify, current_app, g
from app.models import Consultant 
import logging

def token_required(f):
    """Decorator to protect routes requiring a valid JWT."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        # Check for token in Authorization header (Bearer scheme)
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                # Split "Bearer <token>"
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({"success": False, "message": "Malformed Authorization header"}), 401

        if not token:
            return jsonify({"success": False, "message": "Authorization token is missing"}), 401

        try:
            # Decode and verify the token
            payload = jwt.decode(
                token,
                current_app.config['JWT_SECRET_KEY'],
                algorithms=["HS256"]
            )
            user_id = payload['user_id']
            # Fetch the user associated with the token
            # Use g to store user for access within the request context
            g.current_user = Consultant.query.get(user_id)
            if g.current_user is None:
                 # User ID in token doesn't match a user in DB
                 logging.warning(f"Token valid but user ID {user_id} not found.")
                 return jsonify({"success": False, "message": "User not found"}), 401

        except jwt.ExpiredSignatureError:
            logging.info("Expired token received.")
            return jsonify({"success": False, "message": "Token has expired"}), 401
        except jwt.InvalidTokenError as e:
            logging.warning(f"Invalid token received: {e}")
            return jsonify({"success": False, "message": "Token is invalid"}), 401
        except Exception as e:
             logging.error(f"Unexpected error during token validation: {e}", exc_info=True)
             return jsonify({"success": False, "message": "Token validation error"}), 500

        # Token is valid, user loaded into g.current_user, proceed to the route function
        return f(*args, **kwargs)
    return decorated_function