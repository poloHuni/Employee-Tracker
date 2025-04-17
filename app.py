from flask import Flask, send_file, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import csv
import calendar as cal_module
from io import StringIO, BytesIO
import pandas as pd
from werkzeug.utils import secure_filename
from io import BytesIO
from datetime import datetime, timedelta, time
import re

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
    default_night_allowance = db.Column(db.Float, default=0.1)  # Default night shift allowance
    default_work_start_time = db.Column(db.Time, default=time(9, 0))  # Default: 9:00 AM
    default_work_end_time = db.Column(db.Time, default=time(17, 0))  # Default: 5:00 PM
    enforce_work_hours = db.Column(db.Boolean, default=False)  # Whether to enforce work hours
    users = db.relationship('User', backref='company', lazy=True)
    employees = db.relationship('Employee', backref='company', lazy=True)
    job_titles = db.relationship('JobTitle', backref='company', lazy=True)
    locations = db.relationship('Location', backref='company', lazy=True)
    groups = db.relationship('EmployeeGroup', backref='company', lazy=True)
    
    def get_work_hours(self):
        """Get default company work hours"""
        return {
            'start': self.default_work_start_time,
            'end': self.default_work_end_time,
            'enforce': self.enforce_work_hours
        }

class JobTitle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    work_start_time = db.Column(db.Time, nullable=True)  # Custom start time, NULL means use company default
    work_end_time = db.Column(db.Time, nullable=True)    # Custom end time, NULL means use company default
    employees = db.relationship('Employee', backref='job_title', lazy=True)
    
    def get_work_hours(self):
        """Get job title work hours (falls back to company default if not set)"""
        company_hours = self.company.get_work_hours()
        return {
            'start': self.work_start_time or company_hours['start'],
            'end': self.work_end_time or company_hours['end'],
            'enforce': company_hours['enforce']
        }
    
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
    is_sunday_worker = db.Column(db.Boolean, default=False)  # Field for Sunday workers
    is_holiday_worker = db.Column(db.Boolean, default=False)  # Field for holiday workers
    is_night_worker = db.Column(db.Boolean, default=False)  # Field for night shift workers
    night_shift_allowance = db.Column(db.Float, default=0.1)  # Allowance rate for night shifts
    timesheets = db.relationship('Timesheet', backref='employee', lazy=True)
    is_active = db.Column(db.Boolean, default=True)
    work_start_time = db.Column(db.Time, nullable=True)  # Custom start time, NULL means use job title or company default
    work_end_time = db.Column(db.Time, nullable=True)    # Custom end time, NULL means use job title or company default
    
    def get_work_hours(self):
        """Get employee work hours (falls back to job title or company default if not set)"""
        company_hours = self.company.get_work_hours()
        
        if self.job_title_id:
            job_hours = self.job_title.get_work_hours()
        else:
            job_hours = company_hours
            
        # Check if employee is in any groups with set work hours
        group_hours = None
        for group in self.groups:
            if group.work_start_time and group.work_end_time:
                group_hours = {
                    'start': group.work_start_time,
                    'end': group.work_end_time,
                    'enforce': company_hours['enforce']
                }
                break  # Use the first group with set hours
        
        return {
            'start': self.work_start_time or (group_hours['start'] if group_hours else job_hours['start']),
            'end': self.work_end_time or (group_hours['end'] if group_hours else job_hours['end']),
            'enforce': company_hours['enforce']
        }

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
        """Calculate hours worked, adjusted for work hours if enforced"""
        if self.clock_out:
            if self.employee.company.enforce_work_hours:
                return self.calculate_adjusted_hours()
            else:
                duration = self.clock_out - self.clock_in
                return duration.total_seconds() / 3600
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
    
    def is_holiday(self):
        """Check if this timesheet falls on a company holiday"""
        # First check if it's already marked as a public holiday
        if self.is_public_holiday:
            return True
            
        # Then check the holiday table
        timesheet_date = self.clock_in.date()
        holiday = Holiday.query.filter_by(
            company_id=self.employee.company_id,
            date=timesheet_date
        ).first()
        
        return holiday is not None and holiday.is_paid
    
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
        
        # Holiday calculation has highest priority (includes both manually marked public holidays and holidays from the calendar)
        if self.is_holiday():
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
    
    def calculate_adjusted_hours(self):
        """Calculate hours worked adjusted for work hours if enforced."""
        if not self.clock_out:
            return 0
            
        employee = self.employee
        work_hours = employee.get_work_hours()
        
        # If work hours are not enforced, return total time
        if not work_hours['enforce']:
            duration = self.clock_out - self.clock_in
            return duration.total_seconds() / 3600
        
        # Get clock-in and clock-out dates and times
        clock_in_date = self.clock_in.date()
        clock_in_time = self.clock_in.time()
        clock_out_date = self.clock_out.date()
        clock_out_time = self.clock_out.time()
        
        # Get work hours for each day
        work_start = work_hours['start']
        work_end = work_hours['end']
        
        # If shift is within the same day
        if clock_in_date == clock_out_date:
            # Create datetime objects for work start and end times on this day
            work_start_dt = datetime.combine(clock_in_date, work_start)
            work_end_dt = datetime.combine(clock_in_date, work_end)
            
            # Adjust clock-in time if before work hours
            adjusted_clock_in = max(self.clock_in, work_start_dt)
            
            # Adjust clock-out time if after work hours
            adjusted_clock_out = min(self.clock_out, work_end_dt)
            
            # Calculate adjusted duration
            if adjusted_clock_out <= adjusted_clock_in:
                return 0  # No hours if clock-out is before or at clock-in
                
            duration = adjusted_clock_out - adjusted_clock_in
            return duration.total_seconds() / 3600
        
        # If shift spans multiple days
        total_hours = 0
        
        # Day 1: Calculate hours from clock-in to end of work day
        day1_work_end = datetime.combine(clock_in_date, work_end)
        day1_adjusted_start = max(self.clock_in, datetime.combine(clock_in_date, work_start))
        if day1_work_end > day1_adjusted_start:
            total_hours += (day1_work_end - day1_adjusted_start).total_seconds() / 3600
        
        # Middle days (if any)
        current_date = clock_in_date + timedelta(days=1)
        while current_date < clock_out_date:
            # Full work day
            day_start = datetime.combine(current_date, work_start)
            day_end = datetime.combine(current_date, work_end)
            total_hours += (day_end - day_start).total_seconds() / 3600
            current_date += timedelta(days=1)
        
        # Last day: Calculate hours from start of work day to clock-out
        last_day_work_start = datetime.combine(clock_out_date, work_start)
        last_day_adjusted_end = min(self.clock_out, datetime.combine(clock_out_date, work_end))
        if last_day_adjusted_end > last_day_work_start:
            total_hours += (last_day_adjusted_end - last_day_work_start).total_seconds() / 3600
        
        return total_hours
    
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
        
        # Holiday calculation (includes both manually marked public holidays and holidays from the calendar)
        if self.is_holiday():
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

class Holiday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_paid = db.Column(db.Boolean, default=True)  # Whether it's a paid holiday
    
    company = db.relationship('Company', backref='holidays')
    
    # Add a unique constraint for company_id and date
    __table_args__ = (db.UniqueConstraint('company_id', 'date', name='_company_date_uc'),)
    
    def __repr__(self):
        return f'<Holiday {self.name} on {self.date}>'


class EmployeeGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    work_start_time = db.Column(db.Time, nullable=True)  # Custom start time for the group
    work_end_time = db.Column(db.Time, nullable=True)    # Custom end time for the group
    
    # Criteria for automatically adding employees to this group
    job_title_id = db.Column(db.Integer, db.ForeignKey('job_title.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    
    # Relationships
    job_title = db.relationship('JobTitle', backref='groups', foreign_keys=[job_title_id])
    location = db.relationship('Location', backref='groups', foreign_keys=[location_id])
    employees = db.relationship('Employee', secondary='employee_group_membership', backref='groups')
    
    def get_work_hours(self):
        """Get group work hours (falls back to company default if not set)"""
        company_hours = self.company.get_work_hours()
        return {
            'start': self.work_start_time or company_hours['start'],
            'end': self.work_end_time or company_hours['end'],
            'enforce': company_hours['enforce']
        }

# Make sure this table is defined in app.py:
employee_group_membership = db.Table('employee_group_membership',
    db.Column('employee_id', db.Integer, db.ForeignKey('employee.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('employee_group.id'), primary_key=True)
)

class ColumnSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    view_type = db.Column(db.String(50), nullable=False)  # 'dashboard', 'employee_timesheet', 'group_timesheet'
    column_name = db.Column(db.String(50), nullable=False)
    display_name = db.Column(db.String(100))
    is_visible = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)
    
    company = db.relationship('Company', backref='column_settings')
    
    __table_args__ = (db.UniqueConstraint('company_id', 'view_type', 'column_name', name='_company_view_column_uc'),)
    
    @staticmethod
    def get_default_columns(view_type):
        """Get the default columns for a specific view type"""
        if view_type == 'dashboard':
            return [
                {'name': 'name', 'display': 'Name', 'order': 1, 'visible': True},
                {'name': 'email', 'display': 'Email', 'order': 2, 'visible': True},
                {'name': 'pay_rate', 'display': 'Pay Rate', 'order': 3, 'visible': True},
                {'name': 'special_status', 'display': 'Special Status', 'order': 4, 'visible': True},
                {'name': 'status', 'display': 'Status', 'order': 5, 'visible': True},
                {'name': 'actions', 'display': 'Actions', 'order': 6, 'visible': True}
            ]
        elif view_type == 'employee_timesheet':
            return [
                {'name': 'date', 'display': 'Date', 'order': 1, 'visible': True},
                {'name': 'clock_in', 'display': 'Clock In', 'order': 2, 'visible': True},
                {'name': 'clock_out', 'display': 'Clock Out', 'order': 3, 'visible': True},
                {'name': 'type', 'display': 'Type', 'order': 4, 'visible': True},
                {'name': 'hours', 'display': 'Hours', 'order': 5, 'visible': True},
                {'name': 'regular_hours', 'display': 'Regular', 'order': 6, 'visible': True},
                {'name': 'overtime_hours', 'display': 'Overtime', 'order': 7, 'visible': True},
                {'name': 'weekend_hours', 'display': 'Weekend', 'order': 8, 'visible': True},
                {'name': 'holiday_hours', 'display': 'Holiday', 'order': 9, 'visible': True},
                {'name': 'night_shift_hours', 'display': 'Night', 'order': 10, 'visible': True},
                {'name': 'regular_pay', 'display': 'Regular Pay', 'order': 11, 'visible': True}, 
                {'name': 'overtime_pay', 'display': 'Overtime Pay', 'order': 12, 'visible': True},
                {'name': 'weekend_pay', 'display': 'Weekend Pay', 'order': 13, 'visible': True},
                {'name': 'holiday_pay', 'display': 'Holiday Pay', 'order': 14, 'visible': True},
                {'name': 'night_shift_allowance', 'display': 'Night Allowance', 'order': 15, 'visible': True},
                {'name': 'total_pay', 'display': 'Total Pay', 'order': 16, 'visible': True}
            ]
        elif view_type == 'group_timesheet':
            return [
                {'name': 'employee', 'display': 'Employee', 'order': 1, 'visible': True},
                {'name': 'title', 'display': 'Title', 'order': 2, 'visible': True},
                {'name': 'location', 'display': 'Location', 'order': 3, 'visible': True},
                {'name': 'total_hours', 'display': 'Total Hours', 'order': 4, 'visible': True},
                {'name': 'regular_hours', 'display': 'Regular Hours', 'order': 5, 'visible': True},
                {'name': 'overtime_hours', 'display': 'Overtime Hours', 'order': 6, 'visible': True},
                {'name': 'weekend_hours', 'display': 'Weekend Hours', 'order': 7, 'visible': True},
                {'name': 'regular_pay', 'display': 'Regular Pay', 'order': 8, 'visible': True},
                {'name': 'overtime_pay', 'display': 'Overtime Pay', 'order': 9, 'visible': True},
                {'name': 'weekend_pay', 'display': 'Weekend Pay', 'order': 10, 'visible': True},
                {'name': 'total_pay', 'display': 'Total Pay', 'order': 11, 'visible': True}
            ]
        else:
            return []
    
    @staticmethod
    def initialize_for_company(company_id):
        """Initialize default column settings for a new company"""
        # Clear any existing settings
        ColumnSettings.query.filter_by(company_id=company_id).delete()
        
        # Create settings for each view type
        for view_type in ['dashboard', 'employee_timesheet', 'group_timesheet']:
            default_columns = ColumnSettings.get_default_columns(view_type)
            
            for column in default_columns:
                setting = ColumnSettings(
                    company_id=company_id,
                    view_type=view_type,
                    column_name=column['name'],
                    display_name=column['display'],
                    is_visible=column['visible'],
                    display_order=column['order']
                )
                db.session.add(setting)
        
        db.session.commit()
    
    @staticmethod
    def get_visible_columns(company_id, view_type):
        """Get visible columns for a company and view type, sorted by display order"""
        settings = ColumnSettings.query.filter_by(
            company_id=company_id,
            view_type=view_type,
            is_visible=True
        ).order_by(ColumnSettings.display_order).all()
        
        # If no settings exist for this company, initialize with defaults
        if not settings:
            ColumnSettings.initialize_for_company(company_id)
            settings = ColumnSettings.query.filter_by(
                company_id=company_id,
                view_type=view_type,
                is_visible=True
            ).order_by(ColumnSettings.display_order).all()
            
        return settings


class CustomField(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    field_type = db.Column(db.String(50), nullable=False)  # text, number, boolean, date, select
    is_required = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text)
    
    company = db.relationship('Company', backref='custom_fields')
    
    __table_args__ = (db.UniqueConstraint('company_id', 'name', name='_company_custom_field_uc'),)

class CustomFieldValue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    custom_field_id = db.Column(db.Integer, db.ForeignKey('custom_field.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    text_value = db.Column(db.Text)
    number_value = db.Column(db.Float)
    boolean_value = db.Column(db.Boolean)
    date_value = db.Column(db.Date)
    
    custom_field = db.relationship('CustomField')
    employee = db.relationship('Employee', backref='custom_field_values')
    
    __table_args__ = (db.UniqueConstraint('custom_field_id', 'employee_id', name='_field_employee_uc'),)

class ImportConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    field_name = db.Column(db.String(100), nullable=False)
    is_standard = db.Column(db.Boolean, default=True)
    is_required = db.Column(db.Boolean, default=False)
    
    company = db.relationship('Company', backref='import_configs')
    
    __table_args__ = (db.UniqueConstraint('company_id', 'field_name', name='_company_field_name_uc'),)

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
    
    # Get custom fields for the company
    custom_fields = CustomField.query.filter_by(company_id=company.id).all()
    
    # Get column settings for dashboard
    dashboard_columns = ColumnSettings.get_visible_columns(company.id, 'dashboard')
    
    # Add custom fields as available columns if they don't exist already
    for field in custom_fields:
        # Check if a column for this custom field already exists
        column_name = f"custom_{field.id}"
        existing = ColumnSettings.query.filter_by(
            company_id=company.id,
            view_type='dashboard',
            column_name=column_name
        ).first()
        
        if not existing:
            # Create a new column setting for this custom field
            new_column = ColumnSettings(
                company_id=company.id,
                view_type='dashboard',
                column_name=column_name,
                display_name=field.name,
                is_visible=False,  # Hidden by default
                display_order=100  # Add at the end
            )
            db.session.add(new_column)
    
    # Commit any new columns
    if custom_fields:
        db.session.commit()
    
    return render_template('dashboard.html', 
                          company=company, 
                          employees=active_employees, 
                          active_timesheets=active_timesheets,
                          month_names=month_names,
                          current_month=current_month,
                          current_year=current_year,
                          weekly_hours=weekly_hours,
                          week_start_date=week_start.date(),
                          week_end_date=week_end.date(),
                          dashboard_columns=dashboard_columns,
                          custom_fields=custom_fields)

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

@app.template_filter('date_format')
def date_format(value):
    """Format date as YYYY-MM-DD for input fields"""
    if value:
        return value.strftime('%Y-%m-%d')
    return ''

def get_custom_value(employee, field_id, value_type):
    """Get a custom field value for an employee
    
    Args:
        employee: Employee object
        field_id: ID of the custom field
        value_type: Type of value to retrieve ('text', 'number', 'boolean', 'date')
        
    Returns:
        The value of the specified type, or None if not found
    """
    field_value = CustomFieldValue.query.filter_by(
        employee_id=employee.id,
        custom_field_id=field_id
    ).first()
    
    if not field_value:
        return None
    
    if value_type == 'text':
        return field_value.text_value
    elif value_type == 'number':
        return field_value.number_value
    elif value_type == 'boolean':
        return field_value.boolean_value
    elif value_type == 'date':
        return field_value.date_value
    
    return None

# Register the get_custom_value function to be available in templates
app.jinja_env.globals['get_custom_value'] = get_custom_value

@app.route('/employee_details/<int:employee_id>')
@login_required
def employee_details(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    
    # Make sure the employee belongs to the current user's company
    if employee.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Get custom fields for this employee
    custom_fields = CustomField.query.filter_by(company_id=current_user.company.id).all()
    
    # Get recent timesheets (last 5)
    recent_timesheets = Timesheet.query.filter_by(employee_id=employee.id)\
        .filter(Timesheet.clock_out != None)\
        .order_by(Timesheet.clock_in.desc())\
        .limit(5)\
        .all()
    
    return render_template('employee_details.html', 
                          employee=employee,
                          custom_fields=custom_fields,
                          recent_timesheets=recent_timesheets)

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
        
        # Handle work hours settings
        company.enforce_work_hours = 'enforce_work_hours' in request.form
        
        start_time = request.form.get('default_work_start_time')
        if start_time:
            hour, minute = map(int, start_time.split(':'))
            company.default_work_start_time = time(hour, minute)
            
        end_time = request.form.get('default_work_end_time')
        if end_time:
            hour, minute = map(int, end_time.split(':'))
            company.default_work_end_time = datetime.time(hour, minute)
        
        # Handle night shift allowance
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
    company = current_user.company
    
    # Make sure the job title belongs to the current user's company
    if job_title.company_id != company.id:
        flash('Access denied.')
        return redirect(url_for('job_titles'))
    
    if request.method == 'POST':
        job_title.title = request.form.get('title')
        job_title.description = request.form.get('description')
        
        # Handle work hours
        start_time = request.form.get('work_start_time')
        if start_time:
            hour, minute = map(int, start_time.split(':'))
            job_title.work_start_time = time(hour, minute)
        else:
            job_title.work_start_time = None
            
        end_time = request.form.get('work_end_time')
        if end_time:
            hour, minute = map(int, end_time.split(':'))
            job_title.work_end_time = datetime.time(hour, minute)
        else:
            job_title.work_end_time = None
        
        db.session.commit()
        
        flash('Job title updated successfully!')
        return redirect(url_for('job_titles'))
    
    return render_template('edit_job_title.html', job_title=job_title, company=company)

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
    
    # Get visible column settings
    timesheet_columns = ColumnSettings.get_visible_columns(current_user.company.id, 'employee_timesheet')
    
    # Prepare timesheet data with calculated hours, overtime, and weekend rates
    timesheet_data = []
    
    # Track totals
    total_hours = 0
    total_regular_hours = 0
    total_overtime_hours = 0
    total_weekend_hours = 0
    total_holiday_hours = 0
    total_night_shift_hours = 0
    total_regular_pay = 0
    total_overtime_pay = 0
    total_weekend_pay = 0
    total_holiday_pay = 0
    total_night_shift_allowance = 0
    total_pay = 0
    
    for ts in timesheets:
        if ts.clock_out:  # Only include completed timesheets
            pay_breakdown = ts.calculate_pay_breakdown()
            
            # Add up totals
            total_hours += pay_breakdown.get('regular_hours', 0) + pay_breakdown.get('overtime_hours', 0) + pay_breakdown.get('weekend_hours', 0) + pay_breakdown.get('holiday_hours', 0)
            total_regular_hours += pay_breakdown.get('regular_hours', 0)
            total_overtime_hours += pay_breakdown.get('overtime_hours', 0)
            total_weekend_hours += pay_breakdown.get('weekend_hours', 0)
            total_holiday_hours += pay_breakdown.get('holiday_hours', 0)
            total_night_shift_hours += pay_breakdown.get('night_shift_hours', 0)
            total_regular_pay += pay_breakdown.get('regular_pay', 0)
            total_overtime_pay += pay_breakdown.get('overtime_pay', 0)
            total_weekend_pay += pay_breakdown.get('weekend_pay', 0)
            total_holiday_pay += pay_breakdown.get('holiday_pay', 0)
            total_night_shift_allowance += pay_breakdown.get('night_shift_allowance', 0)
            total_pay += pay_breakdown.get('total_pay', 0)
            
            # Make sure all required keys exist in the dictionary
            timesheet_data.append({
                'id': ts.id,
                'date': ts.clock_in.strftime('%Y-%m-%d'),
                'clock_in': ts.clock_in.strftime('%H:%M'),
                'clock_out': ts.clock_out.strftime('%H:%M') if ts.clock_out else 'Active',
                'hours': pay_breakdown.get('regular_hours', 0) + pay_breakdown.get('overtime_hours', 0) + pay_breakdown.get('weekend_hours', 0) + pay_breakdown.get('holiday_hours', 0),
                'regular_hours': pay_breakdown.get('regular_hours', 0),
                'overtime_hours': pay_breakdown.get('overtime_hours', 0),
                'weekend_hours': pay_breakdown.get('weekend_hours', 0),
                'holiday_hours': pay_breakdown.get('holiday_hours', 0),
                'night_shift_hours': pay_breakdown.get('night_shift_hours', 0),
                'regular_pay': pay_breakdown.get('regular_pay', 0),
                'overtime_pay': pay_breakdown.get('overtime_pay', 0),
                'weekend_pay': pay_breakdown.get('weekend_pay', 0),
                'holiday_pay': pay_breakdown.get('holiday_pay', 0),
                'night_shift_allowance': pay_breakdown.get('night_shift_allowance', 0),
                'total_pay': pay_breakdown.get('total_pay', 0),
                'is_public_holiday': ts.is_public_holiday,
                'is_sunday': ts.is_sunday(),
                'is_saturday': ts.is_saturday(),
                'is_night_shift': ts.is_night_shift()
            })
    
    return render_template('employee_timesheets.html', 
                          employee=employee, 
                          timesheets=timesheet_data,
                          timesheet_columns=timesheet_columns,
                          total_hours=total_hours,
                          total_regular_hours=total_regular_hours,
                          total_overtime_hours=total_overtime_hours,
                          total_weekend_hours=total_weekend_hours,
                          total_holiday_hours=total_holiday_hours,
                          total_night_shift_hours=total_night_shift_hours,
                          total_regular_pay=total_regular_pay,
                          total_overtime_pay=total_overtime_pay,
                          total_weekend_pay=total_weekend_pay,
                          total_holiday_pay=total_holiday_pay,
                          total_night_shift_allowance=total_night_shift_allowance,
                          total_pay=total_pay)

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
    _, last_day = cal_module.monthrange(year, month)  # Use cal_module instead of calendar
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
    month_name = cal_module.month_name[month]  # Use cal_module instead of calendar
    filename = f"{current_user.company.name}_timesheets_{month_name}_{year}.csv"
    
    return output, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }

@app.route('/employee_groups')
@login_required
def employee_groups():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company = current_user.company
    groups = EmployeeGroup.query.filter_by(company_id=company.id).all()
    return render_template('employee_groups.html', groups=groups)

# Updated routes for employee groups with custom field support

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
    
    # Get custom fields
    custom_fields = CustomField.query.filter_by(company_id=current_user.company.id).all()
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        job_title_id = request.form.get('job_title_id')
        location_id = request.form.get('location_id')
        worker_type = request.form.get('worker_type')
        min_rate = request.form.get('min_rate')
        max_rate = request.form.get('max_rate')
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
        
        # Build query for filtering based on standard and custom fields
        employee_query = Employee.query.filter_by(company_id=current_user.company.id, is_active=True)
        
        # Apply job title filter
        if job_title_id:
            employee_query = employee_query.filter_by(job_title_id=job_title_id)
        
        # Apply location filter
        if location_id:
            employee_query = employee_query.filter_by(location_id=location_id)
        
        # Apply worker type filter
        if worker_type:
            if worker_type == 'sunday_worker':
                employee_query = employee_query.filter_by(is_sunday_worker=True)
            elif worker_type == 'holiday_worker':
                employee_query = employee_query.filter_by(is_holiday_worker=True)
            elif worker_type == 'night_worker':
                employee_query = employee_query.filter_by(is_night_worker=True)
            elif worker_type == 'regular_worker':
                employee_query = employee_query.filter_by(is_sunday_worker=False, is_holiday_worker=False, is_night_worker=False)
        
        # Apply pay rate range filter
        if min_rate and min_rate.strip():
            employee_query = employee_query.filter(Employee.hourly_rate >= float(min_rate))
        if max_rate and max_rate.strip():
            employee_query = employee_query.filter(Employee.hourly_rate <= float(max_rate))
        
        # Get employees matching basic filters
        filtered_employees = employee_query.all()
        
        # Apply custom field filters (need to be done in Python as SQLAlchemy doesn't handle it well)
        for field in custom_fields:
            field_filter = request.form.get(f'custom_filter_{field.id}')
            
            if field_filter and field_filter.strip():
                filter_op = request.form.get(f'custom_filter_op_{field.id}', 'eq')
                
                # Further filter the employees
                if field.field_type == 'text' or field.field_type == 'select':
                    # Text matching filter
                    filtered_employees = [
                        e for e in filtered_employees if 
                        has_matching_text_value(e, field.id, field_filter)
                    ]
                elif field.field_type == 'number':
                    # Numeric comparison
                    try:
                        filter_value = float(field_filter)
                        if filter_op == 'eq':
                            filtered_employees = [
                                e for e in filtered_employees if 
                                has_matching_number_value(e, field.id, filter_value, '==')
                            ]
                        elif filter_op == 'gt':
                            filtered_employees = [
                                e for e in filtered_employees if 
                                has_matching_number_value(e, field.id, filter_value, '>')
                            ]
                        elif filter_op == 'lt':
                            filtered_employees = [
                                e for e in filtered_employees if 
                                has_matching_number_value(e, field.id, filter_value, '<')
                            ]
                        elif filter_op == 'between':
                            max_value = request.form.get(f'custom_filter_max_{field.id}')
                            if max_value and max_value.strip():
                                max_value = float(max_value)
                                filtered_employees = [
                                    e for e in filtered_employees if 
                                    has_matching_number_value(e, field.id, filter_value, '>=') and
                                    has_matching_number_value(e, field.id, max_value, '<=')
                                ]
                    except ValueError:
                        # Skip invalid number
                        pass
                elif field.field_type == 'boolean':
                    # Boolean filter
                    if field_filter == 'true':
                        filtered_employees = [
                            e for e in filtered_employees if 
                            has_matching_boolean_value(e, field.id, True)
                        ]
                    elif field_filter == 'false':
                        filtered_employees = [
                            e for e in filtered_employees if 
                            has_matching_boolean_value(e, field.id, False)
                        ]
                elif field.field_type == 'date':
                    # Date comparison
                    try:
                        filter_date = datetime.strptime(field_filter, '%Y-%m-%d').date()
                        if filter_op == 'eq':
                            filtered_employees = [
                                e for e in filtered_employees if 
                                has_matching_date_value(e, field.id, filter_date, '==')
                            ]
                        elif filter_op == 'before':
                            filtered_employees = [
                                e for e in filtered_employees if 
                                has_matching_date_value(e, field.id, filter_date, '<')
                            ]
                        elif filter_op == 'after':
                            filtered_employees = [
                                e for e in filtered_employees if 
                                has_matching_date_value(e, field.id, filter_date, '>')
                            ]
                        elif filter_op == 'between':
                            max_date_str = request.form.get(f'custom_filter_max_{field.id}')
                            if max_date_str and max_date_str.strip():
                                max_date = datetime.strptime(max_date_str, '%Y-%m-%d').date()
                                filtered_employees = [
                                    e for e in filtered_employees if 
                                    has_matching_date_value(e, field.id, filter_date, '>=') and
                                    has_matching_date_value(e, field.id, max_date, '<=')
                                ]
                    except ValueError:
                        # Skip invalid date
                        pass
        
        # Add filtered employees to the group
        for employee in filtered_employees:
            if employee not in group.employees:
                group.employees.append(employee)
        
        # Add manually selected employees
        if selected_employees:
            for employee_id in selected_employees:
                employee = Employee.query.get(int(employee_id))
                if employee and employee.company_id == current_user.company.id and employee not in group.employees:
                    group.employees.append(employee)
        
        db.session.commit()
        
        flash(f'Employee group "{name}" created successfully with {len(group.employees)} employees!')
        return redirect(url_for('employee_groups'))
    
    return render_template('add_employee_group.html', 
                          job_titles=job_titles, 
                          locations=locations,
                          employees=employees,
                          custom_fields=custom_fields)

# Helper functions for custom field comparison
def has_matching_text_value(employee, field_id, filter_text):
    """Check if employee has a matching text value for the given custom field"""
    field_value = CustomFieldValue.query.filter_by(
        employee_id=employee.id,
        custom_field_id=field_id
    ).first()
    
    if not field_value or field_value.text_value is None:
        return False
    
    return filter_text.lower() in field_value.text_value.lower()

def has_matching_number_value(employee, field_id, filter_value, operator):
    """Check if employee has a matching number value for the given custom field"""
    field_value = CustomFieldValue.query.filter_by(
        employee_id=employee.id,
        custom_field_id=field_id
    ).first()
    
    if not field_value or field_value.number_value is None:
        return False
    
    if operator == '==':
        return field_value.number_value == filter_value
    elif operator == '>':
        return field_value.number_value > filter_value
    elif operator == '<':
        return field_value.number_value < filter_value
    elif operator == '>=':
        return field_value.number_value >= filter_value
    elif operator == '<=':
        return field_value.number_value <= filter_value
    
    return False

def has_matching_boolean_value(employee, field_id, filter_value):
    """Check if employee has a matching boolean value for the given custom field"""
    field_value = CustomFieldValue.query.filter_by(
        employee_id=employee.id,
        custom_field_id=field_id
    ).first()
    
    if not field_value:
        return False
    
    return field_value.boolean_value == filter_value

def has_matching_date_value(employee, field_id, filter_date, operator):
    """Check if employee has a matching date value for the given custom field"""
    field_value = CustomFieldValue.query.filter_by(
        employee_id=employee.id,
        custom_field_id=field_id
    ).first()
    
    if not field_value or field_value.date_value is None:
        return False
    
    if operator == '==':
        return field_value.date_value == filter_date
    elif operator == '>':
        return field_value.date_value > filter_date
    elif operator == '<':
        return field_value.date_value < filter_date
    elif operator == '>=':
        return field_value.date_value >= filter_date
    elif operator == '<=':
        return field_value.date_value <= filter_date
    
    return False

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
    
    # Get custom fields
    custom_fields = CustomField.query.filter_by(company_id=current_user.company.id).all()
    
    if request.method == 'POST':
        # Update standard fields
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
        
        # Work hours settings
        start_time = request.form.get('work_start_time')
        if start_time:
            hour, minute = map(int, start_time.split(':'))
            employee.work_start_time = time(hour, minute)
        else:
            employee.work_start_time = None
            
        end_time = request.form.get('work_end_time')
        if end_time:
            hour, minute = map(int, end_time.split(':'))
            employee.work_end_time = time(hour, minute)
        else:
            employee.work_end_time = None
        
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
        
        # Handle custom fields
        for field in custom_fields:
            field_key = f'custom_{field.id}'
            field_value = CustomFieldValue.query.filter_by(
                employee_id=employee.id,
                custom_field_id=field.id
            ).first()
            
            # Create a new value if it doesn't exist
            if not field_value:
                field_value = CustomFieldValue(
                    employee_id=employee.id,
                    custom_field_id=field.id
                )
                db.session.add(field_value)
            
            # Update the value based on field type
            if field.field_type == 'text' or field.field_type == 'select':
                field_value.text_value = request.form.get(field_key, '')
            elif field.field_type == 'number':
                try:
                    field_value.number_value = float(request.form.get(field_key, 0))
                except ValueError:
                    field_value.number_value = 0
            elif field.field_type == 'boolean':
                field_value.boolean_value = field_key in request.form
            elif field.field_type == 'date':
                date_str = request.form.get(field_key, '')
                if date_str:
                    try:
                        field_value.date_value = datetime.strptime(date_str, '%Y-%m-%d').date()
                    except ValueError:
                        field_value.date_value = None
                else:
                    field_value.date_value = None
        
        db.session.commit()
        
        flash('Employee updated successfully!')
        return redirect(url_for('employees'))
    
    return render_template('edit_employee.html', 
                          employee=employee, 
                          job_titles=job_titles, 
                          locations=locations, 
                          rate_functions=rate_functions,
                          custom_fields=custom_fields,
                          company=current_user.company)

@app.route('/edit_employee_group/<int:group_id>', methods=['GET', 'POST'])
@login_required
def edit_employee_group(group_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    group = EmployeeGroup.query.get_or_404(group_id)
    company = current_user.company
    
    # Make sure the group belongs to the current user's company
    if group.company_id != company.id:
        flash('Access denied.')
        return redirect(url_for('employee_groups'))
    
    # Get job titles and locations for the dropdowns
    job_titles = JobTitle.query.filter_by(company_id=company.id).all()
    locations = Location.query.filter_by(company_id=company.id).all()
    employees = Employee.query.filter_by(company_id=company.id, is_active=True).all()
    
    if request.method == 'POST':
        group.name = request.form.get('name')
        group.description = request.form.get('description')
        
        job_title_id = request.form.get('job_title_id')
        location_id = request.form.get('location_id')
        selected_employees = request.form.getlist('employees')
        auto_update = 'auto_update' in request.form
        
        # Handle work hours settings
        start_time = request.form.get('work_start_time')
        if start_time:
            hour, minute = map(int, start_time.split(':'))
            group.work_start_time = time(hour, minute)
        else:
            group.work_start_time = None
            
        end_time = request.form.get('work_end_time')
        if end_time:
            hour, minute = map(int, end_time.split(':'))
            group.work_end_time = datetime.time(hour, minute)
        else:
            group.work_end_time = None
        
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
                if employee and employee.company_id == company.id:
                    group.employees.append(employee)
        
        # Automatically add employees based on criteria if auto-update is enabled
        if auto_update and (group.job_title_id or group.location_id):
            query = Employee.query.filter_by(company_id=company.id, is_active=True)
            
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
                          company=company,
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
    
    # Get company for settings
    company = current_user.company
    
    # Get column settings for group timesheets
    group_columns = ColumnSettings.get_visible_columns(company.id, 'group_timesheet')
    
    # Prepare data for each employee in the group
    employee_data = []
    total_regular_hours = 0
    total_overtime_hours = 0
    total_weekend_hours = 0
    total_regular_pay = 0
    total_overtime_pay = 0
    total_weekend_pay = 0
    total_pay = 0
    
    # Get all employees in the group
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
        
        # Add to employee data list - include all employees, even those with 0 hours
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
        
        # Only add to group totals for employees with hours
        if employee_total_hours > 0:
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
                          company=company,
                          employee_data=employee_data,
                          start_date=formatted_start,
                          end_date=formatted_end,
                          group_columns=group_columns,
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
        
        # Initialize column settings for the new company
        ColumnSettings.initialize_for_company(company.id)
        
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/holidays')
@login_required
def holidays():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company = current_user.company
    
    # Get start and end year from query parameters or default to current year
    current_year = datetime.now().year
    start_year = request.args.get('start_year', current_year, type=int)
    end_year = request.args.get('end_year', current_year, type=int)
    
    # Ensure start_year is not after end_year
    if start_year > end_year:
        start_year = end_year
    
    # Get all holidays for the company within the selected years
    start_date = datetime(start_year, 1, 1)
    end_date = datetime(end_year, 12, 31)
    
    holidays = Holiday.query.filter_by(company_id=company.id) \
        .filter(Holiday.date >= start_date) \
        .filter(Holiday.date <= end_date) \
        .order_by(Holiday.date) \
        .all()
    
    # Group holidays by year and month for easier display
    holidays_by_month = {}
    
    for holiday in holidays:
        year = holiday.date.year
        month = holiday.date.month
        
        if year not in holidays_by_month:
            holidays_by_month[year] = {}
            
        if month not in holidays_by_month[year]:
            holidays_by_month[year][month] = []
            
        holidays_by_month[year][month].append(holiday)
    
    # Available years for the dropdown (current year - 2 to current year + 3)
    available_years = range(current_year - 2, current_year + 4)
    
    # Month names for display
    month_names = [
        'January', 'February', 'March', 'April', 'May', 'June', 
        'July', 'August', 'September', 'October', 'November', 'December'
    ]
    
    return render_template('holidays.html', 
                          holidays=holidays,
                          holidays_by_month=holidays_by_month,
                          start_year=start_year,
                          end_year=end_year,
                          available_years=available_years,
                          month_names=month_names,
                          current_year=current_year)

@app.route('/add_holiday', methods=['GET', 'POST'])
@login_required
def add_holiday():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        date_str = request.form.get('date')
        name = request.form.get('name')
        description = request.form.get('description')
        is_paid = 'is_paid' in request.form
        
        try:
            # Parse the date from string
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            # Check if holiday already exists on this date
            existing_holiday = Holiday.query.filter_by(
                company_id=current_user.company.id,
                date=date_obj
            ).first()
            
            if existing_holiday:
                flash(f'A holiday already exists on {date_str}: {existing_holiday.name}')
                return redirect(url_for('add_holiday'))
            
            # Create new holiday
            holiday = Holiday(
                company_id=current_user.company.id,
                date=date_obj,
                name=name,
                description=description,
                is_paid=is_paid
            )
            
            db.session.add(holiday)
            db.session.commit()
            
            flash(f'Holiday "{name}" on {date_str} added successfully!')
            return redirect(url_for('holidays'))
            
        except ValueError:
            flash('Invalid date format. Please use YYYY-MM-DD.')
    
    return render_template('add_holiday.html')

@app.route('/edit_holiday/<int:holiday_id>', methods=['GET', 'POST'])
@login_required
def edit_holiday(holiday_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    holiday = Holiday.query.get_or_404(holiday_id)
    
    # Ensure the holiday belongs to the current user's company
    if holiday.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('holidays'))
    
    if request.method == 'POST':
        date_str = request.form.get('date')
        holiday.name = request.form.get('name')
        holiday.description = request.form.get('description')
        holiday.is_paid = 'is_paid' in request.form
        
        try:
            # Parse the date from string
            new_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            # Check if another holiday already exists on this date
            if new_date != holiday.date:
                existing_holiday = Holiday.query.filter_by(
                    company_id=current_user.company.id,
                    date=new_date
                ).first()
                
                if existing_holiday and existing_holiday.id != holiday.id:
                    flash(f'Another holiday already exists on {date_str}: {existing_holiday.name}')
                    return redirect(url_for('edit_holiday', holiday_id=holiday.id))
            
            holiday.date = new_date
            db.session.commit()
            
            flash('Holiday updated successfully!')
            return redirect(url_for('holidays'))
            
        except ValueError:
            flash('Invalid date format. Please use YYYY-MM-DD.')
    
    return render_template('edit_holiday.html', holiday=holiday)

@app.route('/delete_holiday/<int:holiday_id>')
@login_required
def delete_holiday(holiday_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    holiday = Holiday.query.get_or_404(holiday_id)
    
    # Ensure the holiday belongs to the current user's company
    if holiday.company_id != current_user.company.id:
        flash('Access denied.')
        return redirect(url_for('holidays'))
    
    db.session.delete(holiday)
    db.session.commit()
    
    flash('Holiday deleted successfully!')
    return redirect(url_for('holidays'))

@app.route('/calendar')
@login_required
def calendar_view():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Get the year and month from query parameters or default to current year/month
    current_date = datetime.now()
    year = request.args.get('year', current_date.year, type=int)
    month = request.args.get('month', current_date.month, type=int)
    
    # Create calendar data
    cal = cal_module.monthcalendar(year, month)  # Use the renamed module
    month_name = cal_module.month_name[month]
    
    month_names = [
        'January', 'February', 'March', 'April', 'May', 'June', 
        'July', 'August', 'September', 'October', 'November', 'December'
    ]
    # Get all holidays for this month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1) - timedelta(days=1)
    
    holidays = Holiday.query.filter_by(company_id=current_user.company.id) \
        .filter(Holiday.date >= start_date) \
        .filter(Holiday.date <= end_date) \
        .all()
    
    # Create a dictionary of holidays by day for easy lookup
    holidays_by_day = {holiday.date.day: holiday for holiday in holidays}
    
    # Available years and months for the dropdown
    available_years = range(current_date.year - 2, current_date.year + 4)
    
    return render_template('calendar.html',
                          cal=cal,
                          month=month,
                          month_name=month_name,
                          year=year,
                          holidays_by_day=holidays_by_day,
                          available_years=available_years,
                          current_month=current_date.month,
                          current_year=current_date.year,
                          now=current_date,
                          month_names=month_names)

# Add these new routes to your app.py file

@app.route('/import_configuration', methods=['GET', 'POST'])
@login_required
def import_configuration():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Standard fields with display names and descriptions
    standard_field_definitions = [
        {'name': 'first_name', 'display_name': 'First Name', 'description': 'Employee\'s first name'},
        {'name': 'last_name', 'display_name': 'Last Name', 'description': 'Employee\'s last name'},
        {'name': 'email', 'display_name': 'Email', 'description': 'Email address (auto-generated if not provided)'},
        {'name': 'phone', 'display_name': 'Phone', 'description': 'Contact phone number'},
        {'name': 'title', 'display_name': 'Job Title', 'description': 'Position or role (will create if doesn\'t exist)'},
        {'name': 'location', 'display_name': 'Location', 'description': 'Work location (will create if doesn\'t exist)'},
        {'name': 'hourly_rate', 'display_name': 'Hourly Rate', 'description': 'Regular pay rate per hour'},
        {'name': 'overtime_rate', 'display_name': 'Overtime Rate', 'description': 'Overtime pay rate per hour'},
        {'name': 'weekend_rate', 'display_name': 'Weekend Rate', 'description': 'Weekend pay rate per hour'},
        {'name': 'is_sunday_worker', 'display_name': 'Sunday Worker', 'description': 'Whether Sunday is a normal working day (yes/no)'},
        {'name': 'is_holiday_worker', 'display_name': 'Holiday Worker', 'description': 'Whether holidays are normal working days (yes/no)'},
        {'name': 'is_night_worker', 'display_name': 'Night Worker', 'description': 'Whether the employee works night shifts (yes/no)'},
        {'name': 'night_shift_allowance', 'display_name': 'Night Shift Allowance', 'description': 'Extra pay rate for night shifts'},
        {'name': 'additional_info', 'display_name': 'Additional Info', 'description': 'Any other notes or details'}
    ]
    
    # Get current import configuration
    standard_fields = []
    for field_def in standard_field_definitions:
        config = ImportConfig.query.filter_by(
            company_id=current_user.company.id,
            field_name=field_def['name']
        ).first()
        
        if not config:
            config = ImportConfig(
                company_id=current_user.company.id,
                field_name=field_def['name'],
                is_standard=True,
                is_required=(field_def['name'] in ['first_name', 'last_name', 'title', 'location'])
            )
            db.session.add(config)
            db.session.commit()
        
        field_info = field_def.copy()
        field_info['is_required'] = config.is_required
        standard_fields.append(field_info)
    
    custom_fields = CustomField.query.filter_by(company_id=current_user.company.id).all()
    
    if request.method == 'POST':
        required_fields = request.form.getlist('required_fields')
        
        for field_def in standard_field_definitions:
            field_name = field_def['name']
            if field_name not in ['first_name', 'last_name']:
                config = ImportConfig.query.filter_by(
                    company_id=current_user.company.id,
                    field_name=field_name
                ).first()
                
                if config:
                    config.is_required = field_name in required_fields
        
        custom_field_ids = request.form.getlist('custom_field_ids[]')
        custom_field_names = request.form.getlist('custom_field_names[]')
        custom_field_types = request.form.getlist('custom_field_types[]')
        custom_field_descriptions = request.form.getlist('custom_field_descriptions[]')
        custom_field_required = request.form.getlist('custom_field_required[]')

        name_counts = {}
        for i, name in enumerate(custom_field_names):
            if not name.strip():
                continue

            cleaned_name = name.strip()
            if cleaned_name in name_counts:
                count = name_counts[cleaned_name] + 1
                name_counts[cleaned_name] = count
                custom_field_names[i] = f"{cleaned_name} ({count})"
            else:
                name_counts[cleaned_name] = 1

            if i >= len(custom_field_ids) or not custom_field_ids[i]:
                existing_field = CustomField.query.filter_by(
                    company_id=current_user.company.id,
                    name=cleaned_name
                ).first()
                
                if existing_field:
                    count = 1
                    while True:
                        new_name = f"{cleaned_name} ({count})"
                        exists = CustomField.query.filter_by(
                            company_id=current_user.company.id,
                            name=new_name
                        ).first()
                        
                        if not exists:
                            custom_field_names[i] = new_name
                            break
                        count += 1

        for i in range(len(custom_field_names)):
            field_id = custom_field_ids[i] if i < len(custom_field_ids) else ''
            
            if not custom_field_names[i].strip():
                continue
            
            if field_id and field_id.isdigit():
                field = CustomField.query.get(int(field_id))
                if field and field.company_id == current_user.company.id:
                    old_name = field.name
                    new_name = custom_field_names[i].strip()
                    
                    if old_name != new_name:
                        existing = CustomField.query.filter_by(
                            company_id=current_user.company.id,
                            name=new_name
                        ).first()
                        
                        if existing and existing.id != field.id:
                            count = 1
                            while True:
                                unique_name = f"{new_name} ({count})"
                                exists = CustomField.query.filter_by(
                                    company_id=current_user.company.id,
                                    name=unique_name
                                ).first()
                                
                                if not exists:
                                    new_name = unique_name
                                    break
                                count += 1
                    
                    field.name = new_name
                    field.field_type = custom_field_types[i]
                    field.description = custom_field_descriptions[i] if i < len(custom_field_descriptions) else ''
                    field.is_required = str(i) in custom_field_required
            else:
                field = CustomField(
                    company_id=current_user.company.id,
                    name=custom_field_names[i].strip(),
                    field_type=custom_field_types[i],
                    description=custom_field_descriptions[i] if i < len(custom_field_descriptions) else '',
                    is_required=str(i) in custom_field_required
                )
                db.session.add(field)

        try:
            db.session.commit()
            flash('Import configuration saved successfully!')
            db.session.commit()
            flash('Import configuration saved successfully!')
            # Call the function directly to update custom field columns
            update_custom_field_columns()
            return redirect(url_for('column_settings'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error saving configuration: {str(e)}', 'danger')
            return render_template('import_configuration.html',
                                   standard_fields=standard_fields,
                                   custom_fields=custom_fields)
    
    return render_template('import_configuration.html',
                           standard_fields=standard_fields,
                           custom_fields=custom_fields)


@app.route('/import_employees', methods=['GET', 'POST'])
@login_required
def import_employees():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Get import configuration
    standard_configs = ImportConfig.query.filter_by(
        company_id=current_user.company.id,
        is_standard=True
    ).all()
    
    # Standard field definitions (for display)
    field_display_names = {
        'first_name': 'First Name',
        'last_name': 'Last Name',
        'email': 'Email',
        'phone': 'Phone',
        'title': 'Job Title',
        'location': 'Location', 
        'hourly_rate': 'Hourly Rate',
        'overtime_rate': 'Overtime Rate',
        'weekend_rate': 'Weekend Rate',
        'is_sunday_worker': 'Sunday Worker',
        'is_holiday_worker': 'Holiday Worker',
        'is_night_worker': 'Night Worker',
        'night_shift_allowance': 'Night Shift Allowance',
        'additional_info': 'Additional Info'
    }
    
    # Create lists for required and optional fields
    required_fields = []
    optional_fields = []
    
    for config in standard_configs:
        display_name = field_display_names.get(config.field_name, config.field_name)
        field_info = {
            'name': config.field_name,
            'display_name': display_name
        }
        if config.is_required:
            required_fields.append(field_info)
        else:
            optional_fields.append(field_info)
    
    # Get custom fields
    custom_fields = CustomField.query.filter_by(company_id=current_user.company.id).all()
    
    # Add required custom fields to required list
    for field in custom_fields:
        if field.is_required:
            required_fields.append({
                'name': field.name,
                'display_name': field.name
            })
    
    # Handle file upload
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
                required_field_names = [field['name'] for field in required_fields]
                missing_columns = [col for col in required_field_names if col not in df.columns]
                
                if missing_columns:
                    flash(f"Missing required columns: {', '.join(missing_columns)}")
                    return redirect(request.url)
                
                # Track results
                success_count = 0
                error_count = 0
                error_messages = []
                
                # Get job titles and locations for reference/creation
                job_titles = {title.title: title.id for title in JobTitle.query.filter_by(company_id=current_user.company.id).all()}
                locations = {location.name: location.id for location in Location.query.filter_by(company_id=current_user.company.id).all()}
                
                # Process each row
                for index, row in df.iterrows():
                    try:
                        # Basic validation first
                        if pd.isna(row.get('first_name')) or pd.isna(row.get('last_name')):
                            error_count += 1
                            error_messages.append(f"Row {index+2}: Missing required name fields")
                            continue
                        
                        # Initialize employee data
                        employee_data = {
                            'first_name': str(row['first_name']).strip(),
                            'last_name': str(row['last_name']).strip(),
                            'company_id': current_user.company.id,
                            'is_active': True
                        }
                        
                        # Process job title
                        job_title_id = None
                        if 'title' in df.columns and not pd.isna(row['title']):
                            title_text = str(row['title']).strip()
                            if title_text in job_titles:
                                job_title_id = job_titles[title_text]
                            else:
                                # Create new job title
                                new_title = JobTitle(
                                    title=title_text,
                                    description=f"Auto-created during import",
                                    company_id=current_user.company.id
                                )
                                db.session.add(new_title)
                                db.session.flush()  # Get the ID
                                job_title_id = new_title.id
                                job_titles[title_text] = job_title_id
                        employee_data['job_title_id'] = job_title_id
                        
                        # Process location
                        location_id = None
                        if 'location' in df.columns and not pd.isna(row['location']):
                            location_text = str(row['location']).strip()
                            if location_text in locations:
                                location_id = locations[location_text]
                            else:
                                # Create new location
                                new_location = Location(
                                    name=location_text,
                                    address=f"Auto-created during import",
                                    company_id=current_user.company.id
                                )
                                db.session.add(new_location)
                                db.session.flush()  # Get the ID
                                location_id = new_location.id
                                locations[location_text] = location_id
                        employee_data['location_id'] = location_id
                        
                        # Process email (generate if missing)
                        if 'email' in df.columns and not pd.isna(row['email']):
                            employee_data['email'] = str(row['email']).strip()
                        else:
                            # Generate email
                            email = f"{employee_data['first_name'].lower()}.{employee_data['last_name'].lower()}@{current_user.company.name.lower().replace(' ', '')}.com"
                            employee_data['email'] = email
                        
                        # Check for email uniqueness
                        existing_employee = Employee.query.filter_by(email=employee_data['email']).first()
                        if existing_employee:
                            error_count += 1
                            error_messages.append(f"Row {index+2}: Email {employee_data['email']} already exists")
                            continue
                        
                        # Process standard fields
                        standard_fields = ['phone', 'hourly_rate', 'overtime_rate', 'weekend_rate', 
                                          'is_sunday_worker', 'is_holiday_worker', 'is_night_worker', 
                                          'night_shift_allowance', 'additional_info']
                        
                        for field in standard_fields:
                            if field in df.columns and not pd.isna(row[field]):
                                if field in ['is_sunday_worker', 'is_holiday_worker', 'is_night_worker']:
                                    # Handle boolean fields
                                    value = str(row[field]).lower().strip()
                                    employee_data[field] = value in ['yes', 'true', '1', 'y', 't']
                                elif field in ['hourly_rate', 'overtime_rate', 'weekend_rate', 'night_shift_allowance']:
                                    # Handle numeric fields
                                    try:
                                        employee_data[field] = float(row[field])
                                    except (ValueError, TypeError):
                                        if field == 'hourly_rate':
                                            employee_data[field] = 15.0  # Default
                                        elif field == 'overtime_rate':
                                            employee_data[field] = employee_data.get('hourly_rate', 15.0) * 1.5
                                        elif field == 'weekend_rate':
                                            employee_data[field] = employee_data.get('hourly_rate', 15.0) * 2.0
                                        elif field == 'night_shift_allowance':
                                            employee_data[field] = 0.1  # Default 10%
                                else:
                                    # Handle text fields
                                    employee_data[field] = str(row[field]).strip()
                        
                        # Set defaults for required fields if not present
                        if 'hourly_rate' not in employee_data:
                            employee_data['hourly_rate'] = 15.0  # Default
                        if 'overtime_rate' not in employee_data:
                            employee_data['overtime_rate'] = employee_data['hourly_rate'] * 1.5
                        if 'weekend_rate' not in employee_data:
                            employee_data['weekend_rate'] = employee_data['hourly_rate'] * 2.0
                            
                        # Create the employee
                        employee = Employee(**employee_data)
                        db.session.add(employee)
                        db.session.flush()  # Get employee ID for custom fields
                        
                        # Process custom fields
                        for field in custom_fields:
                            if field.name in df.columns and not pd.isna(row[field.name]):
                                value = row[field.name]
                                
                                # Create field value based on type
                                field_value = CustomFieldValue(
                                    custom_field_id=field.id,
                                    employee_id=employee.id
                                )
                                
                                if field.field_type == 'text' or field.field_type == 'select':
                                    field_value.text_value = str(value).strip()
                                elif field.field_type == 'number':
                                    try:
                                        field_value.number_value = float(value)
                                    except (ValueError, TypeError):
                                        field_value.number_value = 0
                                elif field.field_type == 'boolean':
                                    value_str = str(value).lower().strip()
                                    field_value.boolean_value = value_str in ['yes', 'true', '1', 'y', 't']
                                elif field.field_type == 'date':
                                    try:
                                        if isinstance(value, str):
                                            # Try to parse date string
                                            parsed_date = datetime.strptime(value, '%Y-%m-%d').date()
                                            field_value.date_value = parsed_date
                                        else:
                                            # Handle pandas datetime
                                            field_value.date_value = value.date()
                                    except (ValueError, TypeError, AttributeError):
                                        # Skip invalid dates
                                        continue
                                
                                db.session.add(field_value)
                        
                        success_count += 1
                            
                    except Exception as e:
                        error_count += 1
                        error_messages.append(f"Row {index+2}: {str(e)}")
                
                # Commit all changes if there were any successful imports
                if success_count > 0:
                    try:
                        db.session.commit()
                        flash(f"Successfully imported {success_count} employees.")
                    except Exception as e:
                        db.session.rollback()
                        flash(f"Error during database commit: {str(e)}")
                        return redirect(request.url)
                
                # Show errors
                if error_count > 0:
                    for error in error_messages[:10]:  # Show first 10 errors
                        flash(error, 'error')
                    if len(error_messages) > 10:
                        flash(f"... and {len(error_messages) - 10} more errors", 'error')
                        
                return redirect(url_for('employees'))
                
            except Exception as e:
                flash(f"Error processing file: {str(e)}")
                return redirect(request.url)
        else:
            flash('File must be an Excel spreadsheet (.xlsx or .xls)')
            return redirect(request.url)
    
    return render_template('import_employees.html',
                          required_fields=required_fields,
                          optional_fields=optional_fields,
                          custom_fields=custom_fields)

@app.route('/download_sample_excel')
@login_required
def download_sample_excel():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    # Get all fields configuration
    standard_configs = ImportConfig.query.filter_by(
        company_id=current_user.company.id,
        is_standard=True
    ).all()
    
    custom_fields = CustomField.query.filter_by(company_id=current_user.company.id).all()
    
    # Create headers for all fields
    headers = [config.field_name for config in standard_configs] + [field.name for field in custom_fields]
    
    # Create sample data
    sample_data = {}
    
    # Add standard field sample data
    for config in standard_configs:
        field_name = config.field_name
        if field_name == 'first_name':
            sample_data[field_name] = ['John', 'Jane']
        elif field_name == 'last_name':
            sample_data[field_name] = ['Doe', 'Smith']
        elif field_name == 'title':
            sample_data[field_name] = ['Manager', 'Developer']
        elif field_name == 'location':
            sample_data[field_name] = ['Main Office', 'Remote']
        elif field_name == 'phone':
            sample_data[field_name] = ['555-123-4567', '555-987-6543']
        elif field_name == 'email':
            sample_data[field_name] = ['john.doe@example.com', 'jane.smith@example.com']
        elif field_name == 'hourly_rate':
            sample_data[field_name] = [25.0, 22.5]
        elif field_name == 'overtime_rate':
            sample_data[field_name] = [37.5, 33.75]
        elif field_name == 'weekend_rate':
            sample_data[field_name] = [50.0, 45.0]
        elif field_name in ['is_sunday_worker', 'is_holiday_worker', 'is_night_worker']:
            sample_data[field_name] = [True, False]
        elif field_name == 'night_shift_allowance':
            sample_data[field_name] = [0.15, 0.1]
        elif field_name == 'additional_info':
            sample_data[field_name] = ['Team lead', 'Frontend specialist']
    
    # Add custom field sample data
    for field in custom_fields:
        if field.field_type == 'text' or field.field_type == 'select':
            sample_data[field.name] = [f'Sample {field.name} 1', f'Sample {field.name} 2']
        elif field.field_type == 'number':
            sample_data[field.name] = [42, 73]
        elif field.field_type == 'boolean':
            sample_data[field.name] = [True, False]
        elif field.field_type == 'date':
            sample_data[field.name] = ['2025-01-15', '2025-02-20']
    
    # Create DataFrame with only the fields that have data
    # This prevents empty columns for fields not in the configuration
    valid_columns = [col for col in headers if col in sample_data]
    sample_df = pd.DataFrame({col: sample_data[col] for col in valid_columns})
    
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
# Add these new routes to app.py

@app.route('/column_settings', methods=['GET', 'POST'])
@login_required
def column_settings():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company_id = current_user.company.id
    
    if request.method == 'POST':
        # First, set all columns to not visible by default
        ColumnSettings.query.filter_by(company_id=company_id).update({"is_visible": False})
        db.session.flush()  # Apply the update but don't commit yet
        
        # Process visibility settings - mark selected columns as visible
        for key in request.form:
            if key.startswith('visible['):
                # Extract view_type and column_id using regex for reliability
                match = re.match(r'visible\[([^\]]+)\]\[([^\]]+)\]', key)
                if match:
                    view_type = match.group(1)
                    column_id = match.group(2)
                    
                    # Find and update this column
                    column = ColumnSettings.query.filter_by(
                        id=column_id, 
                        view_type=view_type,
                        company_id=company_id
                    ).first()
                    
                    if column:
                        column.is_visible = True
        
        # Process display names
        for key, value in request.form.items():
            if key.startswith('display['):
                match = re.match(r'display\[([^\]]+)\]\[([^\]]+)\]', key)
                if match:
                    view_type = match.group(1)
                    column_id = match.group(2)
                    
                    column = ColumnSettings.query.filter_by(
                        id=column_id, 
                        view_type=view_type,
                        company_id=company_id
                    ).first()
                    
                    if column and value.strip():  # Only update if not empty
                        column.display_name = value
        
        # Process display order
        for key, value in request.form.items():
            if key.startswith('order['):
                match = re.match(r'order\[([^\]]+)\]\[([^\]]+)\]', key)
                if match:
                    view_type = match.group(1)
                    column_id = match.group(2)
                    
                    try:
                        order_value = int(value)
                        
                        column = ColumnSettings.query.filter_by(
                            id=column_id, 
                            view_type=view_type,
                            company_id=company_id
                        ).first()
                        
                        if column:
                            column.display_order = order_value
                    except (ValueError, TypeError):
                        # Skip invalid order values
                        continue
        
        try:
            db.session.commit()
            flash('Column settings updated successfully!')
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving settings: {str(e)}')
        
        # Redirect to the same page to show updated settings
        return redirect(url_for('column_settings'))
    
    # Get current settings for each view type
    dashboard_columns = ColumnSettings.query.filter_by(
        company_id=company_id,
        view_type='dashboard'
    ).order_by(ColumnSettings.display_order).all()
    
    employee_timesheet_columns = ColumnSettings.query.filter_by(
        company_id=company_id,
        view_type='employee_timesheet'
    ).order_by(ColumnSettings.display_order).all()
    
    group_timesheet_columns = ColumnSettings.query.filter_by(
        company_id=company_id,
        view_type='group_timesheet'
    ).order_by(ColumnSettings.display_order).all()
    
    # Initialize settings if any view has no settings
    if not dashboard_columns or not employee_timesheet_columns or not group_timesheet_columns:
        ColumnSettings.initialize_for_company(company_id)
        
        # Reload settings
        dashboard_columns = ColumnSettings.query.filter_by(
            company_id=company_id,
            view_type='dashboard'
        ).order_by(ColumnSettings.display_order).all()
        
        employee_timesheet_columns = ColumnSettings.query.filter_by(
            company_id=company_id,
            view_type='employee_timesheet'
        ).order_by(ColumnSettings.display_order).all()
        
        group_timesheet_columns = ColumnSettings.query.filter_by(
            company_id=company_id,
            view_type='group_timesheet'
        ).order_by(ColumnSettings.display_order).all()
    
    return render_template('column_settings.html',
                          dashboard_columns=dashboard_columns,
                          employee_timesheet_columns=employee_timesheet_columns,
                          group_timesheet_columns=group_timesheet_columns)

@app.route('/reset_column_settings', methods=['POST'])
@login_required
def reset_column_settings():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company_id = current_user.company.id
    
    # Reinitialize with defaults
    ColumnSettings.initialize_for_company(company_id)
    
    flash('Column settings have been reset to default values.')
    return redirect(url_for('column_settings'))

@app.route('/update_custom_field_columns', methods=['GET', 'POST'])
@login_required
def update_custom_field_columns():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    
    company_id = current_user.company.id
    
    # Process the request regardless of method
    # Get all custom fields
    custom_fields = CustomField.query.filter_by(company_id=company_id).all()
    
    # Update column settings for each view type
    for view_type in ['dashboard', 'employee_timesheet', 'group_timesheet']:
        # First, handle existing custom field columns that might need to be removed
        # Get all custom field column settings
        custom_columns = ColumnSettings.query.filter(
            ColumnSettings.company_id == company_id,
            ColumnSettings.view_type == view_type,
            ColumnSettings.column_name.like('custom_%')
        ).all()
        
        # Check each custom column to see if it still has a corresponding custom field
        for column in custom_columns:
            field_id = column.column_name.replace('custom_', '')
            try:
                field_id = int(field_id)
                field_exists = any(field.id == field_id for field in custom_fields)
                
                if not field_exists:
                    # Custom field has been deleted, so remove its column
                    db.session.delete(column)
            except (ValueError, TypeError):
                # Not a valid custom field ID, remove it
                db.session.delete(column)
        
        # Now add columns for new custom fields
        for field in custom_fields:
            column_name = f"custom_{field.id}"
            
            # Check if this field already has a column
            existing = ColumnSettings.query.filter_by(
                company_id=company_id,
                view_type=view_type,
                column_name=column_name
            ).first()
            
            if not existing and view_type == 'dashboard':  # Only add to dashboard view for now
                # Get the maximum display order
                max_order = db.session.query(db.func.max(ColumnSettings.display_order)).filter_by(
                    company_id=company_id,
                    view_type=view_type
                ).scalar() or 0
                
                # Create a new column setting for this custom field
                new_column = ColumnSettings(
                    company_id=company_id,
                    view_type=view_type,
                    column_name=column_name,
                    display_name=field.name,
                    is_visible=False,  # Hidden by default
                    display_order=max_order + 1  # Add at the end
                )
                db.session.add(new_column)
    
    db.session.commit()
    
    # If it's a GET request, just redirect to column settings
    # If it's a POST request, flash a message and then redirect
    if request.method == 'POST':
        flash('Custom field columns updated successfully!')
    
    return redirect(url_for('column_settings'))

@app.before_first_request
def create_tables():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)