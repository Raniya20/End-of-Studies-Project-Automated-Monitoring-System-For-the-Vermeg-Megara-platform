# app/reports/routes.py
from flask import render_template, redirect, url_for, flash, current_app, request
from flask_login import login_required, current_user
from sqlalchemy import desc, and_
from datetime import datetime, date
import os 
import logging

from app import db 
from app.reports import bp
from app.models import Scenario, ExecutionLog, ExecutionStatusEnum

@bp.route('/')
@login_required
def my_reports():
    """Displays a list of generated reports, with filtering capabilities."""
    try:
        # --- Get Filter Parameters ---
        page = request.args.get('page', 1, type=int) # For pagination later
        per_page = 15 # Reports per page

        filter_scenario_id = request.args.get('scenario_id', type=int)
        filter_report_name = request.args.get('report_name', type=str, default="").strip()
        filter_start_date_str = request.args.get('start_date', type=str)
        filter_end_date_str = request.args.get('end_date', type=str)

        # Convert date strings to date objects
        filter_start_date = None
        if filter_start_date_str:
            try: filter_start_date = datetime.strptime(filter_start_date_str, '%Y-%m-%d').date()
            except ValueError: flash("Invalid start date format. Please use YYYY-MM-DD.", "warning")

        filter_end_date = None
        if filter_end_date_str:
            try: filter_end_date = datetime.strptime(filter_end_date_str, '%Y-%m-%d').date()
            except ValueError: flash("Invalid end date format. Please use YYYY-MM-DD.", "warning")
        # --- End Filter Parameters ---


        # --- Base Query ---
        query = db.session.query(
            ExecutionLog.log_id,
            ExecutionLog.end_time,
            ExecutionLog.report_file_path,
            Scenario.name.label('scenario_name'),
            Scenario.scenario_id
        ).join(Scenario, ExecutionLog.scenario_id == Scenario.scenario_id)\
         .filter(Scenario.created_by_user_id == current_user.user_id)\
         .filter(ExecutionLog.report_file_path.isnot(None))\
         .filter(ExecutionLog.report_file_path != '')\
         .filter(ExecutionLog.status == ExecutionStatusEnum.SUCCESS)
        # --- End Base Query ---


        # --- Apply Filters ---
        if filter_scenario_id:
            query = query.filter(Scenario.scenario_id == filter_scenario_id)
            logging.debug(f"Filtering reports by scenario_id: {filter_scenario_id}")

        if filter_report_name:
            # Use ilike for case-insensitive partial matching on the filename part
            query = query.filter(ExecutionLog.report_file_path.ilike(f'%{filter_report_name}%'))
            logging.debug(f"Filtering reports by name containing: {filter_report_name}")

        if filter_start_date:
            # Compare date part of end_time
            query = query.filter(db.func.date(ExecutionLog.end_time) >= filter_start_date)
            logging.debug(f"Filtering reports from start_date: {filter_start_date}")

        if filter_end_date:
            # Compare date part of end_time
            query = query.filter(db.func.date(ExecutionLog.end_time) <= filter_end_date)
            logging.debug(f"Filtering reports until end_date: {filter_end_date}")
        # --- End Apply Filters ---


        # Order and Paginate 
        pagination = query.order_by(desc(ExecutionLog.end_time)).paginate(page=page, per_page=per_page, error_out=False)
        user_logs_with_reports = pagination.items


        reports_info = []
        for log in user_logs_with_reports:
            reports_info.append({
                'log_id': log.log_id,
                'scenario_id': log.scenario_id,
                'scenario_name': log.scenario_name,
                'generation_time': log.end_time.strftime('%Y-%m-%d %H:%M:%S UTC') if log.end_time else 'N/A',
                'filename': os.path.basename(log.report_file_path) if log.report_file_path else "Unknown Filename"
            })
        logging.info(f"User {current_user.user_id} fetched {len(reports_info)} reports for page {page}.")

        # Get scenarios for the filter dropdown
        user_scenarios_for_filter = Scenario.query.filter_by(created_by_user_id=current_user.user_id).order_by(Scenario.name).all()

    except Exception as e:
        logging.error(f"Error fetching reports for user {current_user.user_id}: {e}", exc_info=True)
        flash("Could not retrieve reports at this time.", "danger")
        reports_info = []
        user_scenarios_for_filter = []
        pagination = None # Ensure pagination is defined even on error

    return render_template(
        'reports/my_reports.html',
        title="My Generated Reports",
        reports=reports_info,
        user_scenarios_for_filter=user_scenarios_for_filter, # For dropdown
        pagination=pagination, # Pass pagination object
        # Pass current filter values back to template to pre-fill form
        filter_scenario_id=filter_scenario_id,
        filter_report_name=filter_report_name,
        filter_start_date=filter_start_date_str, # Send string back for input field
        filter_end_date=filter_end_date_str   # Send string back for input field
    )