#!/usr/bin/env python3
"""
Local development runner for Database Statistics Dashboard
Loads environment variables from .env.local and starts the Flask app
"""

import os
import sys
from pathlib import Path

def load_env_file(env_file_path):
    """Load environment variables from a file"""
    if not os.path.exists(env_file_path):
        print(f"Environment file {env_file_path} not found!")
        return False
    
    print(f"Loading environment variables from {env_file_path}")
    
    with open(env_file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                
                os.environ[key] = value
                print(f"  {key}={'*' * len(value) if 'PASSWORD' in key.upper() else value}")
    
    return True

def check_dependencies():
    """Check if required packages are installed"""
    try:
        import flask
        import redis
        import psycopg2
        print("✅ All required packages are available")
        return True
    except ImportError as e:
        print(f"❌ Missing required package: {e}")
        print("Please install requirements: pip install -r requirements.txt")
        return False

def test_database_connections():
    """Test database connections before starting the app"""
    print("\n🔍 Testing database connections...")
    
    # Test Valkey/Redis connection
    try:
        import redis
        
        # Connection parameters
        conn_params = {
            'host': os.getenv('VALKEY_HOST', 'localhost'),
            'port': int(os.getenv('VALKEY_PORT', 6379)),
            'db': int(os.getenv('VALKEY_DB', 0)),
            'decode_responses': True,
            'socket_connect_timeout': 2,
            'socket_timeout': 2
        }
        
        # Add authentication
        if os.getenv('VALKEY_USER'):
            conn_params['username'] = os.getenv('VALKEY_USER')
        if os.getenv('VALKEY_PASSWORD'):
            conn_params['password'] = os.getenv('VALKEY_PASSWORD')
            
        client = redis.Redis(**conn_params)
        client.ping()
        print("✅ Valkey/Redis connection successful")
    except Exception as e:
        print(f"⚠️  Valkey/Redis connection failed: {e}")
        print("   The app will still start, but Valkey stats will show errors")
    
    # Test PostgreSQL connection
    try:
        import psycopg2
        
        # Connection parameters
        conn_params = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', 5432)),
            'database': os.getenv('POSTGRES_DATABASE', 'webapp_db_dev'),
            'user': os.getenv('POSTGRES_USER', 'postgres'),
            'password': os.getenv('POSTGRES_PASSWORD'),
            'connect_timeout': 5
        }
        
        # Add SSL for managed databases
        postgres_host = os.getenv('POSTGRES_HOST', 'localhost')
        if 'ondigitalocean.com' in postgres_host or os.getenv('POSTGRES_SSLMODE'):
            conn_params['sslmode'] = os.getenv('POSTGRES_SSLMODE', 'require')
            
        conn = psycopg2.connect(**conn_params)
        conn.close()
        print("✅ PostgreSQL connection successful")
    except Exception as e:
        print(f"⚠️  PostgreSQL connection failed: {e}")
        print("   The app will still start, but PostgreSQL stats will show errors")

def main():
    print("🚀 Starting Database Statistics Dashboard (Local Development)")
    print("=" * 60)
    
    # Load environment variables
    env_file = ".env.local"
    if not load_env_file(env_file):
        sys.exit(1)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Test connections
    test_database_connections()
    
    print(f"\n🌐 Starting Flask development server...")
    print(f"   URL: http://localhost:{os.getenv('APP_PORT', 5000)}")
    print(f"   Health Check: http://localhost:{os.getenv('APP_PORT', 5000)}/health")
    print(f"   API Stats: http://localhost:{os.getenv('APP_PORT', 5000)}/api/stats")
    print("\n📊 Dashboard will auto-refresh every 30 seconds")
    print("🛑 Press Ctrl+C to stop the server")
    print("=" * 60)
    
    # Import and run the Flask app
    try:
        from app import app
        app.run(
            host='0.0.0.0',
            port=int(os.getenv('APP_PORT', 5000)),
            debug=os.getenv('DEBUG', 'false').lower() == 'true'
        )
    except ImportError as e:
        print(f"❌ Error importing app: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 Shutting down development server...")

if __name__ == '__main__':
    main()