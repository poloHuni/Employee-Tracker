"""
Migration script to add new fields for the overtime rules.
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
        # Check if is_sunday_worker column already exists in employee table
        cursor.execute("PRAGMA table_info(employee)")
        employee_columns = [column[1] for column in cursor.fetchall()]
        
        # 1. Add is_sunday_worker column if it doesn't exist
        if 'is_sunday_worker' not in employee_columns:
            print("Adding is_sunday_worker column to employee table...")
            cursor.execute('ALTER TABLE employee ADD COLUMN is_sunday_worker BOOLEAN DEFAULT 0')
            
        # 2. Add is_holiday_worker column if it doesn't exist
        if 'is_holiday_worker' not in employee_columns:
            print("Adding is_holiday_worker column to employee table...")
            cursor.execute('ALTER TABLE employee ADD COLUMN is_holiday_worker BOOLEAN DEFAULT 0')
        
        # Check if is_public_holiday column already exists in timesheet table
        cursor.execute("PRAGMA table_info(timesheet)")
        timesheet_columns = [column[1] for column in cursor.fetchall()]
        
        # 3. Add is_public_holiday column if it doesn't exist
        if 'is_public_holiday' not in timesheet_columns:
            print("Adding is_public_holiday column to timesheet table...")
            cursor.execute('ALTER TABLE timesheet ADD COLUMN is_public_holiday BOOLEAN DEFAULT 0')
        
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
    print("Starting database migration for overtime rules...")
    success = execute_migration()
    
    if success:
        print("\nMigration completed successfully!")
        print("Your TimeTracker application now supports special overtime calculation rules.")
        print("\nNext steps:")
        print("1. Restart your TimeTracker application")
        print("2. Configure Sunday and Holiday worker status for your employees")
        print("3. When adding timesheets for public holidays, make sure to mark them accordingly")
    else:
        print("\nMigration failed. Please check the error messages above.")
        print("You may need to provide the correct path to your database file.")