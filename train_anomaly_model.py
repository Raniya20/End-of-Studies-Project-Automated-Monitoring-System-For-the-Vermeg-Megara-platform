# train_anomaly_model.py (Revised to use cleaned CSV)
import os
import pandas as pd
import numpy as np
import re
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler, OneHotEncoder # Use OneHotEncoder
from sklearn.impute import SimpleImputer
import joblib
import logging
from pathlib import Path

# --- Configuration ---
# <<< Input file is now the cleaned CSV >>>
CLEANED_INPUT_FILE = Path('./cleaned_monitoring_data.csv')

# --- Standardized Column Names (MUST match CSV headers and feature engineering logic) ---
PROCESS_COL = 'Process'
PERIODICITY_COL = 'Periodicity'
STATUS_TODAY_COL = 'Status_Today'
STATUS_LEGEND_COL = 'Status_Legend'
REMARKS_COL = 'Remarks'
# Add others if they exist in your CSV and are needed
# STATUS_YESTERDAY_COL = 'Status_Yesterday'
# TIME_EXPECTED_COL = 'Time_Expected'
# TIME_ACTUAL_COL = 'Time_Actual'

# --- Engineered Feature Names ---
FEATURE_EXTRACTED_COUNT = 'Extracted_Count'
FEATURE_IS_PENDING = 'Is_Pending_Today'
FEATURE_IS_ERROR_LEGEND = 'Is_Error_Legend'
# Add more if you engineered them in the preprocessing script or will here

# --- Define Features to Use for Training ---
# <<< CRITICAL: Define features based on engineered columns >>>
NUMERIC_MODEL_FEATURES = [FEATURE_EXTRACTED_COUNT] # Current numeric feature
CATEGORICAL_MODEL_FEATURES = [FEATURE_IS_PENDING, FEATURE_IS_ERROR_LEGEND] # Current binary/categorical features
# Periodicity will be added after one-hot encoding

# --- Output Paths ---
MODEL_OUTPUT_PATH = 'anomaly_model.joblib'
SCALER_OUTPUT_PATH = 'anomaly_scaler.joblib'
IMPUTER_OUTPUT_PATH = 'anomaly_imputer.joblib'
OHE_ENCODER_OUTPUT_PATH = 'anomaly_onehot_encoder.joblib'

# --- Model Parameters ---
ISOLATION_FOREST_CONTAMINATION = 'auto'
ISOLATION_FOREST_N_ESTIMATORS = 100
ISOLATION_FOREST_RANDOM_STATE = 42

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - TRAINER - %(levelname)s - %(message)s')

# --- Helper Function (Keep if needed) ---
def parse_count_from_remarks(remark):
    if not isinstance(remark, str): return np.nan
    match = re.search(r'\d{1,3}(?:[,\s]\d{3})*|\d+', remark)
    if match:
        try: return int(match.group(0).replace(',', '').replace(' ', ''))
        except (ValueError, TypeError): return np.nan
    return np.nan

# --- Main Training Logic ---
def train_model():
    logging.info(f"--- Starting Anomaly Model Training from Cleaned Data ---")
    logging.info(f"Input file: {CLEANED_INPUT_FILE.resolve()}")

    # --- 1. Load Cleaned Data ---
    if not CLEANED_INPUT_FILE.exists():
        logging.error(f"Cleaned data file not found: {CLEANED_INPUT_FILE}. Please run preprocess_reports.py first. Stopping.")
        return
    try:
        data_for_eng = pd.read_csv(CLEANED_INPUT_FILE)
        logging.info(f"Loaded cleaned data: {data_for_eng.shape[0]} rows, {data_for_eng.shape[1]} columns.")
    except Exception as e:
        logging.error(f"Error reading cleaned data file {CLEANED_INPUT_FILE}: {e}", exc_info=True)
        return

    # --- 2. Feature Engineering (from cleaned columns) ---
    #    (This assumes engineering wasn't already done in preprocess script)
    #    (If done already, just select the final feature columns)
    logging.info("Starting feature engineering...")

    # a) Extract Count from Remarks (if not already done)
    if FEATURE_EXTRACTED_COUNT not in data_for_eng.columns: # Check if already exists
        if REMARKS_COL in data_for_eng.columns:
             data_for_eng[FEATURE_EXTRACTED_COUNT] = data_for_eng[REMARKS_COL].apply(parse_count_from_remarks)
             logging.info(f"Engineered '{FEATURE_EXTRACTED_COUNT}'. NaN count: {data_for_eng[FEATURE_EXTRACTED_COUNT].isnull().sum()}")
        else:
             logging.error(f"Cannot engineer '{FEATURE_EXTRACTED_COUNT}', missing base column '{REMARKS_COL}'. Stopping.")
             return

    # b) Is Pending Today Status (if not already done)
    if FEATURE_IS_PENDING not in data_for_eng.columns:
        if STATUS_TODAY_COL in data_for_eng.columns:
             # Ensure consistent casing/stripping even on cleaned data
             data_for_eng[STATUS_TODAY_COL] = data_for_eng[STATUS_TODAY_COL].astype(str).str.upper().str.strip()
             data_for_eng[FEATURE_IS_PENDING] = data_for_eng[STATUS_TODAY_COL].apply(lambda x: 1 if x == 'PDTE' else 0)
             logging.info(f"Engineered '{FEATURE_IS_PENDING}'. Count of pending: {data_for_eng[FEATURE_IS_PENDING].sum()}")
        else:
             logging.warning(f"Cannot engineer '{FEATURE_IS_PENDING}', missing base column '{STATUS_TODAY_COL}'. Model may be less effective.")
             # Create default if needed downstream, or handle missing feature
             data_for_eng[FEATURE_IS_PENDING] = 0 # Example default


    # c) Is Error Legend Status (if not already done)
    if FEATURE_IS_ERROR_LEGEND not in data_for_eng.columns:
        if STATUS_LEGEND_COL in data_for_eng.columns:
            data_for_eng[STATUS_LEGEND_COL] = data_for_eng[STATUS_LEGEND_COL].astype(str).str.upper().str.strip()
            data_for_eng[FEATURE_IS_ERROR_LEGEND] = data_for_eng[STATUS_LEGEND_COL].apply(lambda x: 1 if x in ['KO', 'KR'] else 0)
            logging.info(f"Engineered '{FEATURE_IS_ERROR_LEGEND}'. Count of errors: {data_for_eng[FEATURE_IS_ERROR_LEGEND].sum()}")
        else:
             logging.warning(f"Cannot engineer '{FEATURE_IS_ERROR_LEGEND}', missing base column '{STATUS_LEGEND_COL}'. Model may be less effective.")
             data_for_eng[FEATURE_IS_ERROR_LEGEND] = 0 # Example default

    # d) Periodicity - Ensure it exists and handle missing values
    if PERIODICITY_COL not in data_for_eng.columns:
         logging.error(f"Required column '{PERIODICITY_COL}' not found in cleaned data. Stopping.")
         return
    data_for_eng[PERIODICITY_COL] = data_for_eng[PERIODICITY_COL].astype(str).fillna('Unknown').str.strip().str.capitalize()


    # --- 3. Select Features for Model & Preprocessing ---
    # Combine engineered features + Periodicity
    all_feature_cols_before_ohe = [PERIODICITY_COL] + NUMERIC_MODEL_FEATURES + CATEGORICAL_MODEL_FEATURES
    missing_required = [col for col in all_feature_cols_before_ohe if col not in data_for_eng.columns]
    if missing_required:
         logging.error(f"One or more required feature columns are missing after engineering: {missing_required}. Stopping.")
         return

    features_to_process = data_for_eng[all_feature_cols_before_ohe].copy()
    logging.info(f"Selected data for preprocessing with columns: {list(features_to_process.columns)}")


    # --- 4. Preprocessing ---
    logging.info("Starting preprocessing...")

    # a) Impute Missing Numeric Values
    numeric_imputer = SimpleImputer(strategy='median')
    features_to_process[NUMERIC_MODEL_FEATURES] = numeric_imputer.fit_transform(features_to_process[NUMERIC_MODEL_FEATURES])
    logging.info(f"Applied Median Imputation to: {NUMERIC_MODEL_FEATURES}")
    joblib.dump(numeric_imputer, IMPUTER_OUTPUT_PATH)
    logging.info(f"Numeric Imputer saved to {IMPUTER_OUTPUT_PATH}")

    # b) One-Hot Encode Categorical Periodicity
    ohe_encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False)
    periodicity_encoded = ohe_encoder.fit_transform(features_to_process[[PERIODICITY_COL]])
    periodicity_encoded_df = pd.DataFrame(periodicity_encoded, columns=ohe_encoder.get_feature_names_out([PERIODICITY_COL]), index=features_to_process.index)
    logging.info(f"One-Hot Encoded '{PERIODICITY_COL}' into columns: {list(periodicity_encoded_df.columns)}.")
    joblib.dump(ohe_encoder, OHE_ENCODER_OUTPUT_PATH)
    logging.info(f"OneHotEncoder saved to {OHE_ENCODER_OUTPUT_PATH}")

    # c) Combine Processed Features
    processed_features = features_to_process.drop(columns=[PERIODICITY_COL])
    processed_features = pd.concat([processed_features, periodicity_encoded_df], axis=1)

    # d) Scale ALL numeric features (original numeric + OHE results + binary statuses)
    # Ensure all columns intended for scaling actually exist
    cols_to_scale = [col for col in NUMERIC_MODEL_FEATURES + CATEGORICAL_MODEL_FEATURES + list(periodicity_encoded_df.columns) if col in processed_features.columns]
    logging.info(f"Applying StandardScaler to columns: {cols_to_scale}")
    if not cols_to_scale:
        logging.error("No columns identified for scaling. Stopping.")
        return
    scaler = StandardScaler()
    processed_features[cols_to_scale] = scaler.fit_transform(processed_features[cols_to_scale])
    joblib.dump(scaler, SCALER_OUTPUT_PATH)
    logging.info(f"Scaler saved to {SCALER_OUTPUT_PATH}.")


    # --- 5. Train Model ---
    logging.info("Training Isolation Forest model...")
    final_feature_names = list(processed_features.columns) # Get final list of features model is trained on
    logging.info(f"Final features used for training: {final_feature_names}")
    if processed_features.isnull().values.any():
         logging.error("NaN values detected before training. Check imputation. Stopping.")
         print(processed_features.isnull().sum()) # Print NaN counts per column
         return

    model = IsolationForest(
        n_estimators=ISOLATION_FOREST_N_ESTIMATORS,
        contamination=ISOLATION_FOREST_CONTAMINATION,
        random_state=ISOLATION_FOREST_RANDOM_STATE,
        n_jobs=-1
    )
    try:
        model.fit(processed_features)
        logging.info("Isolation Forest training complete.")
        joblib.dump(model, MODEL_OUTPUT_PATH)
        logging.info(f"Trained model saved to {MODEL_OUTPUT_PATH}.")
        # --- Optional: Save feature list used for training ---
        joblib.dump(final_feature_names, 'anomaly_features.joblib')
        logging.info(f"Feature list saved to anomaly_features.joblib")

    except Exception as e:
        logging.error(f"Error during model fitting: {e}", exc_info=True); return

    logging.info("--- Training Process Finished Successfully ---")


if __name__ == "__main__":
    # Create output directory if needed (relative to script)
    # Path(MODEL_OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    train_model()