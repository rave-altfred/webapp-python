#!/usr/bin/env python3
"""
Security setup helper for Database Dashboard
Generates secure tokens and retrieves current IP address
"""

import secrets
import string
import requests
import sys

def generate_secure_token(length=64):
    """Generate a cryptographically secure random token."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_password(length=16):
    """Generate a secure password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def get_public_ip():
    """Get your current public IP address."""
    try:
        response = requests.get('https://ipinfo.io/ip', timeout=5)
        return response.text.strip()
    except Exception as e:
        print(f"❌ Could not get public IP: {e}")
        return None

def main():
    print("🔐 Database Dashboard Security Setup")
    print("=" * 50)
    
    # Get current IP
    print("🌐 Getting your current public IP...")
    public_ip = get_public_ip()
    if public_ip:
        print(f"✅ Your public IP: {public_ip}")
    else:
        print("❌ Could not retrieve public IP")
    
    print()
    
    # Generate secure credentials
    print("🔑 Generated secure credentials:")
    print(f"AUTH_USERNAME=admin")
    print(f"AUTH_PASSWORD={generate_password()}")
    print()
    print(f"SECURITY_TOKEN={generate_secure_token()}")
    print()
    if public_ip:
        print(f"ALLOWED_IPS={public_ip}")
        print()
    
    print("📋 Recommended security configurations:")
    print()
    
    # Option 1: Simple password
    print("1️⃣  SIMPLE PASSWORD PROTECTION:")
    print("   AUTH_USERNAME=admin")
    print(f"   AUTH_PASSWORD={generate_password()}")
    print()
    
    # Option 2: IP restriction only
    if public_ip:
        print("2️⃣  IP RESTRICTION ONLY (no password needed):")
        print(f"   ALLOWED_IPS={public_ip}")
        print()
    
    # Option 3: Maximum security
    print("3️⃣  MAXIMUM SECURITY:")
    print("   AUTH_USERNAME=admin")
    print(f"   AUTH_PASSWORD={generate_password()}")
    if public_ip:
        print(f"   ALLOWED_IPS={public_ip}")
    print(f"   SECURITY_TOKEN={generate_secure_token(32)}")
    print()
    
    print("📝 To implement:")
    print("1. Copy .env.security to .env.production")
    print("2. Uncomment and customize the security options you want")
    print("3. Deploy to your droplet")
    print()
    print("🔍 Test locally first:")
    print("   export AUTH_PASSWORD='your-password'")
    print("   python app.py")

if __name__ == "__main__":
    main()