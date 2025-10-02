#!/usr/bin/env python3
"""
Debug script to check what columns are actually returned by the observations API
and what's in the database.
"""

import json
import psycopg2
from psycopg2.extras import RealDictCursor
import os

def load_config():
    """Load configuration from production.config.json and environment."""
    config = {}
    
    # Load from production.config.json
    try:
        with open('production.config.json', 'r') as f:
            file_config = json.load(f)
            config.update(file_config)
    except FileNotFoundError:
        print("production.config.json not found")
    
    # Load from environment variables (these take precedence)
    env_vars = [
        'POSTGRES_HOST', 'POSTGRES_PORT', 'POSTGRES_DATABASE', 
        'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_SSL_MODE'
    ]
    
    for var in env_vars:
        if var in os.environ:
            config[var] = os.environ[var]
    
    # Load from Docker secrets if available
    secrets_dir = 'secrets'
    secret_mappings = {
        'postgres_password': 'POSTGRES_PASSWORD'
    }
    
    for secret_file, config_key in secret_mappings.items():
        secret_path = os.path.join(secrets_dir, secret_file)
        if os.path.exists(secret_path):
            with open(secret_path, 'r') as f:
                config[config_key] = f.read().strip()
    
    return config

def get_postgres_connection():
    """Get PostgreSQL database connection."""
    config = load_config()
    
    # Print config for debugging (without password)
    print("Database config:")
    for key, value in config.items():
        if 'PASSWORD' not in key and 'POSTGRES' in key:
            print(f"  {key}: {value}")
    
    try:
        conn = psycopg2.connect(
            host=config.get('POSTGRES_HOST'),
            port=config.get('POSTGRES_PORT', 5432),
            database=config.get('POSTGRES_DATABASE'),
            user=config.get('POSTGRES_USER'),
            password=config.get('POSTGRES_PASSWORD'),
            sslmode=config.get('POSTGRES_SSL_MODE', 'require'),
            connect_timeout=10
        )
        return conn
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        return None

def check_observations_table():
    """Check the observations table structure and sample data."""
    conn = get_postgres_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'observations'
            )
        """)
        table_exists = cursor.fetchone()[0]
        print(f"observations table exists: {table_exists}")
        
        if not table_exists:
            print("❌ observations table does not exist!")
            return
        
        # Get table structure
        cursor.execute("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'observations'
            ORDER BY ordinal_position
        """)
        columns = cursor.fetchall()
        print(f"\n📋 observations table structure ({len(columns)} columns):")
        for col in columns:
            print(f"  {col['column_name']}: {col['data_type']} ({'NULL' if col['is_nullable'] == 'YES' else 'NOT NULL'})")
        
        # Check for detection_id specifically
        detection_id_exists = any(col['column_name'] == 'detection_id' for col in columns)
        print(f"\n🔍 detection_id column exists: {detection_id_exists}")
        
        # Get sample data (first 3 rows)
        cursor.execute("SELECT * FROM observations ORDER BY created_at DESC LIMIT 3")
        sample_data = cursor.fetchall()
        print(f"\n📊 Sample data ({len(sample_data)} rows):")
        for i, row in enumerate(sample_data, 1):
            print(f"  Row {i}:")
            for key, value in dict(row).items():
                if 'detection' in key.lower():
                    print(f"    {key}: {value} ⭐")
                else:
                    print(f"    {key}: {value}")
            print()
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Error checking observations table: {e}")
        if conn:
            conn.close()

if __name__ == "__main__":
    print("🔍 Debugging observations API and database...")
    check_observations_table()