"""
Migration script to add weekend_rate column to Employee table and create RateFunction table.
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
        # Check if weekend_rate column already exists
        cursor.execute("PRAGMA table_info(employee)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # 1. Add weekend_rate column if it doesn't exist
        if 'weekend_rate' not in columns:
            print("Adding weekend_rate column to employee table...")
            cursor.execute('ALTER TABLE employee ADD COLUMN weekend_rate FLOAT DEFAULT 0')
            
            # Set default values - make weekend rate 2x the hourly rate
            cursor.execute('UPDATE employee SET weekend_rate = hourly_rate * 2.0')
            print("Set default weekend rates to 2x regular rates")
        else:
            print("weekend_rate column already exists")
        
        # 2. Create rate_function table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_function (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            weekday_formula VARCHAR(200) NOT NULL,
            weekend_formula VARCHAR(200) NOT NULL,
            company_id INTEGER NOT NULL,
            FOREIGN KEY (company_id) REFERENCES company (id)
        )
        """)
        print("Created rate_function table if it didn't exist")
        
        # Check if rate_function_id column already exists in employee table
        if 'rate_function_id' not in columns:
            print("Adding rate_function_id column to employee table...")
            cursor.execute('ALTER TABLE employee ADD COLUMN rate_function_id INTEGER')
        else:
            print("rate_function_id column already exists")
        
        # 3. Create some default rate functions for each company
        cursor.execute("SELECT id, name FROM company")
        companies = cursor.fetchall()
        
        for company_id, company_name in companies:
            # Check if company already has rate functions
            cursor.execute("SELECT COUNT(*) FROM rate_function WHERE company_id = ?", (company_id,))
            count = cursor.fetchone()[0]
            
            if count == 0:
                print(f"Creating default rate functions for company: {company_name}")
                # Standard functions
                cursor.execute("""
                INSERT INTO rate_function (name, description, weekday_formula, weekend_formula, company_id)
                VALUES (?, ?, ?, ?, ?)
                """, (
                    "Standard Overtime (1.5x)",
                    "Standard overtime at 1.5x regular rate",
                    "base * 1.5",
                    "base * 2.0",
                    company_id
                ))
                
                cursor.execute("""
                INSERT INTO rate_function (name, description, weekday_formula, weekend_formula, company_id)
                VALUES (?, ?, ?, ?, ?)
                """, (
                    "Enhanced Overtime (2x)",
                    "Enhanced overtime at 2x regular rate, weekend at 2.5x",
                    "base * 2.0",
                    "base * 2.5",
                    company_id
                ))
                
                cursor.execute("""
                INSERT INTO rate_function (name, description, weekday_formula, weekend_formula, company_id)
                VALUES (?, ?, ?, ?, ?)
                """, (
                    "Progressive Overtime",
                    "Overtime increases based on regular rate",
                    "base * 1.5 if base < 20 else base * 1.75",
                    "base * 2.0 if base < 20 else base * 2.25",
                    company_id
                ))
            else:
                print(f"Company {company_name} already has rate functions")
        
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
    print("Starting database migration...")
    success = execute_migration()
    
    if success:
        print("\nMigration completed successfully!")
        print("Your TimeTracker application now supports weekend rates and custom rate functions.")
        print("\nNext steps:")
        print("1. Restart your TimeTracker application")
        print("2. Access the new 'Pay Rate Functions' page from the Employees dropdown menu")
        print("3. Update employee records with appropriate weekend rates")
    else:
        print("\nMigration failed. Please check the error messages above.")
        print("You may need to provide the correct path to your database file.")