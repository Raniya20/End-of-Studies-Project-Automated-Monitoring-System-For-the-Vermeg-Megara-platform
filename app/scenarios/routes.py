# app/scenarios/routes.py
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user # Import login_required, current_user
from app import db
from app.scenarios import bp
from app.models import Scenario, Consultant, ScenarioStep, ActionTypeEnum, ReportTemplate, ColumnMapping, ProcessingRule, RuleOperatorEnum
from app.scenarios.forms import CreateScenarioForm, EditScenarioForm, ScenarioStepForm, ColumnMappingForm, ProcessingRuleForm
import os
import openpyxl
from sqlalchemy import func
import logging
from flask import request, jsonify
import uuid # For generating unique filenames
from werkzeug.utils import secure_filename # For sanitizing filenames
from flask import current_app # To access app.config and app.instance_path
from .utils import get_excel_headers
from flask import request, jsonify, g 
from app.auth.decorators import token_required

# --- Routes ---

# --- NEW HELPER FUNCTION ---
def get_template_headers(template_path):
    """Reads the first row from an Excel file to get headers."""
    headers = []
    if not template_path or not os.path.exists(template_path):
        logging.warning(f"Template path invalid or file not found: {template_path}")
        return headers # Return empty list if no path or file doesn't exist

    try:
        workbook = openpyxl.load_workbook(template_path, read_only=True, data_only=True)
        sheet = workbook.active # Get the first sheet
        # Iterate through the first row
        for cell in sheet[1]: # sheet[1] accesses the first row
            if cell.value: # Check if cell has a value
                headers.append(str(cell.value).strip()) # Add header, converting to string and stripping whitespace
        workbook.close() # Close workbook when done reading
        logging.debug(f"Read headers from template {template_path}: {headers}")
    except Exception as e:
        logging.error(f"Error reading headers from template {template_path}: {e}", exc_info=True)

@bp.route('/')
@bp.route('/list')
@login_required # Protect this route
def list_scenarios():
    # Filter scenarios by the currently logged-in user
    scenarios = Scenario.query.filter_by(created_by_user_id=current_user.user_id).order_by(Scenario.created_at.desc()).all()
    return render_template('scenarios/list.html', title='Monitoring Scenarios', scenarios=scenarios)

@bp.route('/<int:scenario_id>')
@login_required
def view_scenario(scenario_id):
    """Displays details, steps, and mappings, populates mapping form."""
    scenario = Scenario.query.get_or_404(scenario_id)
    if scenario.created_by_user_id != current_user.user_id:
        flash('Permission denied.', 'danger'); return redirect(url_for('scenarios.list_scenarios'))

    mappings = scenario.column_mappings.all()
    mapping_form = ColumnMappingForm()

    # --- Populate Template Header Choices ---
    template_headers = []
    if scenario.template and scenario.template.file_path:
        template_headers = get_excel_headers(scenario.template.file_path)
        if template_headers:
             # Format choices for SelectField: (value, label)
             mapping_form.template_header.choices = [(h, h) for h in template_headers]
             # Add an empty default choice (optional but recommended)
             mapping_form.template_header.choices.insert(0, ('', '-- Select Template Header --'))
        else:
             flash("Could not read headers from the associated template file. Please check the file or upload a new one.", "warning")
             mapping_form.template_header.choices = [('', '-- No Headers Found --')]
    else:
        # If no template, disable the field or provide a single disabled choice
        mapping_form.template_header.choices = [('', '-- No Template Uploaded --')]
        # Optionally disable the submit button if no template? (Handled in template below)
    # --- End Populate Choices ---

    # --- Get Rules --- 
    rules = scenario.processing_rules.all() # Fetch existing rules

    # --- Instantiate Add Rule Form --- 
    rule_form = ProcessingRuleForm()

    return render_template(
        'scenarios/view.html',
        title=f'Scenario: {scenario.name}',
        scenario=scenario,
        mappings=mappings,
        mapping_form=mapping_form,
        has_template=bool(scenario.template),  
        rules=rules,          
        rule_form=rule_form 
    )
@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_scenario():
    """Handles initial creation of a new scenario."""
    form = CreateScenarioForm()
    if form.validate_on_submit():
        # --- 1. Handle File Upload ---
        file = form.template_file.data # Get the uploaded file object
        template_record = None
        try:
            # Construct absolute upload path within instance folder
            upload_folder_rel = current_app.config.get('UPLOAD_FOLDER_RELATIVE', 'uploads/templates') # Get from config
            upload_folder_abs = os.path.join(current_app.instance_path, upload_folder_rel)
            os.makedirs(upload_folder_abs, exist_ok=True) # Create if not exists

            original_filename = secure_filename(file.filename)
            _, ext = os.path.splitext(original_filename)
            unique_filename = str(uuid.uuid4()) + ext # Create unique filename
            save_path = os.path.join(upload_folder_abs, unique_filename)

            file.save(save_path) # Save the physical file
            logging.info(f"Uploaded template for new scenario saved to: {save_path}")

            # Create ReportTemplate database record
            template_record = ReportTemplate(
                original_filename=original_filename,
                file_path=save_path # Store absolute path
            )
            db.session.add(template_record)
            db.session.flush() # To get the template_record.template_id

        except Exception as e:
            db.session.rollback()
            flash(f'Error uploading template file: {e}', 'danger')
            logging.error(f"Error uploading template for new scenario: {e}", exc_info=True)
            return render_template('scenarios/create_scenario_form.html', title='Create New Scenario', form=form)


        # --- 2. Create Scenario Record ---
        try:
            new_scenario = Scenario(
                name=form.name.data,
                megara_url=form.megara_url.data,
                schedule_cron=form.schedule_cron.data,
                created_by_user_id=current_user.user_id,
                report_template_id=template_record.template_id # Link to the uploaded template
                # Other fields like enable_anomalies will default or be set later
            )
            db.session.add(new_scenario)
            db.session.commit() # Commit both scenario and template
            flash(f'Scenario "{new_scenario.name}" and template uploaded successfully!', 'success')

            # --- 3. Redirect to Guidance Page ---
            return redirect(url_for('scenarios.start_recording_guidance',
                                    scenario_id=new_scenario.scenario_id))

        except Exception as e:
            db.session.rollback() # Rollback scenario and template creation
            flash(f'Error creating scenario: {e}', 'danger')
            logging.error(f"Error creating new scenario: {e}", exc_info=True)
            # Optionally delete the uploaded file if scenario creation fails here
            if save_path and os.path.exists(save_path):
                try: os.remove(save_path)
                except: logging.error(f"Could not remove orphaned template file: {save_path}")

    # --- Handle GET Request ---
    return render_template('scenarios/create_scenario_form.html', title='Create New Scenario', form=form)

# --- NEW: Recording Guidance Route ---
@bp.route('/<int:scenario_id>/record-guidance')
@login_required
def start_recording_guidance(scenario_id):
    scenario = db.session.get(Scenario, scenario_id) # Use db.session.get for simplicity
    if not scenario or scenario.created_by_user_id != current_user.user_id:
        flash("Scenario not found or permission denied.", "danger")
        return redirect(url_for('scenarios.list_scenarios'))

    return render_template(
        'scenarios/start_recording_guidance.html',
        title="Start Recording Steps",
        scenario=scenario
    )
@bp.route('/<int:scenario_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_scenario(scenario_id):
    scenario = Scenario.query.get_or_404(scenario_id)
    if scenario.created_by_user_id != current_user.user_id: # Check ownership
        flash('Permission denied.', 'danger'); return redirect(url_for('scenarios.list_scenarios'))

    # Pass scenario object to form only if needed for validation, not for pre-population here
    form = EditScenarioForm()

    if form.validate_on_submit(): # Process POST request
        # --- Handle File Upload ---
        file = form.template_file.data
        new_template_id = scenario.report_template_id # Keep existing template by default

        if file: # Check if a file was actually uploaded
            try:
                # Construct absolute upload path within instance folder
                upload_folder_rel = current_app.config['UPLOAD_FOLDER_RELATIVE']
                # app.instance_path is the absolute path to the instance folder
                upload_folder_abs = os.path.join(current_app.instance_path, upload_folder_rel)
                # Create directory if it doesn't exist
                os.makedirs(upload_folder_abs, exist_ok=True)

                # Sanitize and create unique filename
                original_filename = secure_filename(file.filename)
                # Use UUID to ensure uniqueness, keep original extension
                _, ext = os.path.splitext(original_filename)
                unique_filename = str(uuid.uuid4()) + ext
                save_path = os.path.join(upload_folder_abs, unique_filename)

                # Save the file
                file.save(save_path)
                logging.info(f"Uploaded template saved to: {save_path}")

                # --- Create new ReportTemplate record ---
                # Decide: Delete old template record/file? For simplicity, let's just create a new one.
                # Old template records/files might become orphaned if not cleaned up.
                new_template = ReportTemplate(
                    original_filename=original_filename,
                    file_path=save_path # Store the absolute save path
                )
                db.session.add(new_template)
                db.session.flush() # Get the ID of the new template
                new_template_id = new_template.template_id # Use the new template ID
                flash(f'New template "{original_filename}" uploaded successfully.', 'info')

            except Exception as e:
                 db.session.rollback() # Rollback template creation if save fails
                 flash(f'Error uploading template file: {e}', 'danger')
                 logging.error(f"Error uploading template file: {e}", exc_info=True)
                 # Redirect back to edit form to show error
                 return render_template('scenarios/edit_form.html', title=f'Edit Scenario: {scenario.name}', form=form, scenario=scenario)
        # --- End File Upload Handling ---

        # --- Update Scenario fields ---
        try:
            scenario.name = form.name.data
            scenario.megara_url = form.megara_url.data
            scenario.schedule_cron = form.schedule_cron.data
            scenario.enable_anomalies = form.enable_anomalies.data
            scenario.email_recipients = form.email_recipients.data
            scenario.upload_path = form.upload_path.data
            scenario.report_template_id = new_template_id # Assign new or existing template ID

            db.session.commit() # Commit all scenario changes
            flash(f'Scenario "{scenario.name}" updated successfully!', 'success')
            return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating scenario details: {e}', 'danger')
            logging.error(f"Error updating scenario {scenario_id}: {e}", exc_info=True)


    elif request.method == 'GET': # Pre-populate form on GET request
        form.name.data = scenario.name
        form.megara_url.data = scenario.megara_url
        form.schedule_cron.data = scenario.schedule_cron
        form.enable_anomalies.data = scenario.enable_anomalies
        form.email_recipients.data = scenario.email_recipients
        form.upload_path.data = scenario.upload_path
        # Don't pre-populate file field

    # Pass current template info for display
    current_template_filename = scenario.template.original_filename if scenario.template else None
    return render_template('scenarios/edit_form.html', title=f'Edit Scenario: {scenario.name}',
                           form=form, scenario=scenario, current_template=current_template_filename)
       

@bp.route('/<int:scenario_id>/delete', methods=['POST']) # Use POST for deletion
@login_required
def delete_scenario(scenario_id):
    """Handles deletion of a scenario."""
    scenario = Scenario.query.get_or_404(scenario_id)

    # Check ownership
    if scenario.created_by_user_id != current_user.user_id:
        flash('You do not have permission to delete this scenario.', 'danger')
        return redirect(url_for('scenarios.list_scenarios'))

    try:
        scenario_name = scenario.name # Get name before deleting
        # Deletion will cascade to steps, mappings, rules, logs due to cascade options in models
        db.session.delete(scenario)
        db.session.commit()
        flash(f'Scenario "{scenario_name}" and all associated data deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting scenario: {e}', 'danger')
        print(f"Error deleting scenario {scenario_id}: {e}") # Log error

    return redirect(url_for('scenarios.list_scenarios'))


# --- NEW ROUTE: Add Processing Rule ---
@bp.route('/<int:scenario_id>/rules/add', methods=['POST'])
@login_required
def add_rule(scenario_id):
    """Handles adding a new processing rule via POST request."""
    scenario = Scenario.query.get_or_404(scenario_id)
    if scenario.created_by_user_id != current_user.user_id: # Check ownership
        flash('Permission denied.', 'danger'); return redirect(url_for('scenarios.list_scenarios'))

    form = ProcessingRuleForm() # Create form instance to validate POST data

    if form.validate_on_submit():
        try:
            # Validate operator requires value (unless IS_BLANK/IS_NOT_BLANK)
            operator_enum = RuleOperatorEnum[form.operator.data]
            if operator_enum not in [RuleOperatorEnum.IS_BLANK, RuleOperatorEnum.IS_NOT_BLANK] and not form.condition_value.data:
                 flash('Condition value is required for the selected operator.', 'warning')
                 # Redirect back to view which will show the flash message
                 return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))

            new_rule = ProcessingRule(
                scenario_id=scenario.scenario_id,
                condition_column=form.condition_column.data,
                operator=operator_enum, # Store Enum member
                condition_value=form.condition_value.data,
                action_column=form.action_column.data,
                action_value=form.action_value.data
            )
            db.session.add(new_rule)
            db.session.commit()
            flash('Processing rule added successfully!', 'success')
        except KeyError:
             db.session.rollback()
             flash('Invalid operator selected.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding rule: {e}', 'danger')
            logging.error(f"Error adding rule for scenario {scenario_id}: {e}", exc_info=True)
    else:
        # Collect validation errors to show user
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in field '{getattr(form, field).label.text}': {error}", 'danger')

    # Redirect back to the scenario view page regardless of outcome
    return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))


# --- NEW ROUTE: Delete Processing Rule ---
@bp.route('/<int:scenario_id>/rules/<int:rule_id>/delete', methods=['POST'])
@login_required
def delete_rule(scenario_id, rule_id):
    """Handles deleting an existing processing rule."""
    scenario = Scenario.query.get_or_404(scenario_id)
    rule = ProcessingRule.query.get_or_404(rule_id)

    # Check ownership and that rule belongs to the scenario
    if scenario.created_by_user_id != current_user.user_id or rule.scenario_id != scenario.scenario_id:
        flash('Permission denied or rule does not belong to this scenario.', 'danger')
        return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))

    try:
        db.session.delete(rule)
        db.session.commit()
        flash('Processing rule deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting rule: {e}', 'danger')
        logging.error(f"Error deleting rule {rule_id}: {e}", exc_info=True)

    # Redirect back to the scenario view page
    return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))


# --- NEW ROUTE: Add Column Mapping ---
@bp.route('/<int:scenario_id>/mappings/add', methods=['POST'])
@login_required
def add_mapping(scenario_id):
    """Handles adding a new column mapping via POST request."""
    scenario = Scenario.query.get_or_404(scenario_id)
    if scenario.created_by_user_id != current_user.user_id: # Check ownership
        flash('Permission denied.', 'danger'); return redirect(url_for('scenarios.list_scenarios'))

    form = ColumnMappingForm() # Create form instance to validate POST data

    if form.validate_on_submit():
        try:
            # Check if mapping for this scraped header already exists
            existing = ColumnMapping.query.filter_by(
                scenario_id=scenario.scenario_id,
                scraped_header=form.scraped_header.data
            ).first()
            if existing:
                flash(f"A mapping for scraped header '{form.scraped_header.data}' already exists.", 'warning')
            else:
                new_mapping = ColumnMapping(
                    scenario_id=scenario.scenario_id,
                    scraped_header=form.scraped_header.data,
                    template_header=form.template_header.data
                )
                db.session.add(new_mapping)
                db.session.commit()
                flash('Column mapping added successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding mapping: {e}', 'danger')
            logging.error(f"Error adding mapping for scenario {scenario_id}: {e}", exc_info=True)
    else:
        # Collect validation errors to show user
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in field '{getattr(form, field).label.text}': {error}", 'danger')

    # Redirect back to the scenario view page regardless of outcome
    return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))


# --- NEW ROUTE: Delete Column Mapping ---
@bp.route('/<int:scenario_id>/mappings/<int:mapping_id>/delete', methods=['POST'])
@login_required
def delete_mapping(scenario_id, mapping_id):
    """Handles deleting an existing column mapping."""
    scenario = Scenario.query.get_or_404(scenario_id)
    mapping = ColumnMapping.query.get_or_404(mapping_id)

    # Check ownership and that mapping belongs to the scenario
    if scenario.created_by_user_id != current_user.user_id or mapping.scenario_id != scenario.scenario_id:
        flash('Permission denied or mapping does not belong to this scenario.', 'danger')
        return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))

    try:
        db.session.delete(mapping)
        db.session.commit()
        flash('Column mapping deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting mapping: {e}', 'danger')
        logging.error(f"Error deleting mapping {mapping_id}: {e}", exc_info=True)

    # Redirect back to the scenario view page
    return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))


# --- NEW ROUTE: Add Scenario Step ---

@bp.route('/<int:scenario_id>/steps/add', methods=['GET', 'POST'])
@login_required
def add_step(scenario_id):
    """Handles adding a new step to a scenario."""
    scenario = Scenario.query.get_or_404(scenario_id)
    if scenario.created_by_user_id != current_user.user_id: # Check ownership
        flash('Permission denied.', 'danger'); return redirect(url_for('scenarios.list_scenarios'))

    form = ScenarioStepForm()

    # --- Handle POST Request ---
    if form.validate_on_submit():
        try:
            # Determine the next sequence order reliably
            last_order = db.session.query(func.max(ScenarioStep.sequence_order)).filter_by(scenario_id=scenario.scenario_id).scalar()
            next_order = (last_order or 0) + 1 # Start at 1 if no steps exist

            new_step = ScenarioStep(
                scenario_id=scenario.scenario_id,
                # Use the calculated next_order, ignore form input for sequence on create
                sequence_order=next_order,
                action_type=ActionTypeEnum[form.action_type.data], # Get Enum member
                selector=form.selector.data,
                value=form.value.data
            )
            db.session.add(new_step)
            db.session.commit()
            flash(f'New step (Order {next_order}) added successfully!', 'success')
            return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))
        except KeyError:
             # This happens if form.action_type.data is not a valid ActionTypeEnum key
             db.session.rollback()
             flash('Invalid action type selected.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding step: {e}', 'danger')
            logging.error(f"Error adding step for scenario {scenario_id}: {e}", exc_info=True)
            # Fall through to render form again with errors

    # --- Handle GET Request (or failed POST validation) ---
    # Calculate default sequence order for display on GET
    if request.method == 'GET':
        last_order = db.session.query(func.max(ScenarioStep.sequence_order)).filter_by(scenario_id=scenario.scenario_id).scalar()
        next_order = (last_order or 0) + 1
        form.sequence_order.data = next_order # Pre-populate for display

    # Render the form template
    return render_template('scenarios/step_form.html',
                           title=f'Add Step to Scenario: {scenario.name}',
                           form=form,
                           scenario=scenario,
                           # Make sequence readonly on add form
                           is_edit=False,
                           form_action=url_for('scenarios.add_step', scenario_id=scenario.scenario_id))

# --- NEW ROUTE: Edit Scenario Step ---
@bp.route('/<int:scenario_id>/steps/<int:step_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_step(scenario_id, step_id):
    """Handles editing an existing scenario step."""
    scenario = Scenario.query.get_or_404(scenario_id)
    step = ScenarioStep.query.get_or_404(step_id)

    # Check ownership and that step belongs to the scenario
    if scenario.created_by_user_id != current_user.user_id or step.scenario_id != scenario.scenario_id:
        flash('Permission denied or step does not belong to this scenario.', 'danger')
        return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))

    # Instantiate form, pre-populating with step data for GET requests
    form = ScenarioStepForm(obj=step)

    # --- Handle POST Request ---
    if form.validate_on_submit():
        try:
            # Check if sequence order is changing (potential future conflict)
            original_order = step.sequence_order
            new_order = form.sequence_order.data
            if original_order != new_order:
                # TODO: Implement robust re-ordering logic here.
                # This would involve querying for conflicts and shifting other steps.
                # For now, we just log a warning if changed, but allow it.
                logging.warning(f"Sequence order changed for step {step_id} from {original_order} to {new_order}. Re-ordering logic not implemented.")
                flash("Warning: Changing sequence order manually may lead to conflicts. Full re-ordering feature not yet implemented.", "warning")


            # Update the existing step object's attributes
            step.sequence_order = new_order
            step.action_type = ActionTypeEnum[form.action_type.data] # Get Enum member
            step.selector = form.selector.data
            step.value = form.value.data

            db.session.commit() # Commit the changes to the existing step
            flash('Step updated successfully!', 'success')
            return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))
        except KeyError:
            db.session.rollback()
            flash('Invalid action type selected.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating step: {e}', 'danger')
            logging.error(f"Error updating step {step_id}: {e}", exc_info=True)
            # Fall through to render form again with errors

    # --- Handle GET Request (or failed POST validation) ---
    # Pre-population is handled by obj=step when form is instantiated above GET/POST check
    # OR: If not using obj=, you would manually set here:
    # if request.method == 'GET':
    #     form.sequence_order.data = step.sequence_order
    #     form.action_type.data = step.action_type.name # Use enum name for SelectField
    #     form.selector.data = step.selector
    #     form.value.data = step.value

    # Render the form template
    return render_template('scenarios/step_form.html',
                           title=f'Edit Step {step.sequence_order} in Scenario: {scenario.name}',
                           form=form,
                           scenario=scenario,
                           step=step, # Pass step for context
                           is_edit=True, # Flag for template logic
                           form_action=url_for('scenarios.edit_step', scenario_id=scenario.scenario_id, step_id=step.step_id))



# --- Route for delete_step to be added next ---
# --- NEW ROUTE: Delete Scenario Step ---
@bp.route('/<int:scenario_id>/steps/<int:step_id>/delete', methods=['POST']) # Only allow POST for deletion
@login_required
def delete_step(scenario_id, step_id):
    """Handles deleting an existing scenario step."""
    scenario = Scenario.query.get_or_404(scenario_id)
    step = ScenarioStep.query.get_or_404(step_id)

    # Check ownership and that step belongs to the scenario
    if scenario.created_by_user_id != current_user.user_id or step.scenario_id != scenario.scenario_id:
        flash('Permission denied or step does not belong to this scenario.', 'danger')
        return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))

    try:
        step_order = step.sequence_order # Get order before deleting for message
        db.session.delete(step)
        # TODO: Consider logic to re-sequence remaining steps after deletion?
        # For now, just delete the specific step.
        db.session.commit()
        flash(f'Step {step_order} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting step: {e}', 'danger')
        print(f"Error deleting step {step_id}: {e}")

    # Redirect back to the scenario view page
    return redirect(url_for('scenarios.view_scenario', scenario_id=scenario.scenario_id))

# --- PROTECTED API ROUTE: Add Step ---
@bp.route('/api/scenarios/<int:scenario_id>/steps', methods=['POST'])
# @login_required # Remove this
@token_required # Use the JWT token decorator
def api_add_step(scenario_id):
    """API endpoint to add a new step using JWT authentication."""
    # Access user from g
    user = g.current_user
    if not user: return jsonify({"success": False, "message": "Authentication failed"}), 401

    scenario = Scenario.query.get_or_404(scenario_id)
    # Check ownership using user from token
    if scenario.created_by_user_id != user.user_id:
        return jsonify({"success": False, "message": "Permission denied"}), 403

    data = request.get_json()
    # ... (Keep data validation as before) ...
    if not data or not data.get('action_type') or not data.get('selector'):
         return jsonify({"success": False, "message": "Missing action_type or selector"}), 400
    action_str = data.get('action_type')
    selector = data.get('selector')
    value = data.get('value')
    try: action_enum = ActionTypeEnum[action_str]
    except KeyError: return jsonify({"success": False, "message": f"Invalid action_type: {action_str}"}), 400

    try:
        # ... (Keep logic for calculating next_order) ...
        last_order = db.session.query(func.max(ScenarioStep.sequence_order)).filter_by(scenario_id=scenario.scenario_id).scalar()
        next_order = (last_order or 0) + 1
        new_step = ScenarioStep(
            scenario_id=scenario.scenario_id,
            sequence_order=next_order,
            action_type=action_enum,
            selector=selector,
            value=value
        )
        db.session.add(new_step)
        db.session.commit()
        logging.info(f"API: Added step {next_order} to scenario {scenario_id} for user {user.user_id}")
        return jsonify({ # Return JSON success
            "success": True,
            "message": "Step added successfully",
            "step": {
                "step_id": new_step.step_id,
                "sequence_order": new_step.sequence_order,
                "action_type": new_step.action_type.name,
                "selector": new_step.selector,
                "value": new_step.value
            }
        }), 201 # HTTP 201 Created status
    except Exception as e:
        db.session.rollback()
        logging.error(f"API Error adding step for scenario {scenario_id}: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Internal server error: {e}"}), 500

# --- PROTECTED API ROUTE: List Scenarios ---
@bp.route('/api/scenarios/list', methods=['GET'])
# @login_required # Remove this (or ensure it was added back)
@token_required # Use the JWT token decorator
def api_list_scenarios():
    """API endpoint to list scenarios owned by the JWT-authenticated user."""
    # Access user from g instead of current_user
    user = g.current_user
    if not user: # Should not happen if decorator works, but good practice
        return jsonify({"success": False, "message": "Authentication failed"}), 401
    try:
        scenarios = Scenario.query.filter_by(created_by_user_id=user.user_id).order_by(Scenario.name).all()
        output = [{"id": scenario.scenario_id, "name": scenario.name} for scenario in scenarios]
        return jsonify({"success": True, "scenarios": output})
    except Exception as e:
        logging.error(f"API Error listing scenarios for user {user.user_id}: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Internal server error: {e}"}), 500
