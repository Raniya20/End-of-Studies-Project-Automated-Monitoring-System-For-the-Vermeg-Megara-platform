# app/scenarios/forms.py
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired # Import FileField and validators
from wtforms import StringField, TextAreaField, BooleanField, SubmitField, SelectField, IntegerField
from wtforms.validators import DataRequired, URL, Optional, Length, NumberRange, Regexp # Use Optional for fields not required on edit
# Import the Enum for the dropdown choices
from app.models import ActionTypeEnum, RuleOperatorEnum

class EditScenarioForm(FlaskForm):
    name = StringField('Scenario Name', validators=[DataRequired()])
    megara_url = StringField('Megara Target URL', validators=[DataRequired(), URL(message='Please enter a valid URL.',require_tld=False)])
    schedule_cron = StringField('Schedule (Cron Format)', validators=[DataRequired()],
                                description='Use standard cron format (minute hour day-of-month month day-of-week)')
    email_recipients = TextAreaField('Email Recipients (comma-separated)', validators=[Optional()],
                                     description='Enter email addresses separated by commas.')
    upload_path = StringField('Report Upload Path', validators=[Optional()],
                              description='Server path where reports should be uploaded (optional).')
    template_file = FileField(
        'Upload New Template (.xlsx)',
        validators=[
            Optional(), # Make upload optional during edit
            FileAllowed(['xlsx'], 'Excel files (.xlsx) only!')
        ],
        description="Optional: Upload a new template to replace the existing one."
    )
    # --- END NEW FILE FIELD ---
    submit = SubmitField('Update Scenario')

    custom_report_base_name = StringField(
        'Custom Report Base Name (Optional)',
        validators=[
            Optional(),
            Length(max=150),
            Regexp(r'^[a-zA-Z0-9_\s-]+$',
                   message="Report name can only contain letters, numbers, spaces, underscores, and hyphens.")
        ],
        description="E.g., 'Daily_Price_Check'. A timestamp will be appended automatically."
    )
    submit = SubmitField('Update Scenario')


class ScenarioStepForm(FlaskForm):
    """Form for adding or editing a single scenario step."""
    # We might set sequence_order automatically or allow editing later
    sequence_order = IntegerField(
        'Sequence Order',
        validators=[DataRequired(), NumberRange(min=1)],
        description="Order in which this step runs (e.g., 1, 2, 3...)."
        # Render as readonly or hidden if setting automatically on create?
    )
    action_type = SelectField(
        'Action Type',
        choices=[(action.name, action.value) for action in ActionTypeEnum], # Populate choices from Enum
        validators=[DataRequired()]
    )
    selector = TextAreaField(
        'Selector (CSS or XPath)',
        validators=[DataRequired(message="Selector is required for most actions.")], # Required for most actions
        description="e.g., #element-id, .css-class, //xpath/expression",
        render_kw={"rows": 2}
    )
    value = TextAreaField(
        'Value / Label / URL / State:Timeout',
        validators=[Optional()], # Value is often optional (e.g., for CLICK)
        description="For TYPE: text to type. For SELECT: option value. For NAVIGATE: URL. For EXTRACT: label. For WAIT: state[:timeout_ms]. Use __TODAY__, __YESTERDAY__ for dates.",
        render_kw={"rows": 2}
    )
    submit = SubmitField('Save Step')

    # Add custom validation later if needed, e.g., require value for certain action types

    
class ColumnMappingForm(FlaskForm):
    """Form for adding a column mapping."""
    scraped_header = StringField(
        'Scraped Header Name',
        validators=[DataRequired()],
        description="Exact header name found in the scraped data table."
    )
    template_header = SelectField(
        'Template Header Name',
        choices=[], # Initialize with empty choices, will be populated in the route
        validators=[DataRequired(message="Please select a template header.")],
        description="Select the header from your uploaded Excel template."
    )
    submit = SubmitField('Add Mapping')

class ProcessingRuleForm(FlaskForm):
    """Form for adding or editing a processing rule."""
    condition_column = StringField(
        'IF Scraped Column',
        validators=[DataRequired()],
        description="Header name from the scraped data table to check."
    )
    operator = SelectField(
        'Operator',
        choices=[(op.name, op.value) for op in RuleOperatorEnum], # Populate from Enum
        validators=[DataRequired()]
    )
    condition_value = StringField(
        'Condition Value',
        validators=[Optional()], # Optional for IS_BLANK/IS_NOT_BLANK
        description="Value to compare against (leave blank for IS_BLANK/IS_NOT_BLANK)."
    )
    action_column = StringField(
        'THEN Set Template Column',
        validators=[DataRequired()],
        description="Header name in your template whose value will be set."
    )
    action_value = TextAreaField( # Use TextArea for potentially longer action values
        'To Value',
        validators=[Optional()], # Allow setting blank value
        description="The value to set in the target template column if condition is met.",
        render_kw={"rows": 2}
    )
    submit = SubmitField('Add Rule')

class CreateScenarioForm(FlaskForm):
    """Form for initial scenario creation including template upload."""
    name = StringField(
        'Scenario Name',
        validators=[DataRequired(), Length(min=3, max=255)],
        description="A descriptive name for this monitoring scenario."
    )
    megara_url = StringField(
        'Application URL to Monitor',
        validators=[DataRequired(), URL(message='Please enter a valid URL.', require_tld=False)],
        description="The starting URL of the web application you want to monitor."
    )
    template_file = FileField(
        'Upload Report Template (.xlsx)',
        validators=[
            FileRequired(message="An Excel report template is required."), # Make it required
            FileAllowed(['xlsx'], 'Excel files (.xlsx) only!')
        ],
        description="The .xlsx template file that will be populated with data."
    )
    schedule_cron = StringField(
        'Initial Schedule (Cron Format)',
        validators=[DataRequired()],
        default='0 8 * * *', # Example: Daily at 8 AM
        description="E.g., '0 8 * * *' for daily at 8 AM. You can refine this later."
    )
    submit = SubmitField('Save & Proceed to Record Steps')
    custom_report_base_name = StringField(
        'Custom Report Base Name (Optional)',
        validators=[
            Optional(),
            Length(max=150),
            Regexp(r'^[a-zA-Z0-9_\s-]+$',
                   message="Report name can only contain letters, numbers, spaces, underscores, and hyphens.")
        ],
        description="E.g., 'Daily_Price_Check'. A timestamp will be appended automatically."
    )
    submit = SubmitField('Save Scenario & Proceed to Record Steps')