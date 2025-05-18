# run_scenario_manually.py
import sys
import os
import argparse # Use argparse for better argument handling

# --- Ensure the app package can be imported ---
# Add project root to Python path to allow importing 'app'
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- End path setup ---

# Import the Flask app factory function and the runner class
from app import create_app
from app.runner import AutomationRunner

def main():
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(description="Run a specific monitoring scenario manually.")
    # Required argument: scenario_id
    parser.add_argument("scenario_id", type=int, help="The ID of the scenario to run.")
    # Optional flag: --show-browser
    parser.add_argument(
        "--show-browser",
        action="store_true", # Makes this a flag; default is False if not present
        help="Run the browser in non-headless mode (visible window)."
    )
    args = parser.parse_args()
    # --- End Argument Parsing ---

    scenario_id_to_run = args.scenario_id
    # Determine headless mode based on the flag's presence
    headless_mode = not args.show_browser

    # Create a Flask app instance using the factory
    # This initializes Flask extensions like SQLAlchemy and Mail based on config
    flask_app = create_app()

    # Use the application context manager. This is crucial because:
    # 1. It makes 'db.session' work correctly inside the runner.
    # 2. It allows extensions like Flask-Mail to access app config and state.
    with flask_app.app_context():
        print(f"\n--- Running Scenario ID: {scenario_id_to_run} ---")
        print(f"Headless mode: {headless_mode}")

        try:
            # Instantiate the runner, passing the scenario ID AND the app instance
            runner = AutomationRunner(
                scenario_id=scenario_id_to_run,
                app=flask_app,  # Pass the created app instance
                headless=headless_mode
            )
            # Execute the run method
            success = runner.run()

            # Check the outcome and set exit code
            if success:
                print(f"\n--- Scenario {scenario_id_to_run} finished successfully. ---")
                sys.exit(0) # Exit with success code 0
            else:
                print(f"\n--- Scenario {scenario_id_to_run} failed. Check logs above. ---")
                sys.exit(1) # Exit with failure code 1

        except ValueError as e:
            # Catch specific known errors like Scenario ID not found during setup
            print(f"\n--- CONFIGURATION ERROR: {e} ---")
            sys.exit(1) # Exit with failure code
        except Exception as e:
            # Catch any other unexpected errors during runner instantiation or execution
            print(f"\n--- UNEXPECTED RUNTIME ERROR: {e} ---")
            # For deeper debugging, uncomment the next two lines to see the full traceback
            # import traceback
            # traceback.print_exc()
            sys.exit(1) # Exit with failure code

# Standard Python entry point check: ensures main() runs only when script is executed directly
if __name__ == "__main__":
    main()