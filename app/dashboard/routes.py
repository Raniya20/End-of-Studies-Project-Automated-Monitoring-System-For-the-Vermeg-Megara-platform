# app/dashboard/routes.py
from flask import logging, render_template, jsonify, request, abort
from flask_login import login_required, current_user
from sqlalchemy import desc # For ordering
from datetime import datetime, timedelta
import json # Although jsonify handles most cases

from app import db
from app.dashboard import bp # Import the dashboard blueprint
from app.models import Scenario, ExecutionLog, MonitoringResult, ExecutionStatusEnum

FEATURE_EXTRACTED_COUNT = 'Extracted_Count'

# How many days of history to show by default
DEFAULT_DAYS_HISTORY = 7

@bp.route('/')
@login_required
def index():
    """Main dashboard overview page."""
    # Get scenarios owned by user to populate a selector maybe?
    user_scenarios = Scenario.query.filter_by(created_by_user_id=current_user.user_id).order_by(Scenario.name).all()

    # For now, just render the template. Data fetching will happen via JS/API
    # Or fetch data for a default scenario here? Let's try fetching for first scenario.
    selected_scenario_id = request.args.get('scenario_id', type=int)
    scenario = None

    if selected_scenario_id:
         scenario = db.session.get(Scenario, selected_scenario_id)
         # Security check: ensure user owns this scenario
         if not scenario or scenario.created_by_user_id != current_user.user_id:
              abort(403) # Forbidden
    elif user_scenarios:
         # Default to the first scenario if none selected
         scenario = user_scenarios[0]
         selected_scenario_id = scenario.scenario_id

    return render_template(
        'dashboard/dashboard.html', # We'll create this template
        title="Monitoring Dashboard",
        user_scenarios=user_scenarios,
        selected_scenario=scenario # Pass the selected scenario object
    )


@bp.route('/data/<int:scenario_id>')
@login_required
def get_chart_data(scenario_id):
    """API endpoint to fetch processed data for dashboard charts."""
    scenario = db.session.get(Scenario, scenario_id)
    # Security check
    if not scenario or scenario.created_by_user_id != current_user.user_id:
        return jsonify({"success": False, "message": "Permission denied"}), 403

    # Get date range (e.g., last 7 days)
    days = request.args.get('days', DEFAULT_DAYS_HISTORY, type=int)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    logging.info(f"Fetching dashboard data for Scenario {scenario_id} from {start_date} to {end_date}")

    # Query Execution Logs and Monitoring Results within the date range
    # Join results to logs to filter by date, order by date
    query = (db.session.query(
                    MonitoringResult.metric_name,
                    MonitoringResult.metric_value,
                    MonitoringResult.is_anomaly,
                    ExecutionLog.start_time
                 )
                 .join(ExecutionLog, MonitoringResult.log_id == ExecutionLog.log_id)
                 .filter(ExecutionLog.scenario_id == scenario_id)
                 .filter(ExecutionLog.start_time >= start_date)
                 .filter(ExecutionLog.status == ExecutionStatusEnum.SUCCESS)
                 .order_by(ExecutionLog.start_time.asc())
                )
    results = query.all()
    logging.info(f"Found {len(results)} MonitoringResult records for charts.")

    # --- Process data for Chart.js ---
    # This part HEAVILY depends on what you want to visualize.
    # Example: Plot the 'Extracted_Count' for a specific table over time.
    #          Requires knowing the metric_name pattern (e.g., 'example_table_1_INDEX_Extracted_Count')
    # Let's try plotting the first numeric metric we find per run day.

    chart_data = {
        'labels': [],       # X-axis (e.g., Dates)
        'datasets': [
            {
                'label': 'Example Metric Value', # Name of the dataset
                'data': [],            # Y-axis values
                'borderColor': 'rgb(75, 192, 192)',
                'backgroundColor': 'rgba(75, 192, 192, 0.5)',
                'tension': 0.1,
                'pointBackgroundColor': [] # For anomaly highlighting
            }
            # Add more datasets for other metrics
        ]
    }
    anomaly_colors = { True: 'rgba(255, 99, 132, 1)', False: 'rgba(75, 192, 192, 1)'}

    # Basic aggregation: Group by day, take first numeric value found? Needs refinement.
    # This example assumes metric_name tells us what we need.
    # A better approach stores metrics more predictably in _save_monitoring_results.
    # For now, just find 'Extracted_Count' metrics.
    processed_dates = set()
    for result in results:
        # Example: Find metrics related to the count feature
        metric_name_parts = result.metric_name.split('_')
        # Check if metric name relates to the count feature (adjust pattern if needed)
        if FEATURE_EXTRACTED_COUNT in metric_name_parts: # Use constant defined in runner/training
            date_str = result.start_time.strftime('%Y-%m-%d')
            # Only add one point per day per dataset for simplicity here
            if date_str not in processed_dates:
                chart_data['labels'].append(date_str)
                try:
                    # Attempt to convert metric value to float for plotting
                    value = float(result.metric_value)
                    chart_data['datasets'][0]['data'].append(value)
                except (ValueError, TypeError):
                    # If not numeric, plot as 0 or NaN? Let's use NaN (Chart.js can handle it)
                    chart_data['datasets'][0]['data'].append(None) # Use None for non-numeric

                # Set point color based on anomaly flag
                chart_data['datasets'][0]['pointBackgroundColor'].append(anomaly_colors[result.is_anomaly])
                processed_dates.add(date_str)
                # Limit number of points?
                # if len(processed_dates) > 100: break

    # Rename dataset label if we know what we plotted
    if processed_dates: # Check if any data was added
         chart_data['datasets'][0]['label'] = f'{FEATURE_EXTRACTED_COUNT} (Example)'


    return jsonify({"success": True, "chartData": chart_data})