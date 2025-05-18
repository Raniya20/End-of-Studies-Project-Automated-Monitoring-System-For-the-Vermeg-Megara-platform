# preprocess_reports.py
import os
import glob
import pandas as pd
import numpy as np
import logging
from pathlib import Path

# --- Configuration ---
# <<< ** ADJUST THESE PATHS AND SETTINGS ** >>>
HISTORICAL_DATA_DIR = Path('./historical_reports') # Input directory
CLEANED_OUTPUT_FILE = Path('./cleaned_monitoring_data.csv') # Output file path
EXCEL_FILE_PATTERN = '*.xlsx'

# --- Define EXPECTED structure ---
# Primary sheet name and header row index (0-based)
PRIMARY_SHEET_NAME = 'Diario'
PRIMARY_HEADER_INDEX = 3 # Row 4 in Excel

PROCESS_COL = 'Process' # Standard name for the process column
PERIODICITY_COL = 'Periodicity'
STATUS_TODAY_COL = 'Status_Today'
STATUS_LEGEND_COL = 'Status_Legend'
REMARKS_COL = 'Remarks'

# List of REQUIRED columns (using the *standardized* names you want)
# These MUST exist after renaming.
REQUIRED_COLUMNS_STD = [
    'Process',
    'Periodicity',
    'Status_Today',
    'Status_Legend',
    'Remarks'
    # Add other STANDARD names if needed for features:
    # 'Status_Yesterday',
    # 'Time_Expected',
    # 'Time_Actual',
]

# --- Define variations and renaming rules ---
# Add alternative sheet names to try if the primary one fails
ALT_SHEET_NAMES = ['Sheet1', 'Feuil1'] # Add others if known

# Add alternative header row indices (0-based) to try
ALT_HEADER_INDICES = [4, 5] # Try Row 5, Row 6 if Row 4 fails

# Define mapping from POSSIBLE names in Excel files to STANDARD names
# Keys: Potential names found in files (case-insensitive check recommended)
# Values: The single STANDARD name you want to use
COLUMN_RENAME_MAP = {
    # Process Name
    'processus / sous-processus': 'Process',
    'proceso / subproceso': 'Process',
    # Periodicity
    'périodicité': 'Periodicity',
    'periodicidad': 'Periodicity',
    # Status Today
    'date d': 'Status_Today',
    'estado d': 'Status_Today',
    # Status Legend
    'leyenda': 'Status_Legend',
    # Remarks
    'remarques': 'Remarks',
    'observaciones': 'Remarks',
    # Add other columns and their variations here if needed
    'date (j-1)': 'Status_Yesterday',
    'estado d-1': 'Status_Yesterday',
    'engagement en termes de temps': 'Time_Expected',
    'hora compromiso': 'Time_Expected',
    'temps réel': 'Time_Actual',
    'hora real': 'Time_Actual',
}


# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - PREPROCESS - %(levelname)s - %(message)s')

# --- Main Preprocessing Logic ---
def preprocess_reports():
    logging.info("--- Starting Preprocessing ---")
    logging.info(f"Input directory: {HISTORICAL_DATA_DIR.resolve()}")
    logging.info(f"Output file: {CLEANED_OUTPUT_FILE.resolve()}")

    all_files = list(HISTORICAL_DATA_DIR.glob(EXCEL_FILE_PATTERN))
    if not all_files:
        logging.error(f"No files found matching '{EXCEL_FILE_PATTERN}'. Stopping."); return

    logging.info(f"Found {len(all_files)} potential files.")

    processed_data_frames = []
    skipped_files = []
    potential_sheets_to_try = [PRIMARY_SHEET_NAME] + ALT_SHEET_NAMES
    potential_headers_to_try = [PRIMARY_HEADER_INDEX] + ALT_HEADER_INDICES

    for f in all_files:
        if f.name.startswith('~$'): continue

        logging.info(f"Processing file: {f.name}")
        df_loaded = None
        sheet_found = None
        header_found = None

        # --- Try loading with different sheets/headers ---
        for sheet_name in potential_sheets_to_try:
            for header_idx in potential_headers_to_try:
                try:
                    df_try = pd.read_excel(f, sheet_name=sheet_name, header=header_idx)
                    logging.debug(f"  Attempt: Sheet='{sheet_name}', Header Index={header_idx}. Found columns: {list(df_try.columns)}")

                    # --- <<<< SIMPLIFIED CHECK: Just try to load, check columns AFTER rename >>>> ---
                    # Assume we found a potential candidate, store it and break inner loop
                    df_loaded = df_try
                    sheet_found = sheet_name
                    header_found = header_idx
                    logging.info(f"  Loaded data from Sheet='{sheet_name}', Header Index={header_idx}. Will validate columns after rename.")
                    break # Stop trying headers for this sheet

                except ValueError as ve: # Handles sheet not found
                    if "Worksheet named" in str(ve) and sheet_name in str(ve):
                         logging.debug(f"  Sheet '{sheet_name}' not found in {f.name}.")
                         break # No point trying other headers if sheet doesn't exist
                    else: logging.warning(f"  Error reading {f.name} Sheet='{sheet_name}' H={header_idx}: {ve}")
                except Exception as e:
                    logging.warning(f"  Unexpected error reading {f.name} Sheet='{sheet_name}' H={header_idx}: {e}")
            if df_loaded is not None:
                break # Stop trying sheets if data loaded

        # --- Process loaded DataFrame (if one was loaded) ---
        if df_loaded is not None:
            try:
                # 1. Rename columns to standard names (case-insensitive)
                original_cols = list(df_loaded.columns) # Keep original for logging if needed
                df_loaded.columns = df_loaded.columns.str.lower().str.strip()
                rename_map_lower = {k.lower(): v for k, v in COLUMN_RENAME_MAP.items()}
                # Only rename columns that actually exist in the rename map keys
                cols_to_rename = {col: rename_map_lower[col] for col in df_loaded.columns if col in rename_map_lower}
                df_loaded.rename(columns=cols_to_rename, inplace=True)
                logging.debug(f"  Renamed columns. Mappings applied: {cols_to_rename}")
                logging.debug(f"  Columns after rename: {list(df_loaded.columns)}")


                # --- <<<< MOVED VALIDATION HERE >>>> ---
                # 2. Check if all REQUIRED STANDARD columns are now present AFTER renaming
                missing_std_cols = [col for col in REQUIRED_COLUMNS_STD if col not in df_loaded.columns]
                if missing_std_cols:
                    logging.warning(f"  Skipping {f.name} Sheet='{sheet_found}' H={header_found}: Missing STANDARD columns after rename: {missing_std_cols}")
                    skipped_files.append(f.name)
                    continue # Skip this file
                # --- <<<< END MOVED VALIDATION >>>> ---

                # 3. Select only the standard columns needed
                all_std_cols_needed = REQUIRED_COLUMNS_STD # Extend if needed
                # Ensure we only select columns that actually exist after rename and validation
                df_selected = df_loaded[[col for col in all_std_cols_needed if col in df_loaded.columns]].copy()


                # 4. Filter rows
                original_count = len(df_selected)
                df_selected.dropna(subset=[PROCESS_COL], inplace=True)
                df_selected = df_selected[df_selected[PROCESS_COL].astype(str) != PROCESS_COL] # Ensure comparison works
                rows_removed = original_count - len(df_selected)
                if rows_removed > 0: logging.debug(f"  Removed {rows_removed} potentially invalid rows.")

                if df_selected.empty:
                     logging.warning(f"  No valid data rows remaining in {f.name} Sheet='{sheet_found}'. Skipping.")
                     skipped_files.append(f.name)
                     continue

                # 5. Basic Cleaning
                for col in df_selected.select_dtypes(include=['object']).columns:
                     # Use .loc to avoid SettingWithCopyWarning if needed, although .copy() earlier helps
                     df_selected.loc[:, col] = df_selected[col].astype(str).str.strip()

                # 6. Add Source Info
                df_selected['SourceFile'] = f.name

                processed_data_frames.append(df_selected)
                logging.info(f"  Successfully processed {len(df_selected)} rows from {f.name} Sheet='{sheet_found}'.")

            except Exception as e:
                logging.error(f"  Error processing data from {f.name} Sheet='{sheet_found}' H={header_found}: {e}", exc_info=True)
                skipped_files.append(f.name)
        else:
            logging.warning(f"Could not find or load suitable data from any sheet/header in {f.name}. Skipping.")
            skipped_files.append(f.name)

    # --- 7. Concatenate and Final Output ---
    if not processed_data_frames:
        logging.error("No dataframes were successfully processed. No output file generated.")
        return

    final_data = pd.concat(processed_data_frames, ignore_index=True)
    logging.info(f"Concatenated data: {final_data.shape[0]} rows, {final_data.shape[1]} columns.")

    # Optional: Add final checks (e.g., check for duplicates across files?)
    # final_data.drop_duplicates(subset=[...], keep='first', inplace=True)

    # Ensure output directory exists
    CLEANED_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Save to CSV
    try:
        final_data.to_csv(CLEANED_OUTPUT_FILE, index=False, encoding='utf-8-sig') # utf-8-sig for better Excel compatibility
        logging.info(f"Successfully saved cleaned data to: {CLEANED_OUTPUT_FILE.resolve()}")
    except Exception as e:
        logging.error(f"Error saving final CSV file: {e}", exc_info=True)

    if skipped_files:
        logging.warning(f"The following {len(skipped_files)} files were skipped due to errors or missing data:")
        for skipped in skipped_files: logging.warning(f"  - {skipped}")

    logging.info("--- Preprocessing Finished ---")

if __name__ == "__main__":
    # Create input directory if it doesn't exist (user needs to add files)
    HISTORICAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    preprocess_reports()