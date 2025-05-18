import openpyxl
import logging
import os

def get_excel_headers(template_path: str) -> list[str]:
    """
    Reads the first row from the first sheet of an Excel file to get headers.
    Returns an empty list if file not found, is invalid, or has no headers.
    """
    headers = []
    if not template_path or not os.path.exists(template_path):
        logging.warning(f"Template file path not provided or file not found: {template_path}")
        return headers

    try:
        workbook = openpyxl.load_workbook(template_path, read_only=True, data_only=True)
        sheet = workbook.active # Get the first active sheet
        if sheet.max_row >= 1: # Check if there's at least one row
            # Iterate through cells in the first row
            for cell in sheet[1]: # sheet[1] accesses the first row
                if cell.value: # Check if cell has a value
                    headers.append(str(cell.value).strip()) # Convert to string and strip whitespace
        workbook.close() # Close the workbook when done (important for read_only)
        logging.debug(f"Extracted headers from '{template_path}': {headers}")
    except Exception as e:
        logging.error(f"Error reading headers from Excel file '{template_path}': {e}", exc_info=True)
        # Ensure workbook is closed even if error occurs during processing
        if 'workbook' in locals() and workbook:
            try: workbook.close()
            except: pass
        headers = [] # Return empty list on error

    return headers