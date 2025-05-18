# scheduler.py
import logging
import sys
import os
import time
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

# --- Ensure the app package can be imported ---
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- End path setup ---

from app import create_app, db # Import Flask app factory and db instance
from app.models import Scenario # Import Scenario model
from app.runner import AutomationRunner # Import the runner

# Configure logging for the scheduler
logging.basicConfig(level=logging.INFO, format='%(asctime)s - SCHEDULER - %(levelname)s - %(message)s')
log = logging.getLogger('apscheduler.executors.default') # Get APScheduler logger
log.setLevel(logging.INFO) # Set APScheduler log level if needed

# --- Job Function ---
def run_scenario_job(scenario_id: int):
    """
    The function executed by the scheduler for each scenario job.
    It runs within a Flask app context.
    """
    log.info(f"SCHEDULER: Triggered job for Scenario ID: {scenario_id}")
    flask_app = create_app() # Create app instance to get context
    with flask_app.app_context():
        try:
            # Ensure scenario still exists and is valid before running
            scenario = db.session.get(Scenario, scenario_id)
            if not scenario:
                log.warning(f"SCHEDULER: Scenario ID {scenario_id} not found in DB. Job might be stale.")
                return # Don't run if scenario deleted

            # --- Instantiate and run the runner ---
            # Decide headless mode based on environment or default to True
            headless = os.environ.get('RUNNER_HEADLESS_MODE', 'True').lower() == 'true'
            log.info(f"SCHEDULER: Instantiating runner for Scenario ID {scenario_id} (Headless: {headless})")
            runner = AutomationRunner(scenario_id=scenario_id, headless=headless)
            success = runner.run()
            log.info(f"SCHEDULER: Runner for Scenario ID {scenario_id} finished. Success: {success}")

        except Exception as e:
            log.error(f"SCHEDULER: Error executing job for Scenario ID {scenario_id}: {e}", exc_info=True)
            # Important: Don't let job errors crash the scheduler

# --- Scheduler Setup ---
scheduler = BlockingScheduler(timezone="UTC") # Use UTC or your server's local timezone consistently

def load_or_reschedule_jobs():
    """
    Queries the database for Scenarios and schedules/updates jobs in APScheduler.
    """
    log.info("SCHEDULER: Loading/Rescheduling jobs from database...")
    flask_app = create_app()
    added_count = 0
    updated_count = 0
    error_count = 0
    processed_job_ids = set() # Keep track of jobs processed in this run

    with flask_app.app_context():
        try:
            active_scenarios = Scenario.query.all() # Fetch all scenarios (add filter if needed e.g., is_active=True)
            log.info(f"SCHEDULER: Found {len(active_scenarios)} scenarios in database.")

            for scenario in active_scenarios:
                job_id = f'scenario_{scenario.scenario_id}'
                processed_job_ids.add(job_id)

                if not scenario.schedule_cron:
                    log.warning(f"SCHEDULER: Scenario ID {scenario.scenario_id} ('{scenario.name}') has no cron schedule. Skipping.")
                    # Remove existing job if schedule was removed
                    try: scheduler.remove_job(job_id)
                    except JobLookupError: pass # Ignore if job doesn't exist
                    continue

                try:
                    # Create trigger from cron string
                    trigger = CronTrigger.from_crontab(scenario.schedule_cron, timezone=scheduler.timezone)

                    # Add or modify the job
                    job = scheduler.add_job(
                        run_scenario_job,
                        trigger=trigger,
                        args=[scenario.scenario_id],
                        id=job_id,
                        name=f"Run Scenario {scenario.scenario_id}: {scenario.name}",
                        replace_existing=True, # Update if cron schedule changed
                        misfire_grace_time=300 # Allow job to run 5 mins late if scheduler was down
                    )
                    if job.next_run_time: # Check if it was added/updated or already existed unchanged
                         existing_job = scheduler.get_job(job_id)
                         # APScheduler doesn't easily tell if add_job modified an existing one,
                         # so we just log based on whether it exists. A more complex check
                         # could compare triggers before calling add_job.
                         # This logic might double-count updates vs adds on initial load.
                         if existing_job and existing_job.trigger == trigger:
                              log.debug(f"SCHEDULER: Job '{job_id}' confirmed/unchanged. Next run: {job.next_run_time}")
                         else:
                              log.info(f"SCHEDULER: Scheduled/Updated job '{job_id}' for Scenario {scenario.scenario_id}. Next run: {job.next_run_time}")
                              updated_count += 1 # Count adds and updates together for simplicity
                    else:
                         log.warning(f"SCHEDULER: Job '{job_id}' added but has no scheduled run time (maybe cron schedule is in the past?).")


                except ValueError as e:
                    log.error(f"SCHEDULER: Invalid cron string '{scenario.schedule_cron}' for Scenario ID {scenario.scenario_id}: {e}")
                    error_count += 1
                    # Remove job if cron string becomes invalid
                    try: scheduler.remove_job(job_id)
                    except JobLookupError: pass
                except Exception as e:
                     log.error(f"SCHEDULER: Error scheduling job for Scenario ID {scenario.scenario_id}: {e}", exc_info=True)
                     error_count += 1

            # Optional: Remove jobs for scenarios that no longer exist in the DB
            all_scheduled_job_ids = {job.id for job in scheduler.get_jobs() if job.id.startswith('scenario_')}
            stale_job_ids = all_scheduled_job_ids - processed_job_ids
            if stale_job_ids:
                 log.info(f"SCHEDULER: Removing {len(stale_job_ids)} stale jobs: {stale_job_ids}")
                 for job_id in stale_job_ids:
                      try: scheduler.remove_job(job_id)
                      except JobLookupError: pass # Ignore if already gone

        except Exception as e:
            log.error(f"SCHEDULER: Failed to query scenarios from database: {e}", exc_info=True)

    log.info(f"SCHEDULER: Job load finished. Added/Updated: {updated_count}, Errors: {error_count}")


# --- Main Execution ---
if __name__ == "__main__":
    log.info("--- Starting Scheduler ---")

    # Load jobs initially
    load_or_reschedule_jobs()

    # Optional: Reschedule periodically if scenarios might change frequently
    # without restarting the scheduler (e.g., every hour)
    # scheduler.add_job(load_or_reschedule_jobs, 'interval', hours=1, id='job_rescheduler')

    log.info("Scheduler started. Press Ctrl+C to exit.")
    try:
        # Start the scheduler (this blocks the script)
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler interrupted. Shutting down...")
        scheduler.shutdown()
        log.info("Scheduler shutdown complete.")
    except Exception as e:
         log.error(f"SCHEDULER: An unexpected error occurred: {e}", exc_info=True)
         scheduler.shutdown()