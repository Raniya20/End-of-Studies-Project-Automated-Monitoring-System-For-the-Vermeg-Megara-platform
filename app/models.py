# app/models.py
from app import db # Import the db instance from app's __init__
from datetime import datetime
import enum
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin # Import UserMixin

# --- Enums ---
# Define allowed values for specific fields

class ActionTypeEnum(enum.Enum):
    CLICK = 'CLICK'
    TYPE = 'TYPE'
    SELECT = 'SELECT'
    EXTRACT_TABLE = 'EXTRACT_TABLE'
    EXTRACT_ELEMENT = 'EXTRACT_ELEMENT'
    NAVIGATE = 'NAVIGATE'
    WAIT_FOR_SELECTOR = 'WAIT_FOR_SELECTOR'
    WAIT_FOR_TIMEOUT = 'WAIT_FOR_TIMEOUT'

class ExecutionStatusEnum(enum.Enum):
    PENDING = 'PENDING'
    RUNNING = 'RUNNING'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'

class RuleOperatorEnum(enum.Enum):
    EQUALS = 'EQUALS'
    NOT_EQUALS = 'NOT_EQUALS'
    CONTAINS = 'CONTAINS'
    GREATER_THAN = 'GREATER_THAN'
    LESS_THAN = 'LESS_THAN'
    IS_BLANK = 'IS_BLANK'
    IS_NOT_BLANK = 'IS_NOT_BLANK'

# --- Tables ---

# Consultant model inherits from UserMixin for Flask-Login integration
class Consultant(UserMixin, db.Model):
    __tablename__ = 'consultant'
    user_id = db.Column(db.Integer, primary_key=True) # SERIAL handled by DB
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False) # Store hash, not password
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationship backref: allows accessing scenarios created by a user via consultant.scenarios
    scenarios = db.relationship('Scenario', backref='creator', lazy='dynamic')

    # Flask-Login integration: Use user_id as the ID
    def get_id(self):
        return str(self.user_id)

    # Password Hashing methods
    def set_password(self, password):
        """Hashes the password and stores it."""
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256:600000') # Use strong hashing

    def check_password(self, password):
        """Checks if the provided password matches the stored hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<Consultant {self.username}>'


class Scenario(db.Model):
    __tablename__ = 'scenario'
    scenario_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    megara_url = db.Column(db.Text, nullable=False)
    schedule_cron = db.Column(db.String(100), nullable=False) # Cron format string
    enable_anomalies = db.Column(db.Boolean, nullable=False, default=False)
    email_recipients = db.Column(db.Text, nullable=True) # Store as JSON string or comma-separated
    upload_path = db.Column(db.Text, nullable=True) # Path for report uploads
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=datetime.utcnow)

    # Foreign Keys
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('consultant.user_id'), nullable=False, index=True)
    report_template_id = db.Column(db.Integer, db.ForeignKey('report_template.template_id'), nullable=True, index=True)

    # Relationships
    # Cascading deletes ensure related items are removed when a scenario is deleted
    steps = db.relationship('ScenarioStep', backref='scenario', lazy='dynamic', cascade='all, delete-orphan', order_by='ScenarioStep.sequence_order')
    column_mappings = db.relationship('ColumnMapping', backref='scenario', lazy='dynamic', cascade='all, delete-orphan')
    processing_rules = db.relationship('ProcessingRule', backref='scenario', lazy='dynamic', cascade='all, delete-orphan')
    execution_logs = db.relationship('ExecutionLog', backref='scenario', lazy='dynamic', cascade='all, delete-orphan', order_by='ExecutionLog.start_time.desc()')
    template = db.relationship('ReportTemplate', backref=db.backref('scenarios', lazy='dynamic')) # One template can be used by many scenarios

    def __repr__(self):
        return f'<Scenario {self.scenario_id}: {self.name}>'


class ReportTemplate(db.Model):
    __tablename__ = 'report_template'
    template_id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(255), nullable=False)
    # Consider storing uploads outside web root for security
    file_path = db.Column(db.Text, nullable=False, unique=True) # Path on server where template is stored
    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<ReportTemplate {self.template_id}: {self.original_filename}>'


class ScenarioStep(db.Model):
    __tablename__ = 'scenario_step'
    step_id = db.Column(db.Integer, primary_key=True)
    sequence_order = db.Column(db.Integer, nullable=False)
    action_type = db.Column(db.Enum(ActionTypeEnum), nullable=False) # Use the Enum
    selector = db.Column(db.Text, nullable=False) # CSS or XPath
    value = db.Column(db.Text, nullable=True) # Value for TYPE/SELECT, URL for NAVIGATE, label for EXTRACT, state/timeout for WAIT
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Foreign Key
    scenario_id = db.Column(db.Integer, db.ForeignKey('scenario.scenario_id'), nullable=False, index=True)

    def __repr__(self):
        return f'<ScenarioStep {self.step_id} (Scen {self.scenario_id}) Ord {self.sequence_order} Act {self.action_type.name}>'


class ColumnMapping(db.Model):
    __tablename__ = 'column_mapping'
    mapping_id = db.Column(db.Integer, primary_key=True)
    scraped_header = db.Column(db.String(255), nullable=False)
    template_header = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Foreign Key
    scenario_id = db.Column(db.Integer, db.ForeignKey('scenario.scenario_id'), nullable=False, index=True)

    # Ensure a unique mapping per scenario for a given scraped header
    __table_args__ = (db.UniqueConstraint('scenario_id', 'scraped_header', name='_scenario_scraped_header_uc'),)

    def __repr__(self):
        return f'<ColumnMapping {self.mapping_id} (Scen {self.scenario_id}): {self.scraped_header} -> {self.template_header}>'


class ProcessingRule(db.Model):
    __tablename__ = 'processing_rule'
    rule_id = db.Column(db.Integer, primary_key=True)
    condition_column = db.Column(db.String(255), nullable=False) # Scraped Column Name
    operator = db.Column(db.Enum(RuleOperatorEnum), nullable=False) # Use the Enum
    condition_value = db.Column(db.Text, nullable=True) # Value to compare against
    action_column = db.Column(db.String(255), nullable=False) # Template Column Name to set
    action_value = db.Column(db.Text, nullable=True) # Value to set in the template column
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Foreign Key
    scenario_id = db.Column(db.Integer, db.ForeignKey('scenario.scenario_id'), nullable=False, index=True)

    def __repr__(self):
        return f'<ProcessingRule {self.rule_id} (Scen {self.scenario_id})>'


class ExecutionLog(db.Model):
    __tablename__ = 'execution_log'
    log_id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    end_time = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.Enum(ExecutionStatusEnum), nullable=False, default=ExecutionStatusEnum.PENDING, index=True) # Use the Enum
    report_file_path = db.Column(db.Text, nullable=True) # Path to the generated main report
    anomaly_report_path = db.Column(db.Text, nullable=True) # Path to the generated anomaly report
    log_message = db.Column(db.Text, nullable=True) # Store errors or summary info

    # Foreign Key
    scenario_id = db.Column(db.Integer, db.ForeignKey('scenario.scenario_id'), nullable=False, index=True)

    # Relationship (One log has many results)
    results = db.relationship('MonitoringResult', backref='log', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ExecutionLog {self.log_id} (Scen {self.scenario_id}) Status {self.status.name}>'


class MonitoringResult(db.Model):
    __tablename__ = 'monitoring_result'
    # Using BigInteger for potentially high volume of results over time
    result_id = db.Column(db.BigInteger, primary_key=True)
    metric_name = db.Column(db.String(255), nullable=False, index=True) # e.g., 'pending_count', 'tablelabel_rowidx_colname'
    # Using Text for flexibility, assumes conversion/parsing happens during analysis/visualization
    metric_value = db.Column(db.Text, nullable=True)
    is_anomaly = db.Column(db.Boolean, nullable=False, default=False, index=True) # Flag from anomaly detection
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True) # Timestamp for the specific metric

    # Foreign Key
    log_id = db.Column(db.Integer, db.ForeignKey('execution_log.log_id'), nullable=False, index=True)

    def __repr__(self):
        return f'<MonitoringResult {self.result_id} (Log {self.log_id}) Metric {self.metric_name} Anomaly: {self.is_anomaly}>'