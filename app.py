from flask import Flask, send_file, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import csv
import calendar
from io import StringIO, BytesIO
import pandas as pd
from werkzeug.utils import secure_filename
from io import BytesIO

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'  # Change this in production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///timesheet.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'))
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    standard_hours = db.Column(db.Integer, default=40)  # Standard weekly hours before overtime
    users = db.relationship('User', backref='company', lazy=True)
    employees = db.relationship('Employee', backref='company', lazy=True)
    job_titles = db.relationship('JobTitle', backref='company', lazy=True)
    locations = db.relationship('Location', backref='company', lazy=True)
    groups = db.relationship('EmployeeGroup', backref='company', lazy=True)

class JobTitle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    employees = db.relationship('Employee', backref='job_title', lazy=True)
    
class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    employees = db.relationship('Employee', backref='location', lazy=True)

# Update your Employee model to include the new fields and methods

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    hourly_rate = db.Column(db.Float, nullable=False)
    overtime_rate = db.Column(db.Float, nullable=False)
    weekend_rate = db.Column(db.Float, nullable=False)
    additional_info = db.Column(db.Text)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    job_title_id = db.Column(db.Integer, db.ForeignKey('job_title.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    rate_function_id = db.Column(db.Integer, db.ForeignKey('rate_function.id'))
    is_sunday_worker = db.Column(db.Boolean, default=False)  # New field for Sunday workers
    is_holiday_worker = db.Column(db.Boolean, default=False)  # New field for holiday workers
    timesheets = db.relationship('Timesheet', backref='employee', lazy=True)
    is_active = db.Column(db.Boolean, default=True)
    
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def get_effective_overtime_rate(self):
        """Get the effective overtime rate based on custom function or default rate"""
        if self.rate_function_id:
            rate_function = RateFunction.query.get(self.rate_function_id)
            if rate_function:
                return rate_function.calculate_weekday_overtime(self.hourly_rate, self.overtime_rate)
        return self.overtime_rate
    
    def get_effective_weekend_rate(self):
        """Get the effective weekend rate based on custom function or default rate"""
        if self.rate_function_id:
            rate_function = RateFunction.query.get(self.rate_function_id)
            if rate_function:
                return rate_function.calculate_weekend_rate(self.hourly_rate, self.weekend_rate)
        return self.weekend_rate
    
# Update to Timesheet model class in app.py

class Timesheet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    clock_in = db.Column(db.DateTime, nullable=False)
    clock_out = db.Column(db.DateTime)
    is_public_holiday = db.Column(db.Boolean, default=False)  # Field to mark as public holiday
    is_night_shift = db.Column(db.Boolean, default=False)  # Field to mark as night shift
    
    def calculate_hours(self):
        if self.clock_out:
            duration = self.clock_out - self.clock_in
            return round(duration.total_seconds() / 3600, 2)  # Hours with 2 decimal places
        return 0
    
    def is_active(self):
        return self.clock_out is None
    
    def is_weekend(self):
        """Check if this timesheet falls on a weekend"""
        return self.clock_in.weekday() >= 5  # 5 = Saturday, 6 = Sunday
    
    def is_sunday(self):
        """Check if this timesheet is specifically on a Sunday"""
        return self.clock_in.weekday() == 6
    
    def is_saturday(self):
        """Check if this timesheet is specifically on a Saturday"""
        return self.clock_in.weekday() == 5
    
    def is_night_shift(self):
        """Check if this timesheet falls within night shift hours (18:00-06:00)"""
        # Clock-in time is after 18:00 (6pm)
        evening_start = self.clock_in.hour >= 18
        
        # Clock-in time is before 6:00 (6am)
        early_morning = self.clock_in.hour < 6
        
        # If clock-out spans across night shift hours
        spans_night_hours = False
        if self.clock_out:
            # Check if clock_out is after clock_in (same day)
            if self.clock_out.date() == self.clock_in.date():
                # Evening shift that continues after 6pm
                if self.clock_in.hour < 18 and self.clock_out.hour >= 18:
                    spans_night_hours = True
            else:
                # Shift that continues past midnight
                spans_night_hours = True
        
        return evening_start or early_morning or spans_night_hours or self.is_night_shift
    
    def calculate_night_shift_hours(self):
        """Calculate the number of hours worked during night shift (18:00-06:00)"""
        if not self.clock_out:
            return 0
            
        # Total shift duration in hours
        total_hours = self.calculate_hours()
        
        # If not spanning night shift hours at all, return 0
        if not self.is_night_shift():
            return 0
        
        # Clock-in and clock-out datetime
        clock_in = self.clock_in
        clock_out = self.clock_out
        
        # Initialize night hours counter
        night_hours = 0
        
        # Helper function to calculate hours in a specific day's night shift
        def calc_night_hours_for_day(start, end, same_day=True):
            night_start = start.replace(hour=18, minute=0, second=0)  # 6pm
            next_morning = end.replace(hour=6, minute=0, second=0)  # 6am
            
            if same_day:  # Same calendar day
                if start < night_start:  # Started before night shift
                    if end <= night_start:  # Ended before night shift started
                        return 0
                    else:  # Ended during night shift
                        night_end = min(end, end.replace(hour=23, minute=59, second=59))
                        return (night_end - night_start).total_seconds() / 3600
                else:  # Started during night shift
                    return (end - start).total_seconds() / 3600
            else:  # Overnight shift
                if start.hour >= 18:  # Started in evening
                    # Hours from start to midnight
                    night_hours = (start.replace(hour=23, minute=59, second=59) - start).total_seconds() / 3600
                    # Add hours from midnight to 6am or end time if earlier
                    if end.hour < 6:
                        night_hours += (end - end.replace(hour=0, minute=0, second=0)).total_seconds() / 3600
                    else:
                        night_hours += 6.0  # Full 6 hours from midnight to 6am
                    return night_hours
                elif start.hour < 6:  # Started in early morning
                    if end.hour <= 6:  # Ended before 6am
                        return (end - start).total_seconds() / 3600
                    else:  # Ended after 6am
                        return (next_morning - start).total_seconds() / 3600
        
        # Check if shift spans multiple days
        if clock_out.date() != clock_in.date():
            # Calculate night hours for each day
            days_between = (clock_out.date() - clock_in.date()).days
            
            # First day (from clock_in to midnight)
            if clock_in.hour < 18:  # Started before night shift
                night_hours += calc_night_hours_for_day(clock_in, clock_in.replace(hour=23, minute=59, second=59), True)
            else:  # Started during night shift
                night_hours += (clock_in.replace(hour=23, minute=59, second=59) - clock_in).total_seconds() / 3600
            
            # Middle days (each gets 12 night hours - 6pm to 6am)
            if days_between > 1:
                night_hours += (days_between - 1) * 12
            
            # Last day (from midnight to clock_out)
            if clock_out.hour <= 6:  # Ended during early morning night shift
                night_hours += (clock_out - clock_out.replace(hour=0, minute=0, second=0)).total_seconds() / 3600
            elif clock_out.hour >= 18:  # Ended during evening night shift
                night_hours += (clock_out - clock_out.replace(hour=18, minute=0, second=0)).total_seconds() / 3600
                # Also add early morning hours (midnight to 6am)
                night_hours += 6.0
            else:  # Ended during day shift
                night_hours += 6.0  # Just the 6 hours from midnight to 6am
        else:
            # Single day shift
            night_hours = calc_night_hours_for_day(clock_in, clock_out, True)
        
        # Ensure we don't report more night hours than total hours worked
        return min(night_hours, total_hours)
    
    def calculate_pay(self):
        """Calculate pay based on the overtime rules including night shift allowance"""
        if not self.clock_out:
            return 0
                
        hours = self.calculate_hours()
        employee = self.employee
        
        # Night shift calculation
        night_shift_hours = 0
        night_shift_allowance = 0
        
        if self.is_night_shift() and employee.is_night_worker:
            night_shift_hours = self.calculate_night_shift_hours()
            night_shift_allowance = night_shift_hours * (employee.hourly_rate * employee.night_shift_allowance)
        
        # Public holiday calculation has highest priority
        if self.is_public_holiday:
            if employee.is_holiday_worker:
                # 1.5x for holiday workers
                return (hours * employee.hourly_rate * 1.5) + night_shift_allowance
            else:
                # 2x for non-holiday workers
                return (hours * employee.hourly_rate * 2) + night_shift_allowance
        
        # Sunday calculation
        if self.is_sunday():
            if employee.is_sunday_worker:
                # 1.5x for Sunday workers
                return (hours * employee.hourly_rate * 1.5) + night_shift_allowance
            else:
                # 2x for non-Sunday workers
                return (hours * employee.hourly_rate * 2) + night_shift_allowance
                
        # Saturday calculation (same as weekday overtime)
        if self.is_saturday():
            # 1.5x for Saturday
            return (hours * employee.hourly_rate * 1.5) + night_shift_allowance
            
        # Weekday calculation with overtime
        regular_hours = min(8, hours)
        overtime_hours = max(0, hours - 8)
        
        regular_pay = regular_hours * employee.hourly_rate
        overtime_pay = overtime_hours * (employee.hourly_rate * 1.5)  # Always 1.5x for weekday overtime
        
        return regular_pay + overtime_pay + night_shift_allowance
    
    def calculate_pay_breakdown(self):
        """Calculate detailed pay breakdown with the new rules including night shift allowance"""
        if not self.clock_out:
            return {
                'regular_hours': 0,
                'overtime_hours': 0,
                'weekend_hours': 0,
                'holiday_hours': 0,
                'night_shift_hours': 0,
                'regular_pay': 0,
                'overtime_pay': 0,
                'weekend_pay': 0,
                'holiday_pay': 0,
                'night_shift_allowance': 0,
                'total_pay': 0
            }
            
        hours = self.calculate_hours()
        employee = self.employee
        
        # Start with empty breakdown
        breakdown = {
            'regular_hours': 0,
            'overtime_hours': 0,
            'weekend_hours': 0,
            'holiday_hours': 0,
            'night_shift_hours': 0,
            'regular_pay': 0,
            'overtime_pay': 0,
            'weekend_pay': 0,
            'holiday_pay': 0,
            'night_shift_allowance': 0,
            'total_pay': 0
        }
        
        # Calculate night shift hours and allowance
        if self.is_night_shift() and employee.is_night_worker:
            breakdown['night_shift_hours'] = self.calculate_night_shift_hours()
            breakdown['night_shift_allowance'] = breakdown['night_shift_hours'] * (employee.hourly_rate * employee.night_shift_allowance)
        
        # Public holiday calculation
        if self.is_public_holiday:
            if employee.is_holiday_worker:
                # 1.5x for holiday workers
                rate = employee.hourly_rate * 1.5
                breakdown['holiday_hours'] = hours
                breakdown['holiday_pay'] = hours * rate
            else:
                # 2x for non-holiday workers
                rate = employee.hourly_rate * 2
                breakdown['holiday_hours'] = hours
                breakdown['holiday_pay'] = hours * rate
                
            breakdown['total_pay'] = breakdown['holiday_pay'] + breakdown['night_shift_allowance']
            return breakdown
        
        # Sunday calculation
        if self.is_sunday():
            if employee.is_sunday_worker:
                # 1.5x for Sunday workers
                rate = employee.hourly_rate * 1.5
            else:
                # 2x for non-Sunday workers
                rate = employee.hourly_rate * 2
                
            breakdown['weekend_hours'] = hours
            breakdown['weekend_pay'] = hours * rate
            breakdown['total_pay'] = breakdown['weekend_pay'] + breakdown['night_shift_allowance']
            return breakdown
            
        # Saturday calculation
        if self.is_saturday():
            # 1.5x for Saturday (same as weekday overtime)
            rate = employee.hourly_rate * 1.5
            breakdown['weekend_hours'] = hours
            breakdown['weekend_pay'] = hours * rate
            breakdown['total_pay'] = breakdown['weekend_pay'] + breakdown['night_shift_allowance']
            return breakdown
            
        # Weekday calculation with overtime
        regular_hours = min(8, hours)
        overtime_hours = max(0, hours - 8)
        
        breakdown['regular_hours'] = regular_hours
        breakdown['overtime_hours'] = overtime_hours
        breakdown['regular_pay'] = regular_hours * employee.hourly_rate
        breakdown['overtime_pay'] = overtime_hours * (employee.hourly_rate * 1.5)
        breakdown['total_pay'] = breakdown['regular_pay'] + breakdown['overtime_pay'] + breakdown['night_shift_allowance']
        
        return breakdown
    
    def check_for_violations(self, weekly_hours):
        """Check for labor law violations
        
        Args:
            weekly_hours: Total hours worked this week including this timesheet
            
        Returns:
            list: List of violation messages, empty if no violations
        """
        violations = []
        hours = self.calculate_hours()
        
        # Daily violations - max 3 overtime hours per day (over 8 hours)
        if hours > 11:  # 8 regular + 3 overtime
            violations.append(f"Daily hours exceed limit: {hours:.1f} hours (max: 11 hours)")
        
        # Weekly violations - max 45 regular hours and max 10 overtime hours
        if weekly_hours > 55:  # 45 regular + 10 overtime
            violations.append(f"Weekly hours exceed limit: {weekly_hours:.1f} hours (max: 55 hours)")
        elif weekly_hours > 45:
            overtime = weekly_hours - 45
            if overtime > 10:
                violations.append(f"Weekly overtime exceeds limit: {overtime:.1f} hours (max: 10 hours)")
                
        return violations
            
class RateFunction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    weekday_formula = db.Column(db.String(200), nullable=False)  # Python expression as string
    weekend_formula = db.Column(db.String(200), nullable=False)  # Python expression as string
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    employees = db.relationship('Employee', backref='rate_function', lazy=True)
    
    def calculate_weekday_overtime(self, base_rate, overtime_rate):
        """Calculate the effective weekday overtime rate using the formula
        
        Args:
            base_rate: The employee's regular hourly rate
            overtime_rate: The employee's standard overtime rate
            
        Returns:
            float: The calculated overtime rate
        """
        try:
            # Validate formula for safety - only allow basic operations and numbers
            formula = self.weekday_formula.replace(" ", "")
            if not self._is_safe_formula(formula):
                return overtime_rate  # Fall back to default if formula is potentially unsafe
                
            # Create a safe environment with limited variables
            env = {'base': base_rate, 'overtime': overtime_rate}
            # Evaluate the formula with the given rates
            return float(eval(self.weekday_formula, {"__builtins__": {}}, env))
        except Exception as e:
            # Fallback to regular overtime rate in case of error
            print(f"Error calculating overtime rate with formula '{self.weekday_formula}': {str(e)}")
            return overtime_rate
    
    def calculate_weekend_rate(self, base_rate, weekend_rate):
        """Calculate the effective weekend rate using the formula
        
        Args:
            base_rate: The employee's regular hourly rate
            weekend_rate: The employee's standard weekend rate
            
        Returns:
            float: The calculated weekend rate
        """
        try:
            # Validate formula for safety - only allow basic operations and numbers
            formula = self.weekend_formula.replace(" ", "")
            if not self._is_safe_formula(formula):
                return weekend_rate  # Fall back to default if formula is potentially unsafe
                
            # Create a safe environment with limited variables
            env = {'base': base_rate, 'weekend': weekend_rate}
            # Evaluate the formula with the given rates
            return float(eval(self.weekend_formula, {"__builtins__": {}}, env))
        except Exception as e:
            # Fallback to regular weekend rate in case of error
            print(f"Error calculating weekend rate with formula '{self.weekend_formula}': {str(e)}")
            return weekend_rate
            
    def _is_safe_formula(self, formula):
        """Check if the formula is safe to evaluate
        
        Args:
            formula: The formula string to check
            
        Returns:
            bool: True if the formula is safe, False otherwise
        """
        # Only allow basic arithmetic operations, numbers, variables, and simple conditionals
        allowed_chars = set('0123456789.+-*/()= <>!baseovertimweekndfalstru')
        return all(c in allowed_chars for c in formula.lower())
    
class EmployeeGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    
    # Criteria for automatically adding employees to this group
    job_title_id = db.Column(db.Integer, db.ForeignKey('job_title.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    
    # Relationships
    job_title = db.relationship('JobTitle', backref='groups', foreign_keys=[job_title_id])
    location = db.relationship('Location', backref='groups', foreign_keys=[location_id])
    employees = db.relationship('Employee', secondary='employee_group_membership', backref='groups')

# Association table for many-to-many relationship between employees and groups
employee_group_membership = db.Table('employee_group_membership',
    db.Column('employee_id', db.Integer, db.ForeignKey('employee.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('employee_group.id'), primary_key=True)
)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        
        flash('Invalid username or password')
        
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    company = current_user.company
    active_employees = Employee.query.filter_by(company_id=company.id, is_active=True).all()
    
    # Get active timesheets
    active_timesheets = {}
    for employee in active_employees:
        active_timesheet = Timesheet.query.filter_by(employee_id=employee.id, clock_out=None).first()
        if active_timesheet:
            active_timesheets[employee.id] = active_timesheet
    
    # Add month names and current month/year for the export form
    import calendar
    import datetime
    month_names = list(calendar.month_name)[1:]  # Skip the first empty element
    current_month = datetime.datetime.now().month
    current_year = datetime.datetime.now().year
    
    # Calculate weekly hours for the current week
    today = datetime.datetime.now()
    week_start = today - datetime.timedelta(days=today.weekday())  # Monday of this week
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + datetime.timedelta(days=6)  # Sunday of this week
    week_end = week_end.replace(hour=23, minute=59, second=59)
    
    # Get all timesheets for the current week
    weekly_hours = {}
    for employee in active_employees:
        # Get completed timesheets for the week
        completed_timesheets = Timesheet.query.filter(
            Timesheet.employee_id == employee.id,
            Timesheet.clock_in >= week_start,
            Timesheet.clock_in <= week_end,
            Timesheet.clock_out != None
        ).all()
        
        # Calculate total hours from completed timesheets
        total_hours = sum(ts.calculate_hours() for ts in completed_timesheets)
        
        # Add hours from active timesheet (if any)
        if employee.id in active_timesheets:
            active_ts = active_timesheets[employee.id]
            # Calculate hours worked so far in the active timesheet
            now = datetime.datetime.now()
            active_hours = (now - active_ts.clock_in).total_seconds() / 3600
            total_hours += active_hours
        
        weekly_hours[employee.id] = total_hours
    
    return render_template('dashboard.html', 
                          company=company, 
                          employees=active_employees, 
                          active_timesheets=active_timesheets,
                          month_names=month_names,
                          current_month=current_month,
                          current_year=current_year,
                          weekly_hours=weekly_hours,
                          week_start_date=week_start.date(),
                          week_end_date=week_end.date())

@app.route('/employees')
@login_required
def employees():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company = current_user.company
    employees = Employee.query.filter_by(company_id=company.id).all()
    return render_template('employees.html', employees=employees)

@app.route('/add_employee', methods=['GET', 'POST'])
@login_required
def add_employee():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Get job titles, locations, and rate functions for the dropdown
    job_titles = JobTitle.query.filter_by(company_id=current_user.company.id).all()
    locations = Location.query.filter_by(company_id=current_user.company.id).all()
    rate_functions = RateFunction.query.filter_by(company_id=current_user.company.id).all()
    
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        hourly_rate = float(request.form.get('hourly_rate'))
        overtime_rate = float(request.form.get('overtime_rate'))
        weekend_rate = float(request.form.get('weekend_rate'))
        additional_info = request.form.get('additional_info')
        job_title_id = request.form.get('job_title_id')
        location_id = request.form.get('location_id')
        rate_function_id = request.form.get('rate_function_id')
        
        # New fields for overtime rules
        is_sunday_worker = 'is_sunday_worker' in request.form
        is_holiday_worker = 'is_holiday_worker' in request.form
        
        # Handle empty strings for optional foreign keys
        if job_title_id == '':
            job_title_id = None
        else:
            job_title_id = int(job_title_id)
            
        if location_id == '':
            location_id = None
        else:
            location_id = int(location_id)
            
        if rate_function_id == '':
            rate_function_id = None
        else:
            rate_function_id = int(rate_function_id)
        
        employee = Employee(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            hourly_rate=hourly_rate,
            overtime_rate=overtime_rate,
            weekend_rate=weekend_rate,
            additional_info=additional_info,
            company_id=current_user.company.id,
            job_title_id=job_title_id,
            location_id=location_id,
            rate_function_id=rate_function_id,
            is_sunday_worker=is_sunday_worker,
            is_holiday_worker=is_holiday_worker
        )
        
        db.session.add(employee)
        db.session.commit()
        
        flash('Employee added successfully!')
        return redirect(url_for('employees'))
    
    return render_template('add_employee.html', job_titles=job_titles, locations=locations, rate_functions=rate_functions)

@app.route('/edit_employee/<int:employee_id>', methods=['GET', 'POST'])
@login_required
def edit_employee(employee_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    employee = Employee.query.get_or_404(employee_id)
    
    # Make sure the employee belongs to the current user's company
    if employee.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('employees'))
    
    # Get job titles, locations, and rate functions for the dropdown
    job_titles = JobTitle.query.filter_by(company_id=current_user.company.id).all()
    locations = Location.query.filter_by(company_id=current_user.company.id).all()
    rate_functions = RateFunction.query.filter_by(company_id=current_user.company.id).all()
    
    if request.method == 'POST':
        employee.first_name = request.form.get('first_name')
        employee.last_name = request.form.get('last_name')
        employee.email = request.form.get('email')
        employee.phone = request.form.get('phone')
        employee.hourly_rate = float(request.form.get('hourly_rate'))
        employee.overtime_rate = float(request.form.get('overtime_rate'))
        employee.weekend_rate = float(request.form.get('weekend_rate'))
        employee.additional_info = request.form.get('additional_info')
        employee.is_active = 'is_active' in request.form
        
        # Special worker types
        employee.is_sunday_worker = 'is_sunday_worker' in request.form
        employee.is_holiday_worker = 'is_holiday_worker' in request.form
        employee.is_night_worker = 'is_night_worker' in request.form
        
        # Night shift allowance
        night_shift_allowance = request.form.get('night_shift_allowance', '')
        if night_shift_allowance == '':
            employee.night_shift_allowance = current_user.company.default_night_allowance
        else:
            employee.night_shift_allowance = float(night_shift_allowance)
        
        job_title_id = request.form.get('job_title_id')
        location_id = request.form.get('location_id')
        rate_function_id = request.form.get('rate_function_id')
        
        # Handle empty strings for optional foreign keys
        if job_title_id == '':
            employee.job_title_id = None
        else:
            employee.job_title_id = int(job_title_id)
            
        if location_id == '':
            employee.location_id = None
        else:
            employee.location_id = int(location_id)
            
        if rate_function_id == '':
            employee.rate_function_id = None
        else:
            employee.rate_function_id = int(rate_function_id)
        
        db.session.commit()
        
        flash('Employee updated successfully!')
        return redirect(url_for('employees'))
    
    return render_template('edit_employee.html', employee=employee, job_titles=job_titles, locations=locations, rate_functions=rate_functions)

@app.route('/clock_in/<int:employee_id>')
@login_required
def clock_in(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    
    # Make sure the employee belongs to the current user's company
    if employee.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Check if employee is already clocked in
    active_timesheet = Timesheet.query.filter_by(employee_id=employee.id, clock_out=None).first()
    if active_timesheet:
        flash(f'{employee.full_name()} is already clocked in!')
        return redirect(url_for('dashboard'))
    
    # Get date for weekly hours calculation
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())  # Monday of this week
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Calculate total hours worked this week
    weekly_timesheets = Timesheet.query.filter(
        Timesheet.employee_id == employee.id,
        Timesheet.clock_in >= week_start,
        Timesheet.clock_out != None
    ).all()
    
    weekly_hours = sum(ts.calculate_hours() for ts in weekly_timesheets)
    
    # Check for weekly hour violations before clock-in
    if weekly_hours >= 55:  # 45 regular + 10 overtime
        flash(f'WARNING: {employee.full_name()} has already worked {weekly_hours:.1f} hours this week, which exceeds the 55-hour limit.', 'warning')
    elif weekly_hours > 45:
        overtime = weekly_hours - 45
        if overtime >= 10:
            flash(f'WARNING: {employee.full_name()} has already worked {overtime:.1f} hours of overtime this week, which reaches or exceeds the 10-hour overtime limit.', 'warning')
    
    timesheet = Timesheet(
        employee_id=employee.id,
        clock_in=datetime.now()
    )
    
    db.session.add(timesheet)
    db.session.commit()
    
    flash(f'{employee.full_name()} clocked in successfully!')
    return redirect(url_for('dashboard'))

@app.route('/clock_out/<int:employee_id>')
@login_required
def clock_out(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    
    # Make sure the employee belongs to the current user's company
    if employee.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Find active timesheet
    timesheet = Timesheet.query.filter_by(employee_id=employee.id, clock_out=None).first()
    if not timesheet:
        flash(f'{employee.full_name()} is not clocked in!')
        return redirect(url_for('dashboard'))
    
    timesheet.clock_out = datetime.now()
    db.session.commit()
    
    hours = timesheet.calculate_hours()
    
    # Get date for weekly hours calculation
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())  # Monday of this week
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Calculate total hours worked this week (including this timesheet)
    weekly_timesheets = Timesheet.query.filter(
        Timesheet.employee_id == employee.id,
        Timesheet.clock_in >= week_start,
        Timesheet.clock_out != None
    ).all()
    
    weekly_hours = sum(ts.calculate_hours() for ts in weekly_timesheets)
    
    # Check for violations
    violations = timesheet.check_for_violations(weekly_hours)
    
    if violations:
        violation_message = '<br>'.join(violations)
        flash(f'{employee.full_name()} clocked out successfully! Worked for {hours:.1f} hours. <br><strong>VIOLATIONS DETECTED:</strong><br>{violation_message}', 'danger')
    else:
        flash(f'{employee.full_name()} clocked out successfully! Worked for {hours:.1f} hours.')
    
    return redirect(url_for('dashboard'))

@app.route('/mark_holiday/<int:timesheet_id>', methods=['POST'])
@login_required
def mark_holiday(timesheet_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    timesheet = Timesheet.query.get_or_404(timesheet_id)
    
    # Verify the timesheet belongs to the current user's company
    employee = Employee.query.get(timesheet.employee_id)
    if employee.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Toggle holiday status
    timesheet.is_public_holiday = not timesheet.is_public_holiday
    db.session.commit()
    
    if timesheet.is_public_holiday:
        flash(f'Timesheet marked as public holiday.')
    else:
        flash(f'Holiday marking removed from timesheet.')
    
    return redirect(url_for('employee_timesheets', employee_id=timesheet.employee_id))

@app.route('/company_settings', methods=['GET', 'POST'])
@login_required
def company_settings():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company = current_user.company
    
    if request.method == 'POST':
        company.name = request.form.get('company_name')
        company.standard_hours = int(request.form.get('standard_hours'))
        
        # Add handling for default night shift allowance
        default_night_allowance = request.form.get('default_night_allowance', '')
        if default_night_allowance != '':
            company.default_night_allowance = float(default_night_allowance)
        
        db.session.commit()
        
        flash('Company settings updated successfully!')
        return redirect(url_for('dashboard'))
    
    return render_template('company_settings.html', company=company)

@app.route('/job_titles')
@login_required
def job_titles():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company = current_user.company
    titles = JobTitle.query.filter_by(company_id=company.id).all()
    return render_template('job_titles.html', titles=titles)

@app.route('/add_job_title', methods=['GET', 'POST'])
@login_required
def add_job_title():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        
        job_title = JobTitle(
            title=title,
            description=description,
            company_id=current_user.company.id
        )
        
        db.session.add(job_title)
        db.session.commit()
        
        flash('Job title added successfully!')
        return redirect(url_for('job_titles'))
    
    return render_template('add_job_title.html')

@app.route('/edit_job_title/<int:title_id>', methods=['GET', 'POST'])
@login_required
def edit_job_title(title_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    job_title = JobTitle.query.get_or_404(title_id)
    
    # Make sure the job title belongs to the current user's company
    if job_title.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('job_titles'))
    
    if request.method == 'POST':
        job_title.title = request.form.get('title')
        job_title.description = request.form.get('description')
        
        db.session.commit()
        
        flash('Job title updated successfully!')
        return redirect(url_for('job_titles'))
    
    return render_template('edit_job_title.html', job_title=job_title)

@app.route('/delete_job_title/<int:title_id>')
@login_required
def delete_job_title(title_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    job_title = JobTitle.query.get_or_404(title_id)
    
    # Make sure the job title belongs to the current user's company
    if job_title.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('job_titles'))
    
    # Check if this job title is assigned to any employees
    employees_count = Employee.query.filter_by(job_title_id=title_id).count()
    if employees_count > 0:
        flash(f'Cannot delete: This job title is assigned to {employees_count} employees.')
        return redirect(url_for('job_titles'))
    
    db.session.delete(job_title)
    db.session.commit()
    
    flash('Job title deleted successfully!')
    return redirect(url_for('job_titles'))

@app.route('/locations')
@login_required
def locations():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company = current_user.company
    locations = Location.query.filter_by(company_id=company.id).all()
    return render_template('locations.html', locations=locations)

@app.route('/add_location', methods=['GET', 'POST'])
@login_required
def add_location():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        address = request.form.get('address')
        
        location = Location(
            name=name,
            address=address,
            company_id=current_user.company.id
        )
        
        db.session.add(location)
        db.session.commit()
        
        flash('Location added successfully!')
        return redirect(url_for('locations'))
    
    return render_template('add_location.html')

@app.route('/edit_location/<int:location_id>', methods=['GET', 'POST'])
@login_required
def edit_location(location_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    location = Location.query.get_or_404(location_id)
    
    # Make sure the location belongs to the current user's company
    if location.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('locations'))
    
    if request.method == 'POST':
        location.name = request.form.get('name')
        location.address = request.form.get('address')
        
        db.session.commit()
        
        flash('Location updated successfully!')
        return redirect(url_for('locations'))
    
    return render_template('edit_location.html', location=location)

@app.route('/delete_location/<int:location_id>')
@login_required
def delete_location(location_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    location = Location.query.get_or_404(location_id)
    
    # Make sure the location belongs to the current user's company
    if location.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('locations'))
    
    # Check if this location is assigned to any employees
    employees_count = Employee.query.filter_by(location_id=location_id).count()
    if employees_count > 0:
        flash(f'Cannot delete: This location is assigned to {employees_count} employees.')
        return redirect(url_for('locations'))
    
    db.session.delete(location)
    db.session.commit()
    
    flash('Location deleted successfully!')
    return redirect(url_for('locations'))

@app.route('/employee_timesheets/<int:employee_id>')
@login_required
def employee_timesheets(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    
    # Make sure the employee belongs to the current user's company
    if employee.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    timesheets = Timesheet.query.filter_by(employee_id=employee.id).order_by(Timesheet.clock_in.desc()).all()
    
    # Prepare timesheet data with calculated hours, overtime, and weekend rates
    timesheet_data = []
    for ts in timesheets:
        if ts.clock_out:  # Only include completed timesheets
            pay_breakdown = ts.calculate_pay_breakdown()
            
            timesheet_data.append({
                'id': ts.id,
                'date': ts.clock_in.strftime('%Y-%m-%d'),
                'clock_in': ts.clock_in.strftime('%H:%M'),
                'clock_out': ts.clock_out.strftime('%H:%M') if ts.clock_out else 'Active',
                'hours': pay_breakdown['regular_hours'] + pay_breakdown['overtime_hours'] + pay_breakdown['weekend_hours'],
                'regular_hours': pay_breakdown['regular_hours'],
                'overtime_hours': pay_breakdown['overtime_hours'],
                'weekend_hours': pay_breakdown['weekend_hours'],
                'regular_pay': pay_breakdown['regular_pay'],
                'overtime_pay': pay_breakdown['overtime_pay'],
                'weekend_pay': pay_breakdown['weekend_pay'],
                'total_pay': pay_breakdown['total_pay']
            })
    
    return render_template('employee_timesheets.html', 
                          employee=employee, 
                          timesheets=timesheet_data)

@app.route('/export_employee_timesheet/<int:employee_id>')
@login_required
def export_employee_timesheet(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    
    # Make sure the employee belongs to the current user's company
    if employee.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Get date range parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        # Add one day to end_date to include the entire end day
        end_date = end_date + timedelta(days=1)
    except (ValueError, TypeError):
        # Default to current month if dates not provided or invalid
        today = datetime.today()
        start_date = datetime(today.year, today.month, 1)
        end_date = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1)
    
    # Query timesheets within date range
    timesheets = Timesheet.query.filter(
        Timesheet.employee_id == employee.id,
        Timesheet.clock_in >= start_date,
        Timesheet.clock_in < end_date,
        Timesheet.clock_out != None  # Only include completed timesheets
    ).order_by(Timesheet.clock_in).all()
    
    # Create CSV file
    si = StringIO()
    csv_writer = csv.writer(si)
    
    # Write header
    csv_writer.writerow([
        'Date', 'Clock In', 'Clock Out', 'Hours Worked', 
        'Regular Hours', 'Overtime Hours', 'Weekend Hours',
        'Regular Pay', 'Overtime Pay', 'Weekend Pay', 'Total Pay'
    ])
    
    # Write timesheet data
    total_hours = 0
    total_regular_hours = 0
    total_overtime_hours = 0
    total_weekend_hours = 0
    total_regular_pay = 0
    total_overtime_pay = 0
    total_weekend_pay = 0
    total_pay = 0
    
    for ts in timesheets:
        if ts.clock_out:
            # Calculate pay breakdown
            pay_breakdown = ts.calculate_pay_breakdown()
            hours = pay_breakdown['regular_hours'] + pay_breakdown['overtime_hours'] + pay_breakdown['weekend_hours']
            
            csv_writer.writerow([
                ts.clock_in.strftime('%Y-%m-%d'),
                ts.clock_in.strftime('%H:%M'),
                ts.clock_out.strftime('%H:%M'),
                f'{hours:.2f}',
                f'{pay_breakdown["regular_hours"]:.2f}',
                f'{pay_breakdown["overtime_hours"]:.2f}',
                f'{pay_breakdown["weekend_hours"]:.2f}',
                f'${pay_breakdown["regular_pay"]:.2f}',
                f'${pay_breakdown["overtime_pay"]:.2f}',
                f'${pay_breakdown["weekend_pay"]:.2f}',
                f'${pay_breakdown["total_pay"]:.2f}'
            ])
            
            total_hours += hours
            total_regular_hours += pay_breakdown['regular_hours']
            total_overtime_hours += pay_breakdown['overtime_hours']
            total_weekend_hours += pay_breakdown['weekend_hours']
            total_regular_pay += pay_breakdown['regular_pay']
            total_overtime_pay += pay_breakdown['overtime_pay']
            total_weekend_pay += pay_breakdown['weekend_pay']
            total_pay += pay_breakdown['total_pay']
    
    # Write totals
    csv_writer.writerow([])
    csv_writer.writerow([
        'TOTALS', '', '', 
        f'{total_hours:.2f}', 
        f'{total_regular_hours:.2f}', 
        f'{total_overtime_hours:.2f}',
        f'{total_weekend_hours:.2f}',
        f'${total_regular_pay:.2f}',
        f'${total_overtime_pay:.2f}',
        f'${total_weekend_pay:.2f}',
        f'${total_pay:.2f}'
    ])
    
    # Prepare response
    output = si.getvalue()
    filename = f"{employee.last_name}_{employee.first_name}_timesheet_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}.csv"
    
    return output, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }

@app.route('/download_sample_excel')
@login_required
def download_sample_excel():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Template for sample Excel file - updated with night shift fields
    sample_data = {
        'first_name': ['John', 'Jane'],
        'last_name': ['Doe', 'Smith'],
        'title': ['Manager', 'Developer'],
        'location': ['Main Office', 'Remote'],
        'phone': ['555-123-4567', '555-987-6543'],
        'email': ['john.doe@example.com', 'jane.smith@example.com'],
        'hourly_rate': [25.0, 22.5],
        'overtime_rate': [37.5, 33.75],
        'weekend_rate': [50.0, 45.0],
        'is_sunday_worker': [False, True],
        'is_holiday_worker': [False, True],
        'is_night_worker': [True, False],  # Added night worker flag
        'night_shift_allowance': [0.15, 0.1],  # Added night shift allowance rate
        'additional_info': ['Team lead', 'Frontend specialist']
    }
    sample_df = pd.DataFrame(sample_data)
    
    # Create sample Excel file in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        sample_df.to_excel(writer, index=False)
    output.seek(0)
    
    return send_file(
        output,
        as_attachment=True,
        download_name='employee_import_template.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/export_monthly_timesheet')
@login_required
def export_monthly_timesheet():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Get month and year parameters
    month = request.args.get('month', datetime.now().month, type=int)
    year = request.args.get('year', datetime.now().year, type=int)
    
    # Validate month and year
    if month < 1 or month > 12 or year < 2000 or year > 2100:
        flash('Invalid month or year')
        return redirect(url_for('dashboard'))
    
    # Calculate date range for the selected month
    start_date = datetime(year, month, 1)
    # Get the last day of the month
    _, last_day = calendar.monthrange(year, month)
    end_date = datetime(year, month, last_day, 23, 59, 59)
    
    # Get all employees in the company
    employees = Employee.query.filter_by(company_id=current_user.company.id).all()
    
    # Create CSV file
    si = StringIO()
    csv_writer = csv.writer(si)
    
    # Write header
    csv_writer.writerow([
        'Employee', 'Email', 'Total Hours', 
        'Regular Hours', 'Overtime Hours', 
        'Regular Pay', 'Overtime Pay', 'Total Pay'
    ])
    
    # Write data for each employee
    for employee in employees:
        # Get completed timesheets for the month
        timesheets = Timesheet.query.filter(
            Timesheet.employee_id == employee.id,
            Timesheet.clock_in >= start_date,
            Timesheet.clock_in <= end_date,
            Timesheet.clock_out != None
        ).all()
        
        if not timesheets:
            continue  # Skip employees with no timesheets in this period
        
        # Calculate totals
        total_hours = 0
        total_regular_hours = 0
        total_overtime_hours = 0
        weekly_hours = {}  # To track weekly hours for overtime calculation
        
        for ts in timesheets:
            if ts.clock_out:
                hours = ts.calculate_hours()
                total_hours += hours
                
                # Determine week of the timesheet for weekly overtime calculation
                week_start = ts.clock_in.date() - timedelta(days=ts.clock_in.weekday())
                week_key = week_start.strftime('%Y-%m-%d')
                
                if week_key not in weekly_hours:
                    weekly_hours[week_key] = 0
                
                weekly_hours[week_key] += hours
        
        # Calculate overtime based on weekly hours exceeding standard hours
        standard_hours = current_user.company.standard_hours
        
        for week, hours in weekly_hours.items():
            if hours > standard_hours:
                regular_hours_this_week = standard_hours
                overtime_hours_this_week = hours - standard_hours
            else:
                regular_hours_this_week = hours
                overtime_hours_this_week = 0
            
            total_regular_hours += regular_hours_this_week
            total_overtime_hours += overtime_hours_this_week
        
        # Calculate pay
        regular_pay = total_regular_hours * employee.hourly_rate
        overtime_pay = total_overtime_hours * employee.overtime_rate
        total_pay = regular_pay + overtime_pay
        
        # Write row for this employee
        csv_writer.writerow([
            f"{employee.first_name} {employee.last_name}",
            employee.email,
            f"{total_hours:.2f}",
            f"{total_regular_hours:.2f}",
            f"{total_overtime_hours:.2f}",
            f"R{regular_pay:.2f}",
            f"R{overtime_pay:.2f}",
            f"R{total_pay:.2f}"
        ])
    
    # Prepare response
    output = si.getvalue()
    month_name = calendar.month_name[month]
    filename = f"{current_user.company.name}_timesheets_{month_name}_{year}.csv"
    
    return output, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }

@app.route('/import_employees', methods=['GET', 'POST'])
@login_required
def import_employees():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
        
    # Get job titles and locations for validation
    job_titles = {title.title: title.id for title in JobTitle.query.filter_by(company_id=current_user.company.id).all()}
    locations = {location.name: location.id for location in Location.query.filter_by(company_id=current_user.company.id).all()}
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
            
        file = request.files['file']
        
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
            
        if file and file.filename.endswith(('.xlsx', '.xls')):
            try:
                # Read the Excel file
                df = pd.read_excel(file, engine='openpyxl')
                
                # Check for required columns
                required_columns = ['first_name', 'last_name', 'title', 'location', 'phone']
                missing_columns = [col for col in required_columns if col not in df.columns]
                
                if missing_columns:
                    flash(f"Missing required columns: {', '.join(missing_columns)}")
                    return redirect(request.url)
                
                # Track results
                success_count = 0
                error_count = 0
                error_messages = []
                
                # Process each row
                for index, row in df.iterrows():
                    try:
                        # Validate required fields
                        skip_row = False
                        for required_field in required_columns:
                            if pd.isna(row.get(required_field)) or not row.get(required_field):
                                error_count += 1
                                error_messages.append(f"Row {index+2}: Missing required field '{required_field}'")
                                skip_row = True
                                break
                                
                        if skip_row:
                            continue
                            
                        # Get or validate job title
                        job_title_id = None
                        if row['title'] in job_titles:
                            job_title_id = job_titles[row['title']]
                        else:
                            # Create new job title if it doesn't exist
                            new_title = JobTitle(
                                title=row['title'],
                                description=f"Auto-created from import",
                                company_id=current_user.company.id
                            )
                            db.session.add(new_title)
                            db.session.flush()  # Get the ID without committing
                            job_title_id = new_title.id
                            job_titles[row['title']] = job_title_id
                        
                        # Get or validate location
                        location_id = None
                        if row['location'] in locations:
                            location_id = locations[row['location']]
                        else:
                            # Create new location if it doesn't exist
                            new_location = Location(
                                name=row['location'],
                                address=f"Auto-created from import",
                                company_id=current_user.company.id
                            )
                            db.session.add(new_location)
                            db.session.flush()  # Get the ID without committing
                            location_id = new_location.id
                            locations[row['location']] = location_id
                        
                        # Generate email if not provided or if it's NaN
                        email = row.get('email')
                        if pd.isna(email) or not email:
                            email = f"{str(row['first_name']).lower().strip()}.{str(row['last_name']).lower().strip()}@{current_user.company.name.lower().replace(' ', '')}.com"
                        
                        # Check if employee with this email already exists
                        existing_employee = Employee.query.filter_by(email=email, company_id=current_user.company.id).first()
                        if existing_employee:
                            error_count += 1
                            error_messages.append(f"Row {index+2}: Employee with email {email} already exists")
                            continue
                        
                        # Set default hourly and overtime rates if not provided
                        hourly_rate = row.get('hourly_rate', 0)
                        overtime_rate = row.get('overtime_rate', 0)
                        weekend_rate = row.get('weekend_rate', 0)
                        
                        if hourly_rate == 0 or pd.isna(hourly_rate):
                            hourly_rate = 15.0  # Default hourly rate
                        if overtime_rate == 0 or pd.isna(overtime_rate):
                            overtime_rate = hourly_rate * 1.5  # Default overtime rate
                        if weekend_rate == 0 or pd.isna(weekend_rate):
                            weekend_rate = hourly_rate * 2.0  # Default weekend rate
                            
                        # Process boolean fields for Sunday, holiday, and night workers
                        is_sunday_worker = False
                        is_holiday_worker = False
                        is_night_worker = False
                        
                        # Check for is_sunday_worker field
                        if 'is_sunday_worker' in df.columns and not pd.isna(row['is_sunday_worker']):
                            sunday_val = str(row['is_sunday_worker']).lower()
                            is_sunday_worker = sunday_val in ['yes', 'true', '1', 'y', 't']
                        
                        # Check for is_holiday_worker field
                        if 'is_holiday_worker' in df.columns and not pd.isna(row['is_holiday_worker']):
                            holiday_val = str(row['is_holiday_worker']).lower()
                            is_holiday_worker = holiday_val in ['yes', 'true', '1', 'y', 't']
                            
                        # Check for is_night_worker field
                        if 'is_night_worker' in df.columns and not pd.isna(row['is_night_worker']):
                            night_val = str(row['is_night_worker']).lower()
                            is_night_worker = night_val in ['yes', 'true', '1', 'y', 't']
                            
                        # Check for night shift allowance
                        night_shift_allowance = current_user.company.default_night_allowance  # Default to company setting
                        if 'night_shift_allowance' in df.columns and not pd.isna(row['night_shift_allowance']):
                            night_shift_allowance = float(row['night_shift_allowance'])
                                    
                        # Create new employee
                        employee = Employee(
                            first_name=str(row['first_name']).strip(),
                            last_name=str(row['last_name']).strip(),
                            email=email,
                            phone=str(row['phone']).strip(),
                            hourly_rate=float(hourly_rate),
                            overtime_rate=float(overtime_rate),
                            weekend_rate=float(weekend_rate),
                            additional_info=str(row.get('additional_info', '')).strip(),
                            company_id=current_user.company.id,
                            job_title_id=job_title_id,
                            location_id=location_id,
                            is_active=True,
                            is_sunday_worker=is_sunday_worker,
                            is_holiday_worker=is_holiday_worker,
                            is_night_worker=is_night_worker,
                            night_shift_allowance=night_shift_allowance
                        )
                        
                        db.session.add(employee)
                        success_count += 1
                        
                    except Exception as e:
                        error_count += 1
                        error_messages.append(f"Row {index+2}: {str(e)}")
                
                # Commit all changes
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    flash(f"Error during database commit: {str(e)}")
                    return redirect(request.url)
                
                # Show results
                if success_count > 0:
                    flash(f"Successfully imported {success_count} employees.")
                
                if error_count > 0:
                    for error in error_messages:
                        flash(error, 'error')
                        
                return redirect(url_for('employees'))
                
            except Exception as e:
                db.session.rollback()  # Make sure to rollback the session
                flash(f"Error processing file: {str(e)}")
                return redirect(request.url)
        else:
            flash('File must be an Excel spreadsheet (.xlsx or .xls)')
            return redirect(request.url)
    
    return render_template('import_employees.html')

@app.route('/employee_groups')
@login_required
def employee_groups():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company = current_user.company
    groups = EmployeeGroup.query.filter_by(company_id=company.id).all()
    return render_template('employee_groups.html', groups=groups)

@app.route('/add_employee_group', methods=['GET', 'POST'])
@login_required
def add_employee_group():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Get job titles and locations for the dropdowns
    job_titles = JobTitle.query.filter_by(company_id=current_user.company.id).all()
    locations = Location.query.filter_by(company_id=current_user.company.id).all()
    employees = Employee.query.filter_by(company_id=current_user.company.id, is_active=True).all()
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        job_title_id = request.form.get('job_title_id')
        location_id = request.form.get('location_id')
        selected_employees = request.form.getlist('employees')
        
        # Handle empty strings for optional foreign keys
        if job_title_id == '':
            job_title_id = None
        else:
            job_title_id = int(job_title_id)
            
        if location_id == '':
            location_id = None
        else:
            location_id = int(location_id)
        
        # Create new employee group
        group = EmployeeGroup(
            name=name,
            description=description,
            company_id=current_user.company.id,
            job_title_id=job_title_id,
            location_id=location_id
        )
        
        db.session.add(group)
        db.session.flush()  # Get the group ID
        
        # Add selected employees to the group
        if selected_employees:
            for employee_id in selected_employees:
                employee = Employee.query.get(int(employee_id))
                if employee and employee.company_id == current_user.company.id:
                    group.employees.append(employee)
        
        # Automatically add employees based on job title and location criteria
        if job_title_id or location_id:
            query = Employee.query.filter_by(company_id=current_user.company.id, is_active=True)
            
            if job_title_id:
                query = query.filter_by(job_title_id=job_title_id)
            
            if location_id:
                query = query.filter_by(location_id=location_id)
            
            auto_employees = query.all()
            
            for employee in auto_employees:
                if employee not in group.employees:
                    group.employees.append(employee)
        
        db.session.commit()
        
        flash(f'Employee group "{name}" created successfully with {len(group.employees)} employees!')
        return redirect(url_for('employee_groups'))
    
    return render_template('add_employee_group.html', 
                          job_titles=job_titles, 
                          locations=locations,
                          employees=employees)

@app.route('/edit_employee_group/<int:group_id>', methods=['GET', 'POST'])
@login_required
def edit_employee_group(group_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    group = EmployeeGroup.query.get_or_404(group_id)
    
    # Make sure the group belongs to the current user's company
    if group.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('employee_groups'))
    
    # Get job titles and locations for the dropdowns
    job_titles = JobTitle.query.filter_by(company_id=current_user.company.id).all()
    locations = Location.query.filter_by(company_id=current_user.company.id).all()
    employees = Employee.query.filter_by(company_id=current_user.company.id, is_active=True).all()
    
    if request.method == 'POST':
        group.name = request.form.get('name')
        group.description = request.form.get('description')
        
        job_title_id = request.form.get('job_title_id')
        location_id = request.form.get('location_id')
        selected_employees = request.form.getlist('employees')
        auto_update = 'auto_update' in request.form
        
        # Handle empty strings for optional foreign keys
        if job_title_id == '':
            group.job_title_id = None
        else:
            group.job_title_id = int(job_title_id)
            
        if location_id == '':
            group.location_id = None
        else:
            group.location_id = int(location_id)
        
        # Clear existing employees and add selected ones
        group.employees = []
        
        if selected_employees:
            for employee_id in selected_employees:
                employee = Employee.query.get(int(employee_id))
                if employee and employee.company_id == current_user.company.id:
                    group.employees.append(employee)
        
        # Automatically add employees based on criteria if auto-update is enabled
        if auto_update and (group.job_title_id or group.location_id):
            query = Employee.query.filter_by(company_id=current_user.company.id, is_active=True)
            
            if group.job_title_id:
                query = query.filter_by(job_title_id=group.job_title_id)
            
            if group.location_id:
                query = query.filter_by(location_id=group.location_id)
            
            auto_employees = query.all()
            
            for employee in auto_employees:
                if employee not in group.employees:
                    group.employees.append(employee)
        
        db.session.commit()
        
        flash(f'Employee group "{group.name}" updated successfully with {len(group.employees)} employees!')
        return redirect(url_for('employee_groups'))
    
    return render_template('edit_employee_group.html', 
                          group=group,
                          job_titles=job_titles, 
                          locations=locations,
                          employees=employees)

@app.route('/delete_employee_group/<int:group_id>')
@login_required
def delete_employee_group(group_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    group = EmployeeGroup.query.get_or_404(group_id)
    
    # Make sure the group belongs to the current user's company
    if group.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('employee_groups'))
    
    db.session.delete(group)
    db.session.commit()
    
    flash('Employee group deleted successfully!')
    return redirect(url_for('employee_groups'))

@app.route('/group_timesheets/<int:group_id>')
@login_required
def group_timesheets(group_id):
    group = EmployeeGroup.query.get_or_404(group_id)
    
    # Make sure the group belongs to the current user's company
    if group.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Get date range parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        # Add one day to end_date to include the entire end day
        end_date = end_date + timedelta(days=1)
    except (ValueError, TypeError):
        # Default to current month if dates not provided or invalid
        today = datetime.today()
        start_date = datetime(today.year, today.month, 1)
        # Last day of current month
        next_month = today.replace(day=28) + timedelta(days=4)
        end_date = next_month - timedelta(days=next_month.day)
        end_date = end_date.replace(hour=23, minute=59, second=59)
    
    # Prepare data for each employee in the group
    employee_data = []
    total_regular_hours = 0
    total_overtime_hours = 0
    total_weekend_hours = 0
    total_regular_pay = 0
    total_overtime_pay = 0
    total_weekend_pay = 0
    total_pay = 0
    
    for employee in group.employees:
        if not employee.is_active:
            continue
            
        # Query timesheets within date range
        timesheets = Timesheet.query.filter(
            Timesheet.employee_id == employee.id,
            Timesheet.clock_in >= start_date,
            Timesheet.clock_in < end_date,
            Timesheet.clock_out != None  # Only include completed timesheets
        ).order_by(Timesheet.clock_in).all()
        
        # Calculate totals for this employee
        employee_total_hours = 0
        employee_regular_hours = 0
        employee_overtime_hours = 0
        employee_weekend_hours = 0
        employee_regular_pay = 0
        employee_overtime_pay = 0
        employee_weekend_pay = 0
        
        for ts in timesheets:
            pay_breakdown = ts.calculate_pay_breakdown()
            
            employee_regular_hours += pay_breakdown['regular_hours']
            employee_overtime_hours += pay_breakdown['overtime_hours']
            employee_weekend_hours += pay_breakdown['weekend_hours']
            employee_regular_pay += pay_breakdown['regular_pay']
            employee_overtime_pay += pay_breakdown['overtime_pay']
            employee_weekend_pay += pay_breakdown['weekend_pay']
        
        employee_total_hours = employee_regular_hours + employee_overtime_hours + employee_weekend_hours
        employee_total_pay = employee_regular_pay + employee_overtime_pay + employee_weekend_pay
        
        # Add to employee data list
        if employee_total_hours > 0:  # Only include employees with hours
            employee_data.append({
                'id': employee.id,
                'name': f"{employee.first_name} {employee.last_name}",
                'title': employee.job_title.title if employee.job_title else "-",
                'location': employee.location.name if employee.location else "-",
                'total_hours': employee_total_hours,
                'regular_hours': employee_regular_hours,
                'overtime_hours': employee_overtime_hours,
                'weekend_hours': employee_weekend_hours,
                'regular_pay': employee_regular_pay,
                'overtime_pay': employee_overtime_pay,
                'weekend_pay': employee_weekend_pay,
                'total_pay': employee_total_pay
            })
            
            # Add to group totals
            total_regular_hours += employee_regular_hours
            total_overtime_hours += employee_overtime_hours
            total_weekend_hours += employee_weekend_hours
            total_regular_pay += employee_regular_pay
            total_overtime_pay += employee_overtime_pay
            total_weekend_pay += employee_weekend_pay
            total_pay += employee_total_pay
    
    # Sort employee data by name
    employee_data.sort(key=lambda x: x['name'])
    
    # Prepare date range for display
    formatted_start = start_date.strftime('%Y-%m-%d')
    formatted_end = (end_date - timedelta(days=1)).strftime('%Y-%m-%d')
    
    return render_template('group_timesheets.html',
                          group=group,
                          employee_data=employee_data,
                          start_date=formatted_start,
                          end_date=formatted_end,
                          total_regular_hours=total_regular_hours,
                          total_overtime_hours=total_overtime_hours,
                          total_weekend_hours=total_weekend_hours,
                          total_hours=total_regular_hours + total_overtime_hours + total_weekend_hours,
                          total_regular_pay=total_regular_pay,
                          total_overtime_pay=total_overtime_pay,
                          total_weekend_pay=total_weekend_pay,
                          total_pay=total_pay)

@app.route('/export_group_timesheet/<int:group_id>')
@login_required
def export_group_timesheet(group_id):
    group = EmployeeGroup.query.get_or_404(group_id)
    
    # Make sure the group belongs to the current user's company
    if group.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Get date range parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        # Add one day to end_date to include the entire end day
        end_date = end_date + timedelta(days=1)
    except (ValueError, TypeError):
        # Default to current month if dates not provided or invalid
        today = datetime.today()
        start_date = datetime(today.year, today.month, 1)
        # Last day of current month
        next_month = today.replace(day=28) + timedelta(days=4)
        end_date = next_month - timedelta(days=next_month.day)
        end_date = end_date.replace(hour=23, minute=59, second=59)
    
    # Create CSV file
    si = StringIO()
    csv_writer = csv.writer(si)
    
    # Write header
    csv_writer.writerow([
        'Employee', 'Job Title', 'Location', 'Total Hours', 
        'Regular Hours', 'Overtime Hours', 'Weekend Hours',
        'Regular Pay', 'Overtime Pay', 'Weekend Pay', 'Total Pay'
    ])
    
    # Track group totals
    total_regular_hours = 0
    total_overtime_hours = 0
    total_weekend_hours = 0
    total_regular_pay = 0
    total_overtime_pay = 0
    total_weekend_pay = 0
    total_pay = 0
    
    # Write data for each employee in the group
    for employee in group.employees:
        if not employee.is_active:
            continue
            
        # Query timesheets within date range
        timesheets = Timesheet.query.filter(
            Timesheet.employee_id == employee.id,
            Timesheet.clock_in >= start_date,
            Timesheet.clock_in < end_date,
            Timesheet.clock_out != None  # Only include completed timesheets
        ).all()
        
        if not timesheets:
            continue  # Skip employees with no timesheets in this period
        
        # Calculate totals for this employee
        employee_regular_hours = 0
        employee_overtime_hours = 0
        employee_weekend_hours = 0
        employee_regular_pay = 0
        employee_overtime_pay = 0
        employee_weekend_pay = 0
        
        for ts in timesheets:
            if ts.clock_out:
                pay_breakdown = ts.calculate_pay_breakdown()
                
                employee_regular_hours += pay_breakdown['regular_hours']
                employee_overtime_hours += pay_breakdown['overtime_hours']
                employee_weekend_hours += pay_breakdown['weekend_hours']
                employee_regular_pay += pay_breakdown['regular_pay']
                employee_overtime_pay += pay_breakdown['overtime_pay']
                employee_weekend_pay += pay_breakdown['weekend_pay']
        
        employee_total_hours = employee_regular_hours + employee_overtime_hours + employee_weekend_hours
        employee_total_pay = employee_regular_pay + employee_overtime_pay + employee_weekend_pay
        
        # Write row for this employee
        csv_writer.writerow([
            f"{employee.first_name} {employee.last_name}",
            employee.job_title.title if employee.job_title else "-",
            employee.location.name if employee.location else "-",
            f"{employee_total_hours:.2f}",
            f"{employee_regular_hours:.2f}",
            f"{employee_overtime_hours:.2f}",
            f"{employee_weekend_hours:.2f}",
            f"${employee_regular_pay:.2f}",
            f"${employee_overtime_pay:.2f}",
            f"${employee_weekend_pay:.2f}",
            f"${employee_total_pay:.2f}"
        ])
        
        # Add to group totals
        total_regular_hours += employee_regular_hours
        total_overtime_hours += employee_overtime_hours
        total_weekend_hours += employee_weekend_hours
        total_regular_pay += employee_regular_pay
        total_overtime_pay += employee_overtime_pay
        total_weekend_pay += employee_weekend_pay
        total_pay += employee_total_pay
    
    # Write totals
    csv_writer.writerow([])
    csv_writer.writerow([
        'TOTALS', '', '', 
        f'{(total_regular_hours + total_overtime_hours + total_weekend_hours):.2f}', 
        f'{total_regular_hours:.2f}', 
        f'{total_overtime_hours:.2f}',
        f'{total_weekend_hours:.2f}',
        f'${total_regular_pay:.2f}',
        f'${total_overtime_pay:.2f}',
        f'${total_weekend_pay:.2f}',
        f'${total_pay:.2f}'
    ])
    
    # Prepare response
    output = si.getvalue()
    formatted_start = start_date.strftime('%Y%m%d')
    formatted_end = (end_date - timedelta(days=1)).strftime('%Y%m%d')
    filename = f"{current_user.company.name}_{group.name}_timesheets_{formatted_start}_to_{formatted_end}.csv"
    
    return output, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }

@app.route('/rate_functions')
@login_required
def rate_functions():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company = current_user.company
    functions = RateFunction.query.filter_by(company_id=company.id).all()
    return render_template('rate_functions.html', functions=functions)

@app.route('/add_rate_function', methods=['GET', 'POST'])
@login_required
def add_rate_function():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        weekday_formula = request.form.get('weekday_formula')
        weekend_formula = request.form.get('weekend_formula')
        
        # Validate formulas
        try:
            # Create test data to validate the formulas
            test_env = {'base': 15.0, 'overtime': 22.50, 'weekend': 25.0}
            
            # Try to evaluate the weekday formula
            weekday_result = eval(weekday_formula, {"__builtins__": {}}, test_env)
            if not isinstance(weekday_result, (int, float)):
                raise ValueError("Weekday formula must return a number")
                
            # Try to evaluate the weekend formula
            weekend_result = eval(weekend_formula, {"__builtins__": {}}, test_env)
            if not isinstance(weekend_result, (int, float)):
                raise ValueError("Weekend formula must return a number")
            
            # Create the rate function
            function = RateFunction(
                name=name,
                description=description,
                weekday_formula=weekday_formula,
                weekend_formula=weekend_formula,
                company_id=current_user.company.id
            )
            
            db.session.add(function)
            db.session.commit()
            
            flash('Rate function added successfully!')
            return redirect(url_for('rate_functions'))
            
        except Exception as e:
            flash(f'Error in formula: {str(e)}')
    
    return render_template('add_rate_function.html')

@app.route('/edit_rate_function/<int:function_id>', methods=['GET', 'POST'])
@login_required
def edit_rate_function(function_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    function = RateFunction.query.get_or_404(function_id)
    
    # Make sure the function belongs to the current user's company
    if function.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('rate_functions'))
    
    if request.method == 'POST':
        function.name = request.form.get('name')
        function.description = request.form.get('description')
        weekday_formula = request.form.get('weekday_formula')
        weekend_formula = request.form.get('weekend_formula')
        
        # Validate formulas
        try:
            # Create test data to validate the formulas
            test_env = {'base': 15.0, 'overtime': 22.50, 'weekend': 25.0}
            
            # Try to evaluate the weekday formula
            weekday_result = eval(weekday_formula, {"__builtins__": {}}, test_env)
            if not isinstance(weekday_result, (int, float)):
                raise ValueError("Weekday formula must return a number")
                
            # Try to evaluate the weekend formula
            weekend_result = eval(weekend_formula, {"__builtins__": {}}, test_env)
            if not isinstance(weekend_result, (int, float)):
                raise ValueError("Weekend formula must return a number")
                
            function.weekday_formula = weekday_formula
            function.weekend_formula = weekend_formula
            
            db.session.commit()
            
            flash('Rate function updated successfully!')
            return redirect(url_for('rate_functions'))
            
        except Exception as e:
            flash(f'Error in formula: {str(e)}')
    
    return render_template('edit_rate_function.html', function=function)

@app.route('/delete_rate_function/<int:function_id>')
@login_required
def delete_rate_function(function_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    function = RateFunction.query.get_or_404(function_id)
    
    # Make sure the function belongs to the current user's company
    if function.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('rate_functions'))
    
    # Check if any employees are using this function
    employees_count = Employee.query.filter_by(rate_function_id=function_id).count()
    if employees_count > 0:
        flash(f'Cannot delete: This rate function is used by {employees_count} employees.')
        return redirect(url_for('rate_functions'))
    
    db.session.delete(function)
    db.session.commit()
    
    flash('Rate function deleted successfully!')
    return redirect(url_for('rate_functions'))

@app.route('/bulk_update_pay_rates', methods=['GET', 'POST'])
@login_required
def bulk_update_pay_rates():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company = current_user.company
    job_titles = JobTitle.query.filter_by(company_id=company.id).all()
    rate_functions = RateFunction.query.filter_by(company_id=company.id).all()
    
    if request.method == 'POST':
        job_title_id = request.form.get('job_title_id')
        hourly_rate = float(request.form.get('hourly_rate'))
        overtime_rate = float(request.form.get('overtime_rate'))
        weekend_rate = float(request.form.get('weekend_rate'))
        rate_function_id = request.form.get('rate_function_id', '')
        
        # Night shift options
        is_night_worker = 'is_night_worker' in request.form
        night_shift_allowance = request.form.get('night_shift_allowance', '')
        if night_shift_allowance != '':
            night_shift_allowance = float(night_shift_allowance)
        else:
            night_shift_allowance = company.default_night_allowance
        
        if rate_function_id == '':
            rate_function_id = None
        else:
            rate_function_id = int(rate_function_id)
            
        if job_title_id:
            # Find all active employees with this job title
            employees = Employee.query.filter_by(
                company_id=company.id,
                job_title_id=job_title_id,
                is_active=True
            ).all()
            
            count = 0
            for employee in employees:
                employee.hourly_rate = hourly_rate
                employee.overtime_rate = overtime_rate
                employee.weekend_rate = weekend_rate
                employee.rate_function_id = rate_function_id
                employee.is_night_worker = is_night_worker
                employee.night_shift_allowance = night_shift_allowance
                count += 1
            
            db.session.commit()
            
            job_title = JobTitle.query.get(job_title_id)
            flash(f'Updated pay rates for {count} employees with job title "{job_title.title}"')
            return redirect(url_for('employees'))
    
    return render_template('bulk_update_pay_rates.html', job_titles=job_titles, rate_functions=rate_functions)

@app.route('/get_employees_by_job_title/<int:job_title_id>')
@login_required
def get_employees_by_job_title(job_title_id):
    if not current_user.is_admin:
        return jsonify({'employees': []})
    
    # Verify that the job title belongs to the current user's company
    job_title = JobTitle.query.get_or_404(job_title_id)
    if job_title.company_id != current_user.company.id:
        return jsonify({'employees': []})
    
    # Get all active employees with this job title
    employees = Employee.query.filter_by(
        company_id=current_user.company.id,
        job_title_id=job_title_id,
        is_active=True
    ).all()
    
    # Format employee data for JSON response
    employee_data = []
    for employee in employees:
        employee_data.append({
            'id': employee.id,
            'name': f"{employee.first_name} {employee.last_name}",
            'hourly_rate': employee.hourly_rate,
            'overtime_rate': employee.overtime_rate
        })
    
    return jsonify({'employees': employee_data})

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        company_name = request.form.get('company_name')
        standard_hours = int(request.form.get('standard_hours', 40))
        
        # Check if username or email already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return redirect(url_for('register'))
        
        # Create company
        company = Company(name=company_name, standard_hours=standard_hours)
        db.session.add(company)
        db.session.flush()  # To get company ID
        
        # Create user
        user = User(username=username, email=email, company_id=company.id, is_admin=True)
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

# Create the database if it doesn't exist
@app.before_first_request
def create_tables():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)