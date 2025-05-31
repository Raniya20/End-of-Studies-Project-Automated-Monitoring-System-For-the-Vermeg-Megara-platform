# app/dashboard/routes.py
import logging
from datetime import datetime, timedelta, date, time as dt_time
from flask import render_template, jsonify, request, abort, g
from flask_login import login_required, current_user
from sqlalchemy import desc, cast, Date, func, and_ # Ensure func, and_ are imported
from collections import defaultdict # For grouping

from app import db
from app.dashboard import bp
from app.models import Scenario, ExecutionLog, MonitoringResult, ExecutionStatusEnum

# --- Constants (used for deriving features from MonitoringResult if not stored directly) ---
# These should align with how your Runner saves metric_names.
# Example: If a metric is saved as 'MainTable_ProcessA_Daily_0_ObservedDurationMetric'
# and 'ProcessA' is what you want, you'll need to parse it.
# If runner saves 'ProcessName' as a metric type, that's easier.
# For this example, we'll do some basic parsing.

# Define standard names for metrics that the API expects to find or derive
# These are what the API will look for in MonitoringResult.metric_name (often as the last part)
METRIC_NAME_OBSERVED_DURATION = 'ObservedDurationMetric'
METRIC_NAME_COMMITMENT_HOUR = 'CommitmentHour_ModelInput' # As saved by runner from features
METRIC_NAME_DAY_OF_WEEK = 'DayOfWeek_ModelInput'     # As saved by runner from features
METRIC_NAME_PERIODICITY = 'Periodicity'             # As saved by runner from features
METRIC_NAME_PROCESS_NAME = 'ProcessName'             # If saved as metric_type='ProcessName'
METRIC_NAME_ORIGINAL_STATUS_D = 'OriginalStatusD'       # If saved as metric_type='OriginalStatusD'
METRIC_NAME_TYPICAL_OK_DURATION = 'TypicalOKDuration'   # If saved as metric_type='TypicalOKDuration'
METRIC_NAME_IS_ANOMALOUS_FLAG = 'IsAnomalousFlag'     # If saved as metric_type='IsAnomalousFlag'


DEFAULT_DAYS_HISTORY = 1 # For "Today" view primarily

# --- Main Dashboard Page Route (Renders the HTML shell) ---
@bp.route('/')
@login_required
def index():
    """Renders the main Daily Operations Health dashboard page."""
    user_scenarios = Scenario.query.filter_by(created_by_user_id=current_user.user_id).order_by(Scenario.name).all()
    return render_template(
        'dashboard/dashboard_overview.html',
        title="Daily Operations Health",
        user_scenarios=user_scenarios # For the scenario filter dropdown
    )

# --- API Endpoint for Daily Operations Health Overview Data ---
@bp.route('/data/overview')
@login_required
def get_daily_operations_overview_data():
    auth_user = current_user
    
    date_filter_str = request.args.get('report_date', datetime.utcnow().strftime('%Y-%m-%d'))
    try:
        report_date = datetime.strptime(date_filter_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"success": False, "message": "Invalid report_date format. Use YYYY-MM-DD."}), 400

    selected_scenario_id_str = request.args.get('scenario_id') # Can be 'all' or an ID
    
    start_of_day = datetime.combine(report_date, dt_time.min)
    end_of_day = datetime.combine(report_date, dt_time.max)

    logging.info(f"API Overview: User {auth_user.user_id}, Date {report_date}, Scenario Filter: {selected_scenario_id_str}")

    try:
        user_scenario_ids_query = Scenario.query.with_entities(Scenario.scenario_id)\
                                         .filter_by(created_by_user_id=auth_user.user_id)
        user_scenario_ids = [id_tuple[0] for id_tuple in user_scenario_ids_query.all()]

        if not user_scenario_ids:
            return jsonify({"success": True, "message": "No scenarios found for this user.", "data": {
                "kpis": {"overall_health_status": "NO_DATA", "anomaly_rate_today": 0, "anomalies_today_count": 0, "total_processes_monitored": 0},
                "top_anomalous_processes": [], "critical_pending_anomalies": [],
                "anomaly_rates_by_dimension": {
                    "CommitmentHour": {"labels": [], "data": []},
                    "DayOfWeek": {"labels": [], "data": []},
                    "Periodicity": {"labels": [], "data": []}
                }
            }})

        # --- Base Query for all relevant MonitoringResults for the day/filters ---
        base_query = db.session.query(
            MonitoringResult, # Get the whole MonitoringResult object
            ExecutionLog.start_time.label('detection_time'),
            Scenario.name.label('scenario_name'),
            Scenario.scenario_id # For linking
        ).select_from(MonitoringResult)\
         .join(ExecutionLog, MonitoringResult.log_id == ExecutionLog.log_id)\
         .join(Scenario, ExecutionLog.scenario_id == Scenario.scenario_id)\
         .filter(Scenario.scenario_id.in_(user_scenario_ids))\
         .filter(ExecutionLog.start_time >= start_of_day)\
         .filter(ExecutionLog.start_time <= end_of_day)

        if selected_scenario_id_str and selected_scenario_id_str.lower() != 'all':
            try:
                selected_scenario_id = int(selected_scenario_id_str)
                if selected_scenario_id not in user_scenario_ids:
                     return jsonify({"success": False, "message": "Invalid scenario selected or permission denied."}), 403
                base_query = base_query.filter(Scenario.scenario_id == selected_scenario_id)
            except ValueError:
                 logging.warning(f"Invalid scenario_id parameter: {selected_scenario_id_str}")

        all_results_for_day_raw = base_query.order_by(ExecutionLog.start_time, MonitoringResult.id).all() # Order for consistent grouping
        logging.info(f"API: Fetched {len(all_results_for_day_raw)} MonitoringResult entries for overview.")

        # --- Process results into instances_data ---
        instances_data = defaultdict(lambda: {
            "metrics": {}, "is_anomaly_overall": False, "anomaly_score_overall": None,
            "log_id": None, "scenario_name": None, "detection_time": None,
            "ProcessName": "Unknown Process", "OriginalStatusD": "UNKNOWN",
            "Periodicity": "Unknown", "CommitmentHour": -1, "DayOfWeek": -1
        })
        
        # This loop groups metrics by their common prefix, which identifies a unique process instance from a run
        for res_tuple in all_results_for_day_raw:
            mr = res_tuple.MonitoringResult
            metric_parts = mr.metric_name.split('_')
            instance_base_key = "_".join(metric_parts[:-1]) if len(metric_parts) > 1 else mr.metric_name
            metric_type = metric_parts[-1] if len(metric_parts) > 1 else "Value"
            instance_id = f"{mr.log_id}_{instance_base_key}"

            if not instances_data[instance_id]["log_id"]: # Populate instance-level info once
                instances_data[instance_id].update({
                    "log_id": mr.log_id, "scenario_name": res_tuple.scenario_name,
                    "detection_time": res_tuple.detection_time
                })
            
            instances_data[instance_id]["metrics"][metric_type] = mr.metric_value

            # Extract specific known metrics into top-level instance data for easier access
            if metric_type == METRIC_NAME_PROCESS_NAME: instances_data[instance_id]["ProcessName"] = mr.metric_value
            if metric_type == METRIC_NAME_ORIGINAL_STATUS_D: instances_data[instance_id]["OriginalStatusD"] = mr.metric_value
            if metric_type == METRIC_NAME_PERIODICITY: instances_data[instance_id]["Periodicity"] = mr.metric_value
            if metric_type == METRIC_NAME_COMMITMENT_HOUR:
                try: instances_data[instance_id]["CommitmentHour"] = int(float(mr.metric_value))
                except: instances_data[instance_id]["CommitmentHour"] = -1
            if metric_type == METRIC_NAME_DAY_OF_WEEK:
                try: instances_data[instance_id]["DayOfWeek"] = int(float(mr.metric_value))
                except: instances_data[instance_id]["DayOfWeek"] = -1


            if metric_type == METRIC_NAME_IS_ANOMALOUS_FLAG and mr.metric_value.lower() == 'true':
                instances_data[instance_id]["is_anomaly_overall"] = True
                instances_data[instance_id]["anomaly_score_overall"] = mr.anomaly_score

        anomalous_instances = [data for data in instances_data.values() if data["is_anomaly_overall"]]
        anomalies_today_count = len(anomalous_instances)
        unique_process_names_monitored = set(data["ProcessName"] for data in instances_data.values())
        total_processes_monitored_today = len(unique_process_names_monitored)

        # --- 1. KPIs ---
        health_status_text = "GREEN"; anomaly_rate = 0.0
        if total_processes_monitored_today > 0:
            anomaly_rate = (anomalies_today_count / total_processes_monitored_today * 100)
            if 1 <= anomaly_rate < 5: health_status_text = "YELLOW"
            elif anomaly_rate >= 5: health_status_text = "RED"
        kpis = {
            "overall_health_status": health_status_text,
            "anomaly_rate_today": round(anomaly_rate, 2),
            "anomalies_today_count": anomalies_today_count,
            "total_processes_monitored": total_processes_monitored_today
        }

        # --- 2. Top Anomalous Processes ---
        process_anomaly_counts = defaultdict(int)
        for inst_data in anomalous_instances:
            process_anomaly_counts[inst_data["ProcessName"]] += 1
        top_anomalous_processes = sorted(process_anomaly_counts.items(), key=lambda item: item[1], reverse=True)[:5]

        # --- 3. "Still Pending & Anomalous" Watchlist ---
        critical_pending_list = []
        for inst_data in anomalous_instances: # Already filtered for anomalies
            if inst_data["OriginalStatusD"] == 'PENDING':
                pending_duration_str = inst_data["metrics"].get(METRIC_NAME_OBSERVED_DURATION) # This is pending duration
                typical_completion_str = inst_data["metrics"].get(METRIC_NAME_TYPICAL_OK_DURATION)
                pending_duration = 0.0; typical_completion = 60.0 # Defaults
                try: pending_duration = float(pending_duration_str) if pending_duration_str else 0.0
                except: pass
                try: typical_completion = float(typical_completion_str) if typical_completion_str else 60.0
                except: pass
                critical_pending_list.append({
                    "process_name": inst_data["ProcessName"], "scenario_name": inst_data["scenario_name"],
                    "pending_duration_min": f"{pending_duration:.0f}",
                    "typical_completion_min": f"{typical_completion:.0f}",
                    "exceeded_by_min": f"{max(0, pending_duration - typical_completion):.0f}",
                    "probability_normal": f"{inst_data['anomaly_score_overall']:.2%}" if inst_data['anomaly_score_overall'] is not None else "N/A",
                })
        critical_pending_list = sorted(critical_pending_list, key=lambda x: float(x['exceeded_by_min']), reverse=True)

        # --- 4. Anomaly Rate by Selectable Dimension ---
        def calculate_rate_by_dim(dimension_attribute_name):
            counts_by_dim = defaultdict(lambda: {'total': 0, 'anomalies': 0})
            for inst_data in instances_data.values(): # Use all instances for total counts
                dim_value = inst_data.get(dimension_attribute_name) # Get from top-level instance data
                if dim_value is not None and dim_value != -1 : # Check for valid values
                    if dimension_attribute_name == "DayOfWeek": # Convert number to day name for label
                         days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                         dim_value_label = days[dim_value] if 0 <= dim_value <= 6 else "UnknownDay"
                    else:
                         dim_value_label = str(dim_value)

                    counts_by_dim[dim_value_label]['total'] += 1
                    if inst_data["is_anomaly_overall"]:
                        counts_by_dim[dim_value_label]['anomalies'] += 1
            labels = sorted(counts_by_dim.keys(), key=lambda x: (isinstance(x, str), x)) # Sort, keeping numbers before strings if mixed
            data_rates = [round((counts_by_dim[lbl]['anomalies'] / counts_by_dim[lbl]['total']) * 100, 2) if counts_by_dim[lbl]['total'] > 0 else 0 for lbl in labels]
            return {"labels": labels, "data": data_rates}

        anomaly_rates_by_dimension = {
            "CommitmentHour": calculate_rate_by_dim("CommitmentHour"),
            "DayOfWeek": calculate_rate_by_dim("DayOfWeek"),
            "Periodicity": calculate_rate_by_dim("Periodicity"),
            # "SubAxis": calculate_rate_by_dim("SubAxis") # Add if 'SubAxis' is reliably in instances_data
        }

        dashboard_payload = {
            "kpis": kpis,
            "top_anomalous_processes": top_anomalous_processes,
            "critical_pending_anomalies": critical_pending_list,
            "anomaly_rates_by_dimension": anomaly_rates_by_dimension
        }
        return jsonify({"success": True, "data": dashboard_payload})

    except Exception as e:
        logging.error(f"API Error for Daily Operations Overview (User {auth_user.user_id}, Date {date_filter_str}): {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Internal server error: {str(e)}"}), 500