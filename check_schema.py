#!/usr/bin/env python3
"""Check database schema for life_stages and profiles tables."""

import pymysql

# Docker container connection (this is where the app runs)
DB_CONFIG = {
    "host": "mysql-database.cc98ouaycdke.us-east-1.rds.amazonaws.com",
    "port": 3306,
    "user": "admin",  # Try admin user
    "password": "Shahrul@123",
    "database": "pulse_mysql",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

def check_schema():
    """Check table schemas."""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("\n" + "="*90)
        print("DATABASE SCHEMA ANALYSIS")
        print("="*90)
        
        # Check life_stages table columns
        print("\n📋 LIFE_STAGES TABLE COLUMNS:")
        print("-" * 90)
        cursor.execute("DESCRIBE life_stages")
        columns = cursor.fetchall()
        if columns:
            for col in columns:
                print(f"   {col['Field']:20s} | {col['Type']:30s} | {col.get('Null', 'YES'):5s}")
        else:
            print("   ❌ life_stages table not found!")
        
        # Check profiles table columns
        print("\n📋 PROFILES TABLE COLUMNS:")
        print("-" * 90)
        cursor.execute("DESCRIBE profiles")
        columns = cursor.fetchall()
        if columns:
            for col in columns:
                print(f"   {col['Field']:20s} | {col['Type']:30s} | {col.get('Null', 'YES'):5s}")
        else:
            print("   ❌ profiles table not found!")
        
        # Check menstrual_cycles table columns
        print("\n📋 MENSTRUAL_CYCLES TABLE COLUMNS:")
        print("-" * 90)
        cursor.execute("DESCRIBE menstrual_cycles")
        columns = cursor.fetchall()
        if columns:
            for col in columns:
                print(f"   {col['Field']:20s} | {col['Type']:30s} | {col.get('Null', 'YES'):5s}")
        else:
            print("   ❌ menstrual_cycles table not found!")
        
        # Show first few rows from each table
        print("\n📊 SAMPLE DATA - life_stages:")
        print("-" * 90)
        cursor.execute("SELECT * FROM life_stages LIMIT 10")
        rows = cursor.fetchall()
        if rows:
            print("   Columns:", list(rows[0].keys()))
            for row in rows:
                print(f"   {row}")
        
        print("\n📊 SAMPLE DATA - profiles (first 3):")
        print("-" * 90)
        cursor.execute("SELECT * FROM profiles LIMIT 3")
        rows = cursor.fetchall()
        if rows:
            print("   Columns:", list(rows[0].keys()))
            for row in rows:
                print(f"   {dict(row)}")
        
        conn.close()
        print("\n" + "="*90 + "\n")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_schema()
