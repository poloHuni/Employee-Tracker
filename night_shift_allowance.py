"""
Migration script to add night shift allowance feature.
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
        # Check if is_night_worker column already exists in employee table
        cursor.execute("PRAGMA table_info(employee)")
        employee_columns = [column[1] for column in cursor.fetchall()]
        
        # 1. Add is_night_worker column if it doesn't exist
        if 'is_night_worker' not in employee_columns:
            print("Adding is_night_worker column to employee table...")
            cursor.execute('ALTER TABLE employee ADD COLUMN is_night_worker BOOLEAN DEFAULT 0')
            
        # 2. Add night_shift_allowance column if it doesn't exist
        if 'night_shift_allowance' not in employee_columns:
            print("Adding night_shift_allowance column to employee table...")
            cursor.execute('ALTER TABLE employee ADD COLUMN night_shift_allowance FLOAT DEFAULT 0.1')  # Default 10%
        
        # Check if is_night_shift column already exists in timesheet table
        cursor.execute("PRAGMA table_info(timesheet)")
        timesheet_columns = [column[1] for column in cursor.fetchall()]
        
        # 3. Add is_night_shift column if it doesn't exist
        if 'is_night_shift' not in timesheet_columns:
            print("Adding is_night_shift column to timesheet table...")
            cursor.execute('ALTER TABLE timesheet ADD COLUMN is_night_shift BOOLEAN DEFAULT 0')
        
        # 4. Add company-wide default night shift allowance rate to company table
        cursor.execute("PRAGMA table_info(company)")
        company_columns = [column[1] for column in cursor.fetchall()]
        
        if 'default_night_allowance' not in company_columns:
            print("Adding default_night_allowance column to company table...")
            cursor.execute('ALTER TABLE company ADD COLUMN default_night_allowance FLOAT DEFAULT 0.1')  # Default 10%
        
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
    print("Starting database migration for night shift allowance...")
    success = execute_migration()
    
    if success:
        print("\nMigration completed successfully!")
        print("Your TimeTracker application now supports night shift allowance calculation.")
        print("\nNext steps:")
        print("1. Restart your TimeTracker application")
        print("2. Configure night worker status and allowance rates for your employees")
        print("3. The system will automatically detect night shifts based on clock-in and clock-out times")
    else:
        print("\nMigration failed. Please check the error messages above.")
        print("You may need to provide the correct path to your database file.")