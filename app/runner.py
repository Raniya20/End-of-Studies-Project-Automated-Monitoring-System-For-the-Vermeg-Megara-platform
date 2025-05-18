# app/runner.py

import os
import time
import logging
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Page, expect
import pandas as pd
import numpy as np # Import numpy for NaN
import re # Import re for parsing remarks
import joblib # Import joblib for loading models
from sklearn.preprocessing import StandardScaler # Example preprocessor type hint
# from sklearn.ensemble import IsolationForest # Example model type hint
from sqlalchemy.orm import scoped_session, sessionmaker
import openpyxl
from openpyxl.utils.dataframe import dataframe_to_rows
from pathlib import Path # For easier path manipulation

from flask_mail import Message # Import Message class
from flask import current_app # To access app config like MAIL_DEFAULT_SENDER

# Import necessary components from your app
from app import db # Assumes running within Flask context or DB session configured
from app.models import (Scenario, ScenarioStep, ExecutionLog, MonitoringResult,
                        ProcessingRule, ActionTypeEnum, ExecutionStatusEnum, RuleOperatorEnum)

from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
# from sklearn.ensemble import IsolationForest # Type hint if needed

# --- ADD CONSTANTS AND HELPER FUNCTION HERE ---

# Define Standardized Column Names (MUST match names used in training/CSV)
PROCESS_COL = 'Process'
PERIODICITY_COL = 'Periodicity'
STATUS_TODAY_COL = 'Status_Today'
STATUS_LEGEND_COL = 'Status_Legend'
REMARKS_COL = 'Remarks'
# Add others if needed

# Engineered Feature Names (MUST match names used in training)
FEATURE_EXTRACTED_COUNT = 'Extracted_Count'
FEATURE_IS_PENDING = 'Is_Pending_Today'
FEATURE_IS_ERROR_LEGEND = 'Is_Error_Legend'

def parse_count_from_remarks(remark):
    """Extracts the first integer number from the remarks string."""
    if not isinstance(remark, str):
        return np.nan # Return NaN if remark is not a string
    # Look for sequences of digits, possibly with commas or spaces
    match = re.search(r'\d{1,3}(?:[,\s]\d{3})*|\d+', remark)
    if match:
        try:
            # Remove commas/spaces and convert to int
            num_str = match.group(0).replace(',', '').replace(' ', '')
            return int(num_str)
        except (ValueError, TypeError):
            return np.nan # Return NaN if conversion fails
    return np.nan # Return NaN if no number found

# --- END ADDED CONSTANTS AND HELPER FUNCTION ---



# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class AutomationRunner:
    """
    Executes a monitoring scenario using Playwright based on configuration
    stored in the database. Includes data processing, anomaly detection structure,
    and report generation.
    """
    DEFAULT_TIMEOUT = 15000 # Milliseconds (15 seconds)

    def __init__(self, scenario_id: int, app, headless: bool = True):
        """
        Initializes the runner for a specific scenario.
        :param scenario_id: The ID of the Scenario to run.
        :param headless: Whether to run the browser in headless mode.
        """
        self.scenario_id = scenario_id
        self.headless = headless
        self.app = app # Store the app instance
        self.scenario: Scenario | None = None
        self.log_entry: ExecutionLog | None = None
        self.playwright = None
        self.browser = None
        self.page: Page | None = None
        self.results = {} # Stores extracted data {label: data (str or DataFrame)}
        self.processing_rules: list[ProcessingRule] = [] # Stores processing rules
        # --- Anomaly Detection Attributes ---
        self.anomaly_model = None # Will hold the loaded model instance
        self.anomaly_scaler = None # Will hold the loaded scaler instance
        # Use environment variables for paths, default to project root
        self.model_path = os.environ.get('ANOMALY_MODEL_PATH', 'anomaly_model.joblib')
        self.scaler_path = os.environ.get('ANOMALY_SCALER_PATH', 'anomaly_scaler.joblib')
        # --- END Anomaly Detection Attributes ---
        # Add storage for more preprocessors
        self.anomaly_imputer = None
        self.anomaly_onehot_encoder = None
        self.anomaly_feature_names = None # Store expected feature names
        self.imputer_path = os.environ.get('ANOMALY_IMPUTER_PATH', 'anomaly_imputer.joblib')
        self.ohe_path = os.environ.get('ANOMALY_OHE_PATH', 'anomaly_onehot_encoder.joblib')
        self.features_path = os.environ.get('ANOMALY_FEATURES_PATH', 'anomaly_features.joblib')


        # --- UPDATED: Load ML Models and Preprocessors ---
    def _load_ml_model(self):
        """Loads the anomaly detection model, scaler, imputer, encoder, and feature list."""
        if not self.scenario or not self.scenario.enable_anomalies:
            logging.info("Anomaly detection disabled. Skipping model/preprocessor load.")
            return

        # --- Load Model ---
        abs_model_path = os.path.abspath(self.model_path)
        logging.info(f"Attempting to load anomaly model from: {abs_model_path}")
        try:
            self.anomaly_model = joblib.load(abs_model_path)
            logging.info("Anomaly model loaded successfully.")
        except FileNotFoundError:
            logging.warning(f"Model file not found: '{abs_model_path}'. AD skipped."); return
        except Exception as e:
            logging.error(f"Error loading model '{abs_model_path}': {e}", exc_info=True); return

        # --- Load Scaler ---
        abs_scaler_path = os.path.abspath(self.scaler_path)
        logging.info(f"Attempting to load scaler from: {abs_scaler_path}")
        try:
            self.anomaly_scaler = joblib.load(abs_scaler_path)
            logging.info("Scaler loaded successfully.")
        except FileNotFoundError:
            logging.error(f"Scaler file not found: '{abs_scaler_path}'. AD cannot proceed."); self.anomaly_model=None; return
        except Exception as e:
            logging.error(f"Error loading scaler '{abs_scaler_path}': {e}", exc_info=True); self.anomaly_model=None; return

        # --- Load Imputer (Optional) ---
        abs_imputer_path = os.path.abspath(self.imputer_path)
        logging.info(f"Attempting to load imputer from: {abs_imputer_path}")
        try:
            self.anomaly_imputer = joblib.load(abs_imputer_path)
            logging.info("Imputer loaded successfully.")
        except FileNotFoundError:
            logging.info(f"Imputer file not found: '{abs_imputer_path}'. Assuming no imputation needed for prediction.")
            self.anomaly_imputer = None # Okay to proceed without imputer if training data had no NaNs
        except Exception as e:
            # Log error but maybe proceed? Depends if imputation is critical
            logging.error(f"Error loading imputer '{abs_imputer_path}': {e}", exc_info=True)
            self.anomaly_imputer = None

        # --- Load OneHotEncoder ---
        abs_ohe_path = os.path.abspath(self.ohe_path)
        logging.info(f"Attempting to load OneHotEncoder from: {abs_ohe_path}")
        try:
            self.anomaly_onehot_encoder = joblib.load(abs_ohe_path)
            logging.info("OneHotEncoder loaded successfully.")
        except FileNotFoundError:
            logging.error(f"OneHotEncoder file not found: '{abs_ohe_path}'. AD cannot proceed."); self.anomaly_model=None; return
        except Exception as e:
            logging.error(f"Error loading OneHotEncoder '{abs_ohe_path}': {e}", exc_info=True); self.anomaly_model=None; return

        # --- Load Feature Names ---
        abs_features_path = os.path.abspath(self.features_path)
        logging.info(f"Attempting to load feature list from: {abs_features_path}")
        try:
            self.anomaly_feature_names = joblib.load(abs_features_path)
            logging.info(f"Feature list loaded successfully: {self.anomaly_feature_names}")
        except FileNotFoundError:
            logging.error(f"Feature list file not found: '{abs_features_path}'. AD cannot reliably proceed."); self.anomaly_model=None; return
        except Exception as e:
            logging.error(f"Error loading feature list '{abs_features_path}': {e}", exc_info=True); self.anomaly_model=None; return


    def _setup(self):
        """Loads scenario, rules, creates log entry, initializes Playwright & ML Model."""
        logging.info(f"Setting up runner for Scenario ID: {self.scenario_id}")

        # 1. Load Scenario from DB
        self.scenario = db.session.get(Scenario, self.scenario_id)
        if not self.scenario: raise ValueError(f"Scenario ID {self.scenario_id} not found.")
        logging.info(f"Loaded Scenario: {self.scenario.name}")

        # 2. Load Processing Rules
        self.processing_rules = self.scenario.processing_rules.all()
        logging.info(f"Loaded {len(self.processing_rules)} processing rules.")

        # 3. Create initial ExecutionLog entry
        self.log_entry = ExecutionLog(
            scenario_id=self.scenario_id,
            start_time=datetime.utcnow(),
            status=ExecutionStatusEnum.RUNNING
        )
        db.session.add(self.log_entry)
        db.session.flush() # Get the log_id
        logging.info(f"Created Execution Log Entry ID: {self.log_entry.log_id}")

        # 4. Initialize Playwright
        logging.info(f"Launching Playwright (Headless: {self.headless})...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.page = self.browser.new_page()
        self.page.set_default_timeout(self.DEFAULT_TIMEOUT)
        logging.info("Playwright browser page initialized.")

        # 5. Load ML Model (after scenario loaded)
        self._load_ml_model()


    def _teardown(self, status: ExecutionStatusEnum, message: str | None = None):
        """Closes Playwright, updates log entry."""
        logging.info("Tearing down runner...")
        # 1. Close Playwright
        if self.browser and self.browser.is_connected():
            try: self.browser.close()
            except Exception as e: logging.error(f"Error closing browser: {e}")
            finally: logging.info("Playwright browser closed.") # Log even if error during close
        if self.playwright:
            try: self.playwright.stop()
            except Exception as e: logging.error(f"Error stopping playwright: {e}")
            finally: logging.info("Playwright context stopped.")

        # 2. Update ExecutionLog entry
        if self.log_entry:
            self.log_entry.end_time = datetime.utcnow()
            self.log_entry.status = status
            if message: self.log_entry.log_message = (self.log_entry.log_message + "\n---\n" + message if self.log_entry.log_message else message)
            try:
                db.session.commit() # Commit log changes
                logging.info(f"Execution Log ID {self.log_entry.log_id} updated. Final Status: {status.name}")
            except Exception as e:
                 logging.error(f"Failed to commit final Execution Log update for ID {self.log_entry.log_id}: {e}")
                 db.session.rollback()


    def _get_dynamic_value(self, value: str | None) -> str | None:
        """Replaces date markers like __TODAY__ or __YESTERDAY__."""
        if value == "__TODAY__": return datetime.now().strftime('%Y-%m-%d')
        elif value == "__YESTERDAY__": return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        return value


    def _execute_step(self, step: ScenarioStep):
        """Executes a single step from the scenario."""
        action = step.action_type
        selector = step.selector
        raw_value = step.value
        value = self._get_dynamic_value(raw_value)
        logging.info(f"Executing Step {step.sequence_order}: {action.name} - Selector: '{selector}' RawValue: '{raw_value}' -> Value: '{value}'")
        if not self.page: raise RuntimeError("Playwright page is not available.")

        try:
            if action == ActionTypeEnum.NAVIGATE:
                target_url = value or self.scenario.megara_url
                if not target_url: raise ValueError("Navigation target URL is missing.")
                self.page.goto(target_url, wait_until='networkidle')
                logging.info(f"  Navigated to {target_url}")
            elif action == ActionTypeEnum.CLICK:
                locator = self.page.locator(selector)
                locator.wait_for(state="visible", timeout=self.DEFAULT_TIMEOUT)
                locator.click()
                logging.info(f"  Clicked '{selector}'")
            elif action == ActionTypeEnum.TYPE:
                locator = self.page.locator(selector)
                locator.wait_for(state="visible", timeout=self.DEFAULT_TIMEOUT)
                locator.fill(value if value is not None else "")
                logging.info(f"  Typed into '{selector}'")
            elif action == ActionTypeEnum.SELECT:
                if value is None: raise ValueError(f"Missing value for SELECT on step {step.sequence_order}")
                locator = self.page.locator(selector)
                locator.wait_for(state="visible", timeout=self.DEFAULT_TIMEOUT)
                locator.select_option(value=value)
                logging.info(f"  Selected option with value '{value}' in '{selector}'")
            elif action == ActionTypeEnum.EXTRACT_ELEMENT:
                locator = self.page.locator(selector)
                locator.wait_for(state="attached", timeout=self.DEFAULT_TIMEOUT)
                text_content = locator.text_content()
                label = value if value else f"extracted_{step.step_id}"
                self.results[label] = text_content
                logging.info(f"  Extracted text from '{selector}' (Label: {label}): '{text_content[:100]}...'")
            elif action == ActionTypeEnum.EXTRACT_TABLE:
                label = value if value else f"table_{step.step_id}"
                logging.info(f"  Attempting table extraction for '{selector}' (Label: {label})...")
                table_locator = self.page.locator(selector)
                table_locator.wait_for(state="visible", timeout=self.DEFAULT_TIMEOUT)
                table_html = table_locator.evaluate("element => element.outerHTML")
                try:
                    dfs = pd.read_html(table_html, flavor='lxml')
                    if dfs:
                        extracted_df = dfs[0]
                        self.results[label] = extracted_df
                        logging.info(f"  Successfully extracted table '{label}' with {len(extracted_df)} rows and {len(extracted_df.columns)} columns.")
                    else:
                        logging.warning(f"  Pandas read_html found no tables for selector '{selector}'.")
                        self.results[label] = pd.DataFrame()
                except ImportError:
                    logging.error("Pandas/lxml not installed for table extraction.")
                    self.results[label] = pd.DataFrame() # Store empty
                except ValueError as ve: # Handle cases where read_html finds no table
                    logging.warning(f"  Pandas read_html failed for selector '{selector}': {ve}")
                    self.results[label] = pd.DataFrame()
            elif action == ActionTypeEnum.WAIT_FOR_SELECTOR:
                target_state, wait_timeout = 'visible', self.DEFAULT_TIMEOUT
                if value:
                    parts = value.split(':', 1)
                    target_state = parts[0].lower()
                    if len(parts) > 1:
                        try: wait_timeout = int(parts[1])
                        except ValueError: logging.warning(f"Invalid timeout value '{parts[1]}'. Using default.")
                valid_states = ['attached', 'detached', 'visible', 'hidden']
                if target_state not in valid_states: raise ValueError(f"Invalid state '{target_state}' for WAIT.")
                logging.info(f"  Waiting for selector '{selector}' to be '{target_state}' (Timeout: {wait_timeout}ms)...")
                self.page.locator(selector).wait_for(state=target_state, timeout=wait_timeout)
                logging.info(f"  Selector '{selector}' is now '{target_state}'.")
            elif action == ActionTypeEnum.WAIT_FOR_TIMEOUT:
                try: timeout_ms = int(value) if value else 1000
                except (ValueError, TypeError): raise ValueError(f"Invalid timeout value '{value}' for WAIT_TIMEOUT.")
                logging.info(f"  Waiting for fixed timeout of {timeout_ms} ms...")
                self.page.wait_for_timeout(timeout_ms)
                logging.info("  Wait complete.")
            else:
                logging.warning(f"  Action type '{action.name}' not implemented yet.")
        except PlaywrightTimeoutError as e:
            logging.error(f"Timeout error on step {step.sequence_order} ({action.name}): {e}")
            raise
        except Exception as e:
            logging.error(f"Error executing step {step.sequence_order} ({action.name}): {e}", exc_info=True)
            raise


    def _perform_login(self):
        """Performs login to the target application using credentials from env vars if configured."""
        login_url = os.environ.get('MEGARA_LOGIN_URL')
        username = os.environ.get('MEGARA_USERNAME')
        password = os.environ.get('MEGARA_PASSWORD')
        if not login_url or not username or not password:
            logging.info("Login credentials/URL not fully configured in environment variables. Skipping login.")
            return
        if not self.page: raise RuntimeError("Login attempted before page initialization.")

        logging.info(f"Attempting login to {login_url}...")
        try:
            self.page.goto(login_url, wait_until='networkidle')
            user_selector = os.environ.get('MEGARA_USER_SELECTOR', "#username")
            pass_selector = os.environ.get('MEGARA_PASS_SELECTOR', "#password")
            submit_selector = os.environ.get('MEGARA_SUBMIT_SELECTOR', "button[type='submit']")
            post_login_wait_selector = os.environ.get('MEGARA_POST_LOGIN_SELECTOR', None)

            self.page.locator(user_selector).wait_for(state="visible", timeout=self.DEFAULT_TIMEOUT)
            self.page.locator(user_selector).fill(username)
            logging.info("  Entered username.")
            self.page.locator(pass_selector).wait_for(state="visible", timeout=self.DEFAULT_TIMEOUT)
            self.page.locator(pass_selector).fill(password)
            logging.info("  Entered password.")
            self.page.locator(submit_selector).wait_for(state="visible", timeout=self.DEFAULT_TIMEOUT)
            self.page.locator(submit_selector).click()
            logging.info("  Clicked login button.")

            if post_login_wait_selector:
                 logging.info(f"  Waiting for post-login element: {post_login_wait_selector}")
                 self.page.locator(post_login_wait_selector).wait_for(state="visible", timeout=self.DEFAULT_TIMEOUT * 2)
            else:
                 logging.info("  Waiting for network idle after login click...")
                 self.page.wait_for_load_state('networkidle', timeout=self.DEFAULT_TIMEOUT * 2)
            logging.info("Login completed (based on wait condition). Further verification recommended.")
        except PlaywrightTimeoutError as e:
            logging.error(f"Timeout during login process: {e}")
            raise
        except Exception as e:
            logging.error(f"Error during login process: {e}")
            raise


    def _apply_anomaly_detection(self, df: pd.DataFrame, label: str) -> pd.DataFrame:
        """
        Applies the trained anomaly detection model and preprocessors to a DataFrame.

        Args:
            df (pd.DataFrame): The DataFrame containing extracted data (potentially
                               modified by processing rules).
            label (str): The label associated with this DataFrame (e.g., 'example_table_1').

        Returns:
            pd.DataFrame: The original DataFrame with an 'Is_Anomaly' boolean column added.
                          Returns the original DataFrame unmodified if detection is skipped.
        """
        # --- Default Column & Prerequisites Check ---
        # Ensure Is_Anomaly column exists, default to False. If detection runs, it will be overwritten.
        if 'Is_Anomaly' not in df.columns: df['Is_Anomaly'] = False

        # Check if anomaly detection should run
        if (not self.scenario or not self.scenario.enable_anomalies or # Scenario exists and enabled?
                not self.anomaly_model or not self.anomaly_scaler or    # Model and scaler loaded?
                not self.anomaly_onehot_encoder or not self.anomaly_feature_names or # OHE and feature list loaded?
                df.empty):                                               # DataFrame has data?

            # Log reason only if detection was expected but prerequisites failed
            if self.scenario and self.scenario.enable_anomalies and (not self.anomaly_model or not self.anomaly_scaler or not self.anomaly_onehot_encoder or not self.anomaly_feature_names):
                 logging.warning(f"Skipping anomaly detection for '{label}': prerequisites (model/scaler/encoder/features) not met. Check loading process.")
            elif self.scenario and self.scenario.enable_anomalies and df.empty:
                 logging.warning(f"Skipping anomaly detection for '{label}': DataFrame is empty.")
            # Otherwise, detection is simply disabled or df empty, no warning needed

            return df # Return original df with default Is_Anomaly=False

        logging.info(f"Applying anomaly detection for DataFrame '{label}' using trained model...")
        df_processed = df.copy() # Work on a copy to avoid modifying original results dict directly

        # --- 1. Feature Engineering (Replicate training steps on NEW data) ---
        #    Ensure the necessary base columns exist and create the engineered features
        #    the model was trained on. This section MUST align with train_anomaly_model.py

        base_numeric_features = ['Extracted_Count'] # Names MUST match those used in training script
        base_categorical_features = ['Is_Pending_Today', 'Is_Error_Legend'] # Names MUST match training
        base_ohe_feature = 'Periodicity' # Name MUST match training

        # a) Extract Count
        if FEATURE_EXTRACTED_COUNT not in df_processed.columns:
            if REMARKS_COL in df_processed.columns:
                 df_processed[FEATURE_EXTRACTED_COUNT] = df_processed[REMARKS_COL].apply(parse_count_from_remarks)
                 logging.debug(f"  Engineered '{FEATURE_EXTRACTED_COUNT}' for prediction.")
            else: logging.error(f"AD Skip: Cannot engineer '{FEATURE_EXTRACTED_COUNT}', missing base '{REMARKS_COL}'."); return df

        # b) Is Pending Today
        if FEATURE_IS_PENDING not in df_processed.columns:
            if STATUS_TODAY_COL in df_processed.columns:
                 df_processed[STATUS_TODAY_COL] = df_processed[STATUS_TODAY_COL].astype(str).str.upper().str.strip()
                 df_processed[FEATURE_IS_PENDING] = df_processed[STATUS_TODAY_COL].apply(lambda x: 1 if x == 'PDTE' else 0)
                 logging.debug(f"  Engineered '{FEATURE_IS_PENDING}' for prediction.")
            else: logging.error(f"AD Skip: Cannot engineer '{FEATURE_IS_PENDING}', missing base '{STATUS_TODAY_COL}'."); return df

        # c) Is Error Legend
        if FEATURE_IS_ERROR_LEGEND not in df_processed.columns:
            if STATUS_LEGEND_COL in df_processed.columns:
                df_processed[STATUS_LEGEND_COL] = df_processed[STATUS_LEGEND_COL].astype(str).str.upper().str.strip()
                df_processed[FEATURE_IS_ERROR_LEGEND] = df_processed[STATUS_LEGEND_COL].apply(lambda x: 1 if x in ['KO', 'KR'] else 0)
                logging.debug(f"  Engineered '{FEATURE_IS_ERROR_LEGEND}' for prediction.")
            else: logging.error(f"AD Skip: Cannot engineer '{FEATURE_IS_ERROR_LEGEND}', missing base '{STATUS_LEGEND_COL}'."); return df

        # d) Periodicity - Ensure column exists and has consistent format for OHE
        if PERIODICITY_COL not in df_processed.columns:
            logging.error(f"AD Skip: Required base column '{PERIODICITY_COL}' for OHE missing."); return df
        df_processed[PERIODICITY_COL] = df_processed[PERIODICITY_COL].astype(str).fillna('Unknown').str.strip().str.capitalize()

        # --- 2. Preprocessing (Using loaded objects) ---
        logging.debug("  Applying preprocessing steps using loaded objects...")

        # a) Impute Missing Numeric Values (Use loaded imputer ONLY if it exists)
        numeric_cols_to_process = [col for col in base_numeric_features if col in df_processed.columns]
        if not numeric_cols_to_process:
             logging.warning(f"No numeric features ({base_numeric_features}) found in DataFrame '{label}' for imputation/scaling.")
             # Continue if no numeric features expected, error if they were? Depends on model.
        elif self.anomaly_imputer:
            try:
                # Only transform columns that were part of the imputer's fitting process
                # We assume the imputer was fitted ONLY on base_numeric_features during training
                df_processed[numeric_cols_to_process] = self.anomaly_imputer.transform(df_processed[numeric_cols_to_process])
                logging.debug(f"  Applied loaded imputer to: {numeric_cols_to_process}")
            except Exception as e:
                 logging.error(f"Error applying loaded imputer: {e}", exc_info=True); return df # Stop if imputation fails
        elif df_processed[numeric_cols_to_process].isnull().values.any():
             # Handle case where NaNs exist now but didn't during training (no imputer saved)
             logging.warning(f"Missing values found in {numeric_cols_to_process} but no imputer loaded. Filling with 0 for prediction.")
             df_processed[numeric_cols_to_process] = df_processed[numeric_cols_to_process].fillna(0)

        # b) One-Hot Encode Periodicity (Use loaded encoder)
        try:
            periodicity_encoded = self.anomaly_onehot_encoder.transform(df_processed[[base_ohe_feature]])
            # Get feature names FROM THE LOADED ENCODER
            ohe_feature_names = self.anomaly_onehot_encoder.get_feature_names_out([base_ohe_feature])
            periodicity_encoded_df = pd.DataFrame(periodicity_encoded, columns=ohe_feature_names, index=df_processed.index)
            # Drop original categorical column, add encoded ones
            df_processed = pd.concat([df_processed.drop(columns=[base_ohe_feature]), periodicity_encoded_df], axis=1)
            logging.debug(f"  Applied loaded OneHotEncoder for '{base_ohe_feature}'.")
        except Exception as e:
            logging.error(f"Error applying loaded OneHotEncoder: {e}", exc_info=True); return df # Stop if OHE fails

        # c) Prepare Final Feature DataFrame for Scaling/Prediction
        #    Ensure all columns the model expects exist and are in the correct order.
        df_model_input = pd.DataFrame(index=df_processed.index) # Start with matching index
        missing_in_current_data = []
        for feature_name in self.anomaly_feature_names: # Iterate through LOADED feature list
             if feature_name in df_processed.columns:
                  df_model_input[feature_name] = df_processed[feature_name]
             else:
                  # This happens if a category seen during training isn't in the current batch
                  # OHE creates columns like Periodicity_Daily, Periodicity_Monthly etc.
                  # If current data only has Daily, Periodicity_Monthly will be missing.
                  missing_in_current_data.append(feature_name)
                  df_model_input[feature_name] = 0 # Add missing one-hot columns as 0
        if missing_in_current_data:
             logging.warning(f"  Features missing after preprocessing that were in training: {missing_in_current_data}. Added as 0.")

        # Ensure order is correct (it should be if we built it from anomaly_feature_names)
        df_model_input = df_model_input[self.anomaly_feature_names]

        # d) Scale Features (Use loaded scaler on the correctly ordered feature set)
        try:
            # Scaler expects data in the exact same order and shape as during fitting
            scaled_features = self.anomaly_scaler.transform(df_model_input)
            # For clarity, create a new DataFrame with scaled data and correct columns/index
            df_scaled = pd.DataFrame(scaled_features, columns=self.anomaly_feature_names, index=df_model_input.index)
            logging.debug("  Applied loaded scaler to the final feature set.")
        except Exception as e:
            logging.error(f"Error applying loaded scaler: {e}", exc_info=True); return df # Stop if scaling fails

        # --- 3. Prediction ---
        logging.info(f"Predicting anomalies using loaded model for {len(df_scaled)} rows...")
        try:
            # Predict using the scaled data prepared exactly as during training
            predictions = self.anomaly_model.predict(df_scaled) # Returns 1 (inlier) or -1 (outlier)

            # Assign predictions back to the ORIGINAL input DataFrame 'df'
            # using the index to ensure correct alignment.
            df['Is_Anomaly'] = (predictions == -1) # True if outlier (-1)

            num_anomalies = df['Is_Anomaly'].sum()
            logging.info(f"Anomaly detection applied. Found {num_anomalies} potential anomalies in '{label}'.")
        except Exception as e:
            logging.error(f"Error during anomaly prediction for '{label}': {e}", exc_info=True)
            # Keep default Is_Anomaly=False in df if prediction fails

        return df # Return the original DataFrame with 'Is_Anomaly' column updated


    def _apply_processing_rules(self):
        """Applies defined processing rules and then anomaly detection to DataFrame results."""
        if not self.processing_rules and not (self.scenario and self.scenario.enable_anomalies and self.anomaly_model):
            logging.info("No processing rules or enabled/loaded anomaly detection. Skipping processing.")
            return
        logging.info("Applying processing rules and anomaly detection (if enabled)...")

        for label, data in list(self.results.items()):
            if isinstance(data, pd.DataFrame):
                df = data.copy() # Work on a copy to avoid modifying original dict item directly during iteration

                # --- Apply Rules ---
                if self.processing_rules:
                    logging.info(f"Applying rules for extracted DataFrame '{label}'...")
                    # Check for needed columns and add if missing (avoids errors)
                    rule_columns = set(rule.condition_column for rule in self.processing_rules) | \
                                   set(rule.action_column for rule in self.processing_rules)
                    missing_cols = [col for col in rule_columns if col not in df.columns]
                    if missing_cols:
                        logging.warning(f"  DataFrame '{label}' is missing columns required by rules: {missing_cols}. Adding them as empty.")
                        for col in missing_cols: df[col] = None

                    # Apply rules
                    for i, rule in enumerate(self.processing_rules):
                        # ... (Rule application logic as defined previously) ...
                        try:
                            condition = None
                            col_series = df[rule.condition_column]
                            col_str = col_series.astype(str).fillna('')
                            val = str(rule.condition_value) if rule.condition_value is not None else ""
                            op = rule.operator
                            if op == RuleOperatorEnum.EQUALS: condition = (col_str == val)
                            elif op == RuleOperatorEnum.NOT_EQUALS: condition = (col_str != val)
                            elif op == RuleOperatorEnum.CONTAINS: condition = col_str.str.contains(val, case=False, na=False)
                            elif op == RuleOperatorEnum.IS_BLANK: condition = col_str == ''
                            elif op == RuleOperatorEnum.IS_NOT_BLANK: condition = col_str != ''
                            # Add numeric comparisons later if needed
                            else: logging.warning(f"Rule operator '{op.name}' not handled."); continue
                            if condition is not None:
                                if rule.action_column not in df.columns: df[rule.action_column] = None
                                df.loc[condition, rule.action_column] = rule.action_value
                        except Exception as e: logging.error(f"Error applying rule {rule.rule_id} to '{label}': {e}", exc_info=True)
                    logging.info(f"Finished applying rules for '{label}'.")

                # --- Apply Anomaly Detection (After Rules) ---
                df = self._apply_anomaly_detection(df, label)

                # Update the results dictionary with the fully processed DataFrame
                self.results[label] = df

    def _save_monitoring_results(self):
        """Saves processed data points (including anomaly flags) to the MonitoringResult table."""
        if not self.log_entry: logging.error("Cannot save results: Log entry missing."); return
        if not self.results: logging.info("No results extracted to save."); return

        logging.info(f"Saving monitoring results for Log ID: {self.log_entry.log_id}...")
        results_to_add = []
        current_time = datetime.utcnow()

        for label, data in self.results.items():
            if isinstance(data, pd.DataFrame):
                logging.debug(f"Formatting DataFrame '{label}' for saving...")
                # Example: Save specific columns + anomaly flag per row
                target_cols = data.columns[:5].tolist() # Adjust which columns to save
                anomaly_col_present = 'Is_Anomaly' in data.columns
                if anomaly_col_present and 'Is_Anomaly' not in target_cols: target_cols.append('Is_Anomaly')

                for index, row in data.iterrows():
                    is_anomaly_flag = bool(row['Is_Anomaly']) if anomaly_col_present else False
                    for col_name in target_cols:
                        if col_name == 'Is_Anomaly': continue # Skip saving the flag itself as a metric
                        if col_name in row:
                           results_to_add.append(MonitoringResult(
                               log_id=self.log_entry.log_id,
                               metric_name=f"{label}_{index}_{col_name}",
                               metric_value=str(row[col_name]),
                               is_anomaly=is_anomaly_flag, # Save flag associated with this row
                               recorded_at=current_time ))
            elif isinstance(data, (str, int, float, bool)):
                 results_to_add.append(MonitoringResult(
                     log_id=self.log_entry.log_id, metric_name=label, metric_value=str(data),
                     is_anomaly=False, recorded_at=current_time ))
            else: logging.warning(f"Result type '{type(data)}' for '{label}' not saved.")

        if results_to_add:
            try:
                db.session.bulk_save_objects(results_to_add)
                db.session.commit()
                logging.info(f"Successfully saved {len(results_to_add)} monitoring results.")
            except Exception as e:
                 db.session.rollback()
                 logging.error(f"Error bulk saving monitoring results: {e}", exc_info=True)
        else: logging.info("No results formatted for saving.")


    def _generate_report(self):
        """Generates the Excel report using a template and column mappings."""
        if not self.log_entry: logging.error("Cannot generate report: Log entry missing."); return
        if not self.scenario or not self.scenario.template: logging.info("No template configured."); return

        template_path = self.scenario.template.file_path
        logging.info(f"Attempting to use template path from DB: {template_path}")
        if not os.path.exists(template_path):
            logging.error(f"Template file not found: {template_path}")
            self.log_entry.log_message = (self.log_entry.log_message or "") + f"\nERROR: Template not found {template_path}"
            return

        mappings_query = self.scenario.column_mappings.all()
        column_map = {mapping.scraped_header: mapping.template_header for mapping in mappings_query}
        if not column_map: logging.warning("No column mappings defined.")

        report_df, report_label = None, None
        for label, data in self.results.items():
            if isinstance(data, pd.DataFrame): report_df, report_label = data, label; break
        if report_df is None or report_df.empty: logging.warning("No DataFrame found/empty. Skipping report."); return

        logging.info(f"Generating report using data '{report_label}' and template: {template_path}")
        try:
            workbook = openpyxl.load_workbook(template_path)
            sheet = workbook.active
            logging.info(f"Using sheet: '{sheet.title}'")

            # Prepare data based on mappings, including anomaly column if it exists
            template_headers_ordered = list(column_map.values())
            mapped_data = pd.DataFrame()
            for scraped_col, template_col in column_map.items():
                if scraped_col in report_df.columns: mapped_data[template_col] = report_df[scraped_col]
                else: logging.warning(f"Mapped column '{scraped_col}' not in data '{report_label}'."); mapped_data[template_col] = None
            # Add anomaly column if it exists in source and has a mapping
            if 'Is_Anomaly' in report_df.columns and 'Is_Anomaly' in column_map:
                 mapped_data[column_map['Is_Anomaly']] = report_df['Is_Anomaly']

            # Reorder columns if possible
            final_template_cols = [h for h in template_headers_ordered if h in mapped_data.columns]
            mapped_data = mapped_data[final_template_cols]

            # Write data
            start_row = sheet.max_row + 1 if sheet.max_row > 1 else 2
            logging.info(f"Writing data starting from row {start_row}")
            for r_idx, row in enumerate(dataframe_to_rows(mapped_data, index=False, header=False), start=start_row):
                for c_idx, value in enumerate(row, start=1): sheet.cell(row=r_idx, column=c_idx, value=value)

            # Save file
            output_dir = Path(os.environ.get('REPORT_OUTPUT_DIR', './generated_reports'))
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_scenario_name = "".join(c if c.isalnum() else "_" for c in self.scenario.name)
            output_filename = f"Scenario_{self.scenario_id}_{safe_scenario_name}_{timestamp}.xlsx"
            output_path = output_dir / output_filename
            output_path_str = str(output_path.resolve())
            workbook.save(output_path)
            logging.info(f"Report saved successfully to: {output_path_str}")
            self.log_entry.report_file_path = output_path_str # Update log entry field
        except Exception as e:
            logging.error(f"Error generating report: {e}", exc_info=True)
            self.log_entry.log_message = (self.log_entry.log_message or "") + f"\nERROR: Report generation failed: {e}"

    def _deliver_report(self):
        """Sends the generated report via email if configured."""
        # 1. Check if report exists and log entry is available
        if not self.log_entry or not self.log_entry.report_file_path:
            logging.info("No report file generated or log entry missing. Skipping email delivery.")
            return

        # 2. Check if email recipients are configured for the scenario
        if not self.scenario or not self.scenario.email_recipients:
            logging.info("No email recipients configured for this scenario. Skipping email delivery.")
            return

        # 3. Parse recipients string (comma-separated) into a list
        try:
            recipients = [email.strip() for email in self.scenario.email_recipients.split(',') if email.strip()]
            if not recipients:
                logging.warning("Recipient list parsed is empty. Skipping email delivery.")
                return
        except Exception as e:
            logging.error(f"Error parsing recipient list '{self.scenario.email_recipients}': {e}")
            return

        # 4. Verify the report file actually exists
        report_path = self.log_entry.report_file_path
        if not os.path.exists(report_path):
             logging.error(f"Cannot email report: File not found at {report_path}")
             self.log_entry.log_message = (self.log_entry.log_message or "") + f"\nERROR: Report file {report_path} not found for emailing."
             return

        logging.info(f"Attempting to email report '{os.path.basename(report_path)}' to: {recipients}")

        try:
            # 5. Construct the email message object
            subject = f"Monitoring Report: {self.scenario.name} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            # Get sender from the stored app instance's config
            sender = self.app.config.get('MAIL_DEFAULT_SENDER', self.app.config.get('MAIL_USERNAME'))
            if not sender:
                 logging.error("MAIL_DEFAULT_SENDER or MAIL_USERNAME not configured in Flask app. Cannot send email.")
                 self.log_entry.log_message = (self.log_entry.log_message or "") + "\nERROR: Mail sender not configured."
                 return

            msg = Message(subject=subject,
                          sender=sender,
                          recipients=recipients)

            # Construct email body
            msg.body = f"Automated monitoring report for scenario '{self.scenario.name}' attached.\n\n"
            msg.body += f"Execution completed at: {self.log_entry.end_time.strftime('%Y-%m-%d %H:%M:%S UTC') if self.log_entry.end_time else 'N/A'}\n"
            msg.body += f"Status: {self.log_entry.status.name}\n"
            # Include any previous log messages (like errors or warnings)
            if self.log_entry.log_message and "Report emailed successfully" not in self.log_entry.log_message and "ERROR: Failed to send report email" not in self.log_entry.log_message :
                 msg.body += f"\nNotes/Errors during execution:\n{self.log_entry.log_message}\n"

            # 6. Attach the report file
            with open(report_path, 'rb') as fp:
                msg.attach(
                    filename=os.path.basename(report_path),
                    # Correct MIME type for .xlsx files
                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    data=fp.read()
                )

            # 7. Send the email using the mail instance from the stored app instance
            mail_instance = self.app.extensions.get('mail')
            if mail_instance:
                 # Ensure app context is active for sending email
                 with self.app.app_context():
                      mail_instance.send(msg)
                 logging.info(f"Report email sent successfully to {recipients}.")
                 # Update log message - Append success
                 self.log_entry.log_message = (self.log_entry.log_message or "") + "\nINFO: Report emailed successfully."
            else:
                 # This indicates a setup problem if Flask-Mail wasn't initialized correctly
                 logging.error("Flask-Mail extension not found in provided app instance. Mail not sent.")
                 self.log_entry.log_message = (self.log_entry.log_message or "") + "\nERROR: Flask-Mail extension not found in app."
                 # Maybe raise error if this happens?

        except Exception as e:
            # Catch any exception during mail sending (e.g., auth error, connection error)
            logging.error(f"Failed to send report email: {e}", exc_info=True)
            # Update log message with the specific email error
            self.log_entry.log_message = (self.log_entry.log_message or "") + f"\nERROR: Failed to send report email: {e}"
            # Note: We don't re-raise the exception here typically,
            # as failure to email shouldn't necessarily fail the whole monitoring run.


    


    def run(self):
        """Executes the full scenario."""
        final_status = ExecutionStatusEnum.FAILED
        error_message = None
        try:
            self._setup()
            if not self.page: raise RuntimeError("Playwright page not initialized correctly.")
            # self._perform_login() # Call login method if needed for the target app

            steps = self.scenario.steps.order_by(ScenarioStep.sequence_order).all()
            if not steps:
                logging.warning(f"Scenario {self.scenario_id} has no steps defined.")
                final_status, error_message = ExecutionStatusEnum.SUCCESS, "Scenario completed (No steps)."
            else:
                 for step in steps: self._execute_step(step)
                 self._apply_processing_rules() # Applies rules & anomaly detection structure
                 self._save_monitoring_results() # Saves results including anomaly flags
                 self._generate_report() # Generates report possibly including anomaly flags

                 self._deliver_report()

                 logging.info("Final processed results dictionary (after AD):")
                 for label, result_data in self.results.items():
                      if isinstance(result_data, pd.DataFrame): logging.info(f"  Result '{label}' (DataFrame): {len(result_data)} rows x {len(result_data.columns)} columns")
                      else: logging.info(f"  Result '{label}': {str(result_data)[:200]}...")

                 

                 logging.info(f"Scenario ID {self.scenario_id} execution finished.")
                 final_status, error_message = ExecutionStatusEnum.SUCCESS, "Scenario executed successfully."

        except PlaywrightTimeoutError as e: error_message = f"Timeout Error: {e}"; logging.error(error_message, exc_info=False)
        except Exception as e: error_message = f"Error: {e}"; logging.error(error_message, exc_info=True)
        finally:
            if final_status == ExecutionStatusEnum.FAILED and self.page and self.browser and self.browser.is_connected():
                 try:
                    screenshot_path = f"error_screenshot_scenario_{self.scenario_id}_log_{self.log_entry.log_id if self.log_entry else 'unknown'}.png"
                    self.page.screenshot(path=screenshot_path, full_page=True)
                    logging.info(f"Error screenshot saved to {screenshot_path}")
                    error_message = (error_message or "") + f" (Screenshot: {screenshot_path})"
                 except Exception as se: logging.error(f"Failed to take error screenshot: {se}")
            self._teardown(final_status, error_message)
        return final_status == ExecutionStatusEnum.SUCCESS