"""
Migration script to add custom fields functionality.
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
        # 1. Create custom_field table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_field (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            field_type VARCHAR(50) NOT NULL,
            is_required BOOLEAN DEFAULT 0,
            description TEXT,
            FOREIGN KEY (company_id) REFERENCES company (id),
            UNIQUE (company_id, name)
        )
        ''')
        print("Created custom_field table")
        
        # 2. Create custom_field_value table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_field_value (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            custom_field_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            text_value TEXT,
            number_value FLOAT,
            boolean_value BOOLEAN,
            date_value DATE,
            FOREIGN KEY (custom_field_id) REFERENCES custom_field (id),
            FOREIGN KEY (employee_id) REFERENCES employee (id),
            UNIQUE (custom_field_id, employee_id)
        )
        ''')
        print("Created custom_field_value table")
        
        # 3. Create import_config table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS import_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            field_name VARCHAR(100) NOT NULL,
            is_standard BOOLEAN DEFAULT 1,
            is_required BOOLEAN DEFAULT 0,
            FOREIGN KEY (company_id) REFERENCES company (id),
            UNIQUE (company_id, field_name)
        )
        ''')
        print("Created import_config table")
        
        # 4. Add default import configuration for each company
        cursor.execute("SELECT id, name FROM company")
        companies = cursor.fetchall()
        
        # Standard field names
        standard_fields = [
            ('first_name', 1),  # Required by default
            ('last_name', 1),   # Required by default
            ('email', 0),       # Optional by default
            ('phone', 0),       # Optional by default
            ('title', 1),       # Required by default
            ('location', 1),    # Required by default
            ('hourly_rate', 0), # Optional by default
            ('overtime_rate', 0), # Optional by default
            ('weekend_rate', 0), # Optional by default
            ('is_sunday_worker', 0), # Optional by default
            ('is_holiday_worker', 0), # Optional by default
            ('is_night_worker', 0),  # Optional by default
            ('night_shift_allowance', 0), # Optional by default
            ('additional_info', 0)    # Optional by default
        ]
        
        for company_id, company_name in companies:
            print(f"Adding default import configuration for {company_name}...")
            
            # Check if company already has import configuration
            cursor.execute("SELECT COUNT(*) FROM import_config WHERE company_id = ?", (company_id,))
            config_count = cursor.fetchone()[0]
            
            if config_count == 0:
                # Add default import configuration
                for field_name, is_required in standard_fields:
                    cursor.execute('''
                    INSERT INTO import_config (company_id, field_name, is_standard, is_required)
                    VALUES (?, ?, 1, ?)
                    ''', (company_id, field_name, is_required))
                
                print(f"Added default import configuration with {len(standard_fields)} fields")
            else:
                print(f"Company already has import configuration, skipping defaults")
        
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
    print("Starting database migration for custom fields...")
    success = execute_migration()
    
    if success:
        print("\nMigration completed successfully!")
        print("Your TimeTracker application now supports custom fields and flexible import configuration.")
        print("\nNext steps:")
        print("1. Restart your TimeTracker application")
        print("2. Access the new 'Import Configuration' page from the Employees dropdown menu")
        print("3. Define which fields are required and add any custom fields")
        print("4. Import employees with your customized configuration")
    else:
        print("\nMigration failed. Please check the error messages above.")
        print("You may need to provide the correct path to your database file.")