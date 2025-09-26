#!/bin/bash

# Create Docker Secrets from Environment Variables
# This script creates secrets files from environment variables for secure deployment

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Main function to create secrets
create_secrets() {
    log "Creating Docker secrets from environment variables..."
    
    # Ensure we're in the right directory
    if [ ! -f "app.py" ]; then
        error "app.py not found. Make sure you're running this script from the webapp-python directory."
        exit 1
    fi
    
    # Create secrets directory
    mkdir -p secrets
    
    # Check for required environment variables and create secrets files
    local secrets_created=0
    
    # Valkey password
    if [ -n "${VALKEY_PASSWORD:-}" ]; then
        echo "$VALKEY_PASSWORD" > secrets/valkey_password
        success "Created secrets/valkey_password"
        secrets_created=$((secrets_created + 1))
    else
        error "VALKEY_PASSWORD environment variable not set"
    fi
    
    # PostgreSQL password
    if [ -n "${POSTGRES_PASSWORD:-}" ]; then
        echo "$POSTGRES_PASSWORD" > secrets/postgres_password
        success "Created secrets/postgres_password"
        secrets_created=$((secrets_created + 1))
    else
        error "POSTGRES_PASSWORD environment variable not set"
    fi
    
    # Auth password
    if [ -n "${AUTH_PASSWORD:-}" ]; then
        echo "$AUTH_PASSWORD" > secrets/auth_password
        success "Created secrets/auth_password"
        secrets_created=$((secrets_created + 1))
    else
        error "AUTH_PASSWORD environment variable not set"
    fi
    
    # Security token (optional)
    if [ -n "${SECURITY_TOKEN:-}" ]; then
        echo "$SECURITY_TOKEN" > secrets/security_token
        success "Created secrets/security_token"
        secrets_created=$((secrets_created + 1))
    else
        warning "SECURITY_TOKEN environment variable not set (optional)"
        echo "" > secrets/security_token  # Create empty file
    fi
    
    # Spaces secret key
    if [ -n "${SPACES_SECRET_KEY:-}" ]; then
        echo "$SPACES_SECRET_KEY" > secrets/spaces_secret_key
        success "Created secrets/spaces_secret_key"
        secrets_created=$((secrets_created + 1))
    else
        error "SPACES_SECRET_KEY environment variable not set"
    fi
    
    # Set secure permissions
    if [ $secrets_created -gt 0 ]; then
        chmod 400 secrets/*
        success "Set secure permissions (400) on all secret files"
        
        # Display summary
        log "Secrets creation summary:"
        echo "  Total secrets created: $secrets_created"
        echo "  Files created in ./secrets/:"
        ls -la secrets/ | grep -v "^total" | grep -v "README.md" | grep -v ".example-"
        
        success "All secrets created successfully!"
        
        warning "⚠️  SECURITY REMINDER:"
        warning "   - These files contain sensitive credentials"
        warning "   - They are excluded from git via .gitignore"
        warning "   - Never commit these files to version control"
        warning "   - Keep these files secure and restrict access"
        
    else
        error "No secrets were created successfully"
        exit 1
    fi
}

# Show usage information
show_usage() {
    cat << EOF
Usage: $0

This script creates Docker secrets files from environment variables.

Required environment variables:
  VALKEY_PASSWORD       - Password for Valkey (Redis) database
  POSTGRES_PASSWORD     - Password for PostgreSQL database
  AUTH_PASSWORD         - HTTP Basic Auth password for web interface
  SPACES_SECRET_KEY     - DigitalOcean Spaces secret key

Optional environment variables:
  SECURITY_TOKEN        - Optional API security token

Example usage:
  export VALKEY_PASSWORD="your_valkey_password"
  export POSTGRES_PASSWORD="your_postgres_password"
  export AUTH_PASSWORD="your_secure_auth_password"
  export SPACES_SECRET_KEY="your_spaces_secret_key"
  export SECURITY_TOKEN="your_optional_token"
  
  ./create-secrets.sh

The secrets files will be created in the ./secrets/ directory.
EOF
}

# Main execution
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    show_usage
    exit 0
fi

create_secrets

log "🔒 Docker secrets setup completed!"