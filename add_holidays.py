"""
Migration script to add holiday management feature.
Run this script directly to update your database schema.
"""

import sqlite3
import os
import datetime

# Path to your database file - update this to match your actual database path
DB_PATH = 'timesheet.db'  # Use the full path if needed

# List of South African public holidays for 2023, 2024, and 2025
SOUTH_AFRICAN_HOLIDAYS = [
    # 2023 Holidays
    ('2023-01-01', "New Year's Day"),
    ('2023-01-02', "New Year's Day (observed)"),
    ('2023-03-21', "Human Rights Day"),
    ('2023-04-07', "Good Friday"),
    ('2023-04-10', "Family Day"),
    ('2023-04-27', "Freedom Day"),
    ('2023-05-01', "Workers' Day"),
    ('2023-06-16', "Youth Day"),
    ('2023-08-09', "National Women's Day"),
    ('2023-09-24', "Heritage Day"),
    ('2023-09-25', "Heritage Day (observed)"),
    ('2023-12-16', "Day of Reconciliation"),
    ('2023-12-25', "Christmas Day"),
    ('2023-12-26', "Day of Goodwill"),
    
    # 2024 Holidays
    ('2024-01-01', "New Year's Day"),
    ('2024-03-21', "Human Rights Day"),
    ('2024-03-29', "Good Friday"),
    ('2024-04-01', "Family Day"),
    ('2024-04-27', "Freedom Day"),
    ('2024-05-01', "Workers' Day"),
    ('2024-06-16', "Youth Day"),
    ('2024-06-17', "Youth Day (observed)"),
    ('2024-08-09', "National Women's Day"),
    ('2024-09-24', "Heritage Day"),
    ('2024-12-16', "Day of Reconciliation"),
    ('2024-12-25', "Christmas Day"),
    ('2024-12-26', "Day of Goodwill"),
    
    # 2025 Holidays
    ('2025-01-01', "New Year's Day"),
    ('2025-03-21', "Human Rights Day"),
    ('2025-04-18', "Good Friday"),
    ('2025-04-21', "Family Day"),
    ('2025-04-27', "Freedom Day"),
    ('2025-04-28', "Freedom Day (observed)"),
    ('2025-05-01', "Workers' Day"),
    ('2025-06-16', "Youth Day"),
    ('2025-08-09', "National Women's Day"),
    ('2025-08-11', "National Women's Day (observed)"),
    ('2025-09-24', "Heritage Day"),
    ('2025-12-16', "Day of Reconciliation"),
    ('2025-12-25', "Christmas Day"),
    ('2025-12-26', "Day of Goodwill")
]

def execute_migration():
    # Check if database file exists
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file '{DB_PATH}' not found.")
        return False
    
    # Connect to the database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 1. Create the holiday table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS holiday (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            date DATE NOT NULL,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            is_paid BOOLEAN DEFAULT 1,
            FOREIGN KEY (company_id) REFERENCES company (id),
            UNIQUE (company_id, date)
        )
        ''')
        print("Created holiday table")
        
        # 2. Get all companies to add default South African holidays
        cursor.execute("SELECT id, name FROM company")
        companies = cursor.fetchall()
        
        for company_id, company_name in companies:
            print(f"Adding default South African holidays for {company_name}...")
            
            # Check how many holidays this company already has
            cursor.execute("SELECT COUNT(*) FROM holiday WHERE company_id = ?", (company_id,))
            holiday_count = cursor.fetchone()[0]
            
            if holiday_count == 0:
                # Add default South African holidays
                for date_str, name in SOUTH_AFRICAN_HOLIDAYS:
                    cursor.execute('''
                    INSERT INTO holiday (company_id, date, name, is_paid)
                    VALUES (?, ?, ?, 1)
                    ''', (company_id, date_str, name))
                
                print(f"Added {len(SOUTH_AFRICAN_HOLIDAYS)} default holidays")
            else:
                print(f"Company already has {holiday_count} holidays, skipping defaults")
        
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
    print("Starting database migration for holiday management...")
    success = execute_migration()
    
    if success:
        print("\nMigration completed successfully!")
        print("Your TimeTracker application now supports holiday management.")
        print("\nNext steps:")
        print("1. Restart your TimeTracker application")
        print("2. Access the new 'Holidays' page from the management menu")
        print("3. Default South African holidays have been added")
        print("4. You can add, edit or remove holidays as needed")
    else:
        print("\nMigration failed. Please check the error messages above.")
        print("You may need to provide the correct path to your database file.")