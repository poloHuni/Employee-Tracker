"""
Migration script to add work hours configuration feature.
Run this script directly to update your database schema.
"""

import sqlite3
import os

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
        # 1. Add default work hours columns to company table
        cursor.execute("PRAGMA table_info(company)")
        company_columns = [column[1] for column in cursor.fetchall()]
        
        if 'default_work_start_time' not in company_columns:
            print("Adding default_work_start_time column to company table...")
            cursor.execute('ALTER TABLE company ADD COLUMN default_work_start_time TIME DEFAULT "09:00:00"')
            
        if 'default_work_end_time' not in company_columns:
            print("Adding default_work_end_time column to company table...")
            cursor.execute('ALTER TABLE company ADD COLUMN default_work_end_time TIME DEFAULT "17:00:00"')
        
        # 2. Add work hours columns to job_title table
        cursor.execute("PRAGMA table_info(job_title)")
        job_title_columns = [column[1] for column in cursor.fetchall()]
        
        if 'work_start_time' not in job_title_columns:
            print("Adding work_start_time column to job_title table...")
            cursor.execute('ALTER TABLE job_title ADD COLUMN work_start_time TIME DEFAULT NULL')
            
        if 'work_end_time' not in job_title_columns:
            print("Adding work_end_time column to job_title table...")
            cursor.execute('ALTER TABLE job_title ADD COLUMN work_end_time TIME DEFAULT NULL')
        
        # 3. Add work hours columns to employee table
        cursor.execute("PRAGMA table_info(employee)")
        employee_columns = [column[1] for column in cursor.fetchall()]
        
        if 'work_start_time' not in employee_columns:
            print("Adding work_start_time column to employee table...")
            cursor.execute('ALTER TABLE employee ADD COLUMN work_start_time TIME DEFAULT NULL')
            
        if 'work_end_time' not in employee_columns:
            print("Adding work_end_time column to employee table...")
            cursor.execute('ALTER TABLE employee ADD COLUMN work_end_time TIME DEFAULT NULL')
        
        # 4. Add work hours columns to employee_group table
        cursor.execute("PRAGMA table_info(employee_group)")
        group_columns = [column[1] for column in cursor.fetchall()]
        
        if 'work_start_time' not in group_columns:
            print("Adding work_start_time column to employee_group table...")
            cursor.execute('ALTER TABLE employee_group ADD COLUMN work_start_time TIME DEFAULT NULL')
            
        if 'work_end_time' not in group_columns:
            print("Adding work_end_time column to employee_group table...")
            cursor.execute('ALTER TABLE employee_group ADD COLUMN work_end_time TIME DEFAULT NULL')
        
        # 5. Create employee_group_membership table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS employee_group_membership (
            employee_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            PRIMARY KEY (employee_id, group_id),
            FOREIGN KEY (employee_id) REFERENCES employee (id),
            FOREIGN KEY (group_id) REFERENCES employee_group (id)
        )
        """)
        print("Created/verified employee_group_membership table")
        
        # 6. Add option to have enforced work hours in the company table
        if 'enforce_work_hours' not in company_columns:
            print("Adding enforce_work_hours column to company table...")
            cursor.execute('ALTER TABLE company ADD COLUMN enforce_work_hours BOOLEAN DEFAULT 0')
        
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
    print("Starting database migration for work hours configuration...")
    success = execute_migration()
    
    if success:
        print("\nMigration completed successfully!")
        print("Your TimeTracker application now supports configurable work hours.")
        print("\nNext steps:")
        print("1. Restart your TimeTracker application")
        print("2. Configure company-wide, job title, employee, or group work hours")
        print("3. Early clock-ins will not count until the work start time")
    else:
        print("\nMigration failed. Please check the error messages above.")
        print("You may need to provide the correct path to your database file.")