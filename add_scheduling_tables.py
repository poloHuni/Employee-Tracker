"""
Migration script to add job scheduling functionality.
Run this script directly to update your database schema.
"""

import sqlite3
import os
from datetime import datetime

# Path to your database file - update this to match your actual database path
DB_PATH = 'timesheet.db'  # Use the full path if needed

def execute_migration():
    # Check if database file exists
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file '{DB_PATH}' not found.")
        return False
    
    # Connect to the database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 1. Create the shift table for shift templates
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS shift (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            color VARCHAR(20) DEFAULT '#3498db',
            is_night_shift BOOLEAN DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            FOREIGN KEY (company_id) REFERENCES company (id)
        )
        ''')
        print("Created shift table")
        
        # 2. Create the shift_assignment table for assigning shifts to employees
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS shift_assignment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            shift_id INTEGER NOT NULL,
            date DATE NOT NULL,
            status VARCHAR(20) DEFAULT 'scheduled',
            notes TEXT,
            FOREIGN KEY (employee_id) REFERENCES employee (id),
            FOREIGN KEY (shift_id) REFERENCES shift (id),
            UNIQUE (employee_id, shift_id, date)
        )
        ''')
        print("Created shift_assignment table")
        
        # 3. Create the employee_availability table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS employee_availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL,
            start_time TIME,
            end_time TIME,
            FOREIGN KEY (employee_id) REFERENCES employee (id),
            UNIQUE (employee_id, day_of_week)
        )
        ''')
        print("Created employee_availability table")
        
        # 4. Create the time_off_request table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS time_off_request (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            reason TEXT,
            status VARCHAR(20) DEFAULT 'pending',
            notes TEXT,
            requested_on DATETIME DEFAULT CURRENT_TIMESTAMP,
            decided_by INTEGER,
            decided_on DATETIME,
            FOREIGN KEY (employee_id) REFERENCES employee (id),
            FOREIGN KEY (decided_by) REFERENCES user (id)
        )
        ''')
        print("Created time_off_request table")
        
        # 5. Create the schedule_period table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedule_period (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            name VARCHAR(100),
            status VARCHAR(20) DEFAULT 'draft',
            created_by INTEGER NOT NULL,
            created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
            published_on DATETIME,
            FOREIGN KEY (company_id) REFERENCES company (id),
            FOREIGN KEY (created_by) REFERENCES user (id)
        )
        ''')
        print("Created schedule_period table")
        
        # Create some sample shifts for each company
        cursor.execute("SELECT id, name FROM company")
        companies = cursor.fetchall()
        
        for company_id, company_name in companies:
            print(f"Adding default shifts for {company_name}...")
            
            # Check if company already has shifts
            cursor.execute("SELECT COUNT(*) FROM shift WHERE company_id = ?", (company_id,))
            shifts_count = cursor.fetchone()[0]
            
            if shifts_count == 0:
                # Add default shifts
                default_shifts = [
                    ('Morning Shift', '08:00:00', '16:00:00', '#3498db', 0),
                    ('Afternoon Shift', '16:00:00', '00:00:00', '#2ecc71', 1),
                    ('Night Shift', '00:00:00', '08:00:00', '#9b59b6', 1),
                    ('Regular Day', '09:00:00', '17:00:00', '#e67e22', 0),
                    ('Weekend Shift', '10:00:00', '18:00:00', '#e74c3c', 0)
                ]
                
                for name, start_time, end_time, color, is_night_shift in default_shifts:
                    cursor.execute('''
                    INSERT INTO shift (company_id, name, start_time, end_time, color, is_night_shift)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''', (company_id, name, start_time, end_time, color, is_night_shift))
                
                print(f"Added {len(default_shifts)} default shifts")
            else:
                print(f"Company already has {shifts_count} shifts, skipping defaults")
        
        # Commit all changes
        conn.commit()
        print("Migration completed successfully!")
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {str(e)}")
        return False
    
    finally:
        conn.close()

if __name__ == "__main__":
    print("Starting database migration for job scheduling...")
    success = execute_migration()
    
    if success:
        print("\nMigration completed successfully!")
        print("Your TimeTracker application now has job scheduling capabilities.")
        print("\nNext steps:")
        print("1. Restart your TimeTracker application")
        print("2. Use the new Scheduling menu to manage shifts and schedules")
        print("3. Set up employee availability for better scheduling")
    else:
        print("\nMigration failed. Please check the error messages above.")
        print("You may need to provide the correct path to your database file.")