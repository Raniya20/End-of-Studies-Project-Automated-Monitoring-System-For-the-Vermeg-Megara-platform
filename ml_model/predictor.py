# ml_model/predictor.py

import joblib
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta # If you need to recreate features like CommitmentHour

# --- Configuration ---
# Determine the base directory of the project or where the model files are stored
# This assumes your 'ml_model' directory is at the same level as your main Flask 'app.py'
# or that you are running Flask from the 'your_flask_project' root.
# Adjust pathing if your structure is different.
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # Gets the directory of predictor.py
MODEL_DIR = BASE_DIR # Or specify another path if models are elsewhere

PIPELINE_PATH = os.path.join(MODEL_DIR, 'final_anomaly_pipeline.joblib')
FEATURE_NAMES_PATH = os.path.join(MODEL_DIR, 'feature_names_for_prediction.json')
# feature_config.json might not be strictly needed here if the pipeline handles it,
# but good to have if you need to reconstruct feature lists.

# --- Load Model and Feature Names Once When Module is Imported ---
try:
    pipeline = joblib.load(PIPELINE_PATH)
    with open(FEATURE_NAMES_PATH, 'r') as f:
        EXPECTED_FEATURE_NAMES = json.load(f)
    print("ML Pipeline and feature names loaded successfully.")
except FileNotFoundError:
    pipeline = None
    EXPECTED_FEATURE_NAMES = []
    print(f"ERROR: Model or feature names file not found. Searched in: {MODEL_DIR}")
    print("Please ensure 'final_anomaly_pipeline.joblib' and 'feature_names_for_prediction.json' are in the ml_model directory.")
except Exception as e:
    pipeline = None
    EXPECTED_FEATURE_NAMES = []
    print(f"ERROR loading ML model or feature names: {e}")


# --- Helper function to parse time (if needed for new data preparation) ---
def parse_time_to_timedelta_duration_predictor(time_str):
    if pd.isna(time_str) or str(time_str).strip() == '':
        return None
    time_str = str(time_str).strip()
    for fmt in ('%I:%M:%S %p', '%H:%M:%S', '%H:%M'):
        try:
            dt_obj = datetime.strptime(time_str, fmt)
            return timedelta(hours=dt_obj.hour, minutes=dt_obj.minute, seconds=dt_obj.second)
        except ValueError:
            continue
    return None

def get_hour_predictor(td_object):
    if pd.isna(td_object):
        return -1
    return td_object.seconds // 3600

# --- Prediction Function ---
def predict_anomaly(input_data_dict_list):
    """
    Predicts anomalies for a list of input data instances.

    Args:
        input_data_dict_list (list of dict): A list where each dictionary
                                             represents a process instance and
                                             contains feature values.
                                             Example:
                                             [
                                                 {
                                                     'SubAxis': 'Prices',
                                                     'ProcessName': 'Recepción de ficheros de AC_RF',
                                                     'Periodicity': 'Daily',
                                                     'Status_D_minus_1': 'OK',
                                                     'ObservedDurationMetric': 1420.0,
                                                     'CommitmentHour': 18,
                                                     'DayOfWeek': 3
                                                 },
                                                 # ... more instances
                                             ]

    Returns:
        list: A list of predictions (0 for anomaly, 1 for not anomaly).
        list: A list of anomaly probabilities (probability of class 1 - Not Anomaly).
              Returns None for probabilities if the model doesn't support predict_proba.
    """
    if pipeline is None:
        print("ERROR: Model pipeline is not loaded. Cannot make predictions.")
        # Return a default non-anomalous prediction or raise an error
        return [1] * len(input_data_dict_list), [0.0] * len(input_data_dict_list)


    # Convert input data (list of dicts) to DataFrame in the correct order of features
    try:
        # Create DataFrame using the expected feature order
        input_df = pd.DataFrame(input_data_dict_list, columns=EXPECTED_FEATURE_NAMES)
        
        # --- Data Type Conversion and Pre-checks (mirror what was done for X_train) ---
        # Example: Ensure categorical features are strings, numerical are numeric
        # This part highly depends on what your `preprocessor` expects.
        # If your `X_train` had specific dtypes, try to match them.
        # For simplicity, we assume the preprocessor handles most of this.
        # However, explicit conversion might be needed for robustness.

        # Ensure all expected columns are present, fill missing with a placeholder if appropriate
        # (though ideally the input_data_dict should always contain all required keys)
        for col in EXPECTED_FEATURE_NAMES:
            if col not in input_df.columns:
                # Handle missing columns: fill with NaN or a default.
                # This depends on how your preprocessor handles NaNs.
                # For OHE, NaNs might become a separate category if not handled.
                # For StandardScaler, NaNs will cause errors if not imputed.
                print(f"Warning: Feature '{col}' missing in input_data. Filling with NaN.")
                input_df[col] = np.nan


    except Exception as e:
        print(f"Error preparing input DataFrame for prediction: {e}")
        return [1] * len(input_data_dict_list), [0.0] * len(input_data_dict_list)


    # Make predictions
    try:
        predictions = pipeline.predict(input_df)
    except Exception as e:
        print(f"Error during model prediction: {e}")
        return [1] * len(input_data_dict_list), [0.0] * len(input_data_dict_list)

    # Get probabilities (if available)
    probabilities = None
    if hasattr(pipeline, "predict_proba"):
        try:
            # Probabilities for [class_0_prob, class_1_prob]
            # We usually want the probability of the "positive" or target class.
            # If anomaly (0) is your positive class for interpretation, use proba[:,0]
            # If non-anomaly (1) is positive, use proba[:,1]
            # The AUC-ROC in your eval was for class 1, so let's get P(class 1)
            probabilities = pipeline.predict_proba(input_df)[:, 1] # Probability of Not Anomaly
        except Exception as e:
            print(f"Error during model predict_proba: {e}")
            probabilities = [0.0] * len(predictions) # Fallback

    return predictions.tolist(), probabilities.tolist() if probabilities is not None else [None] * len(predictions)


if __name__ == '__main__':
    # Example usage (for testing the module directly)
    if pipeline:
        print("\n--- Testing predictor module ---")
        sample_data = [
            {
                'SubAxis': 'Prices', 'ProcessName': 'Recepción de ficheros de AC_RF', 'Periodicity': 'Daily',
                'Status_D_minus_1': 'OK', 'ObservedDurationMetric': 1500.0, 'CommitmentHour': 18, 'DayOfWeek': 3
            },
            {
                'SubAxis': 'WA', 'ProcessName': 'Daily Contractos WA was executed', 'Periodicity': 'Daily',
                'Status_D_minus_1': 'OK', 'ObservedDurationMetric': 60.0, 'CommitmentHour': 10, 'DayOfWeek': 1
            },
            { # Example of a potentially anomalous 'OK' process based on new features
                'SubAxis': 'Automatic Jobs', 'ProcessName': 'Derivative Price Control Process', 'Periodicity': 'Daily',
                'Status_D_minus_1': 'PDTE', 'ObservedDurationMetric': 120.0, 'CommitmentHour': 13, 'DayOfWeek': 2 # High duration
            }
        ]
        
        # Manually ensure the sample_data keys match EXPECTED_FEATURE_NAMES structure
        # and that numerical values are appropriate (not strings)
        
        preds, probs = predict_anomaly(sample_data)
        for i, (data, pred, prob) in enumerate(zip(sample_data, preds, probs)):
            print(f"\nInput {i+1}: {data}")
            print(f"Prediction: {'Anomaly (0)' if pred == 0 else 'Not Anomaly (1)'}")
            if prob is not None:
                print(f"Probability (Not Anomaly): {prob:.4f}")
    else:
        print("Model not loaded, cannot run test.")