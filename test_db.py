#!/usr/bin/env python3
"""Simple test script to check database connectivity"""

import os
import redis
import psycopg2
from datetime import datetime

def test_secrets():
    """Test if secrets are readable"""
    print("🔐 Testing secrets...")
    
    secrets = ['valkey_password', 'postgres_password', 'auth_password']
    for secret in secrets:
        path = f'secrets/{secret}'
        if os.path.exists(path):
            with open(path, 'r') as f:
                content = f.read().strip()
                print(f"✅ {secret}: {'[REDACTED]' if content else '[EMPTY]'}")
        else:
            print(f"❌ {secret}: NOT FOUND")

def test_valkey():
    """Test Valkey connection"""
    print("\n📡 Testing Valkey connection...")
    
    try:
        # Read password from secrets
        with open('secrets/valkey_password', 'r') as f:
            password = f.read().strip()
        
        client = redis.Redis(
            host='database-valkey-do-user-25716918-0.m.db.ondigitalocean.com',
            port=25061,
            username='default',
            password=password,
            ssl=True,
            ssl_cert_reqs=None,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
        
        result = client.ping()
        print(f"✅ Valkey connection: {'SUCCESS' if result else 'FAILED'}")
        return True
        
    except Exception as e:
        print(f"❌ Valkey connection failed: {e}")
        return False

def test_postgres():
    """Test PostgreSQL connection"""
    print("\n🐘 Testing PostgreSQL connection...")
    
    try:
        # Read password from secrets
        with open('secrets/postgres_password', 'r') as f:
            password = f.read().strip()
        
        conn = psycopg2.connect(
            host='database-postgresql-do-user-25716918-0.d.db.ondigitalocean.com',
            port=25060,
            database='defaultdb',
            user='doadmin',
            password=password,
            sslmode='require',
            connect_timeout=10
        )
        
        cursor = conn.cursor()
        cursor.execute('SELECT version()')
        version = cursor.fetchone()
        print(f"✅ PostgreSQL connection: SUCCESS")
        print(f"   Version: {version[0][:50]}...")
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ PostgreSQL connection failed: {e}")
        return False

if __name__ == "__main__":
    print(f"🧪 Database Connectivity Test - {datetime.now()}")
    print("=" * 50)
    
    test_secrets()
    valkey_ok = test_valkey()
    postgres_ok = test_postgres()
    
    print("\n📊 Summary:")
    print(f"   Valkey: {'✅ OK' if valkey_ok else '❌ FAILED'}")
    print(f"   PostgreSQL: {'✅ OK' if postgres_ok else '❌ FAILED'}")
    
    if valkey_ok and postgres_ok:
        print("\n🎉 All database connections working!")
    else:
        print("\n⚠️  Some connections failed - check configuration")