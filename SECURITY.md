# Security Setup Guide

## ⚠️ IMPORTANT SECURITY NOTICE

This project now uses **Docker Compose secrets** for secure credential management. **NO credentials should ever be hardcoded in files or committed to git.**

## Setup Requirements

Before deploying or running this application, you MUST set up the following environment variables with your actual credentials:

### Required Environment Variables

```bash
# Database passwords (get these from your DigitalOcean managed databases)
export VALKEY_PASSWORD="your_actual_valkey_password"
export POSTGRES_PASSWORD="your_actual_postgres_password"

# Web interface authentication
export AUTH_PASSWORD="your_secure_web_password"

# DigitalOcean Spaces secret key
export SPACES_SECRET_KEY="your_digitalocean_spaces_secret"

# Optional: API security token
export SECURITY_TOKEN="your_optional_api_token"
```

### Setup Steps

1. **Set environment variables** (see above)

2. **Create secrets files:**
   ```bash
   ./create-secrets.sh
   ```

3. **Deploy:**
   ```bash
   ./build-push-deploy.sh
   ```

## Security Features

✅ **Docker Compose secrets** - Credentials stored as secure files  
✅ **Git protection** - All secret files excluded from version control  
✅ **File permissions** - Secret files have 400 permissions (read-only for owner)  
✅ **Environment validation** - Deployment fails if required credentials are missing  
✅ **No fallbacks** - No hardcoded default passwords  

## Files That Should NEVER Contain Real Credentials

- ❌ Any `.env*` files (except `.env.secrets` template)
- ❌ Source code files
- ❌ Configuration files
- ❌ Shell scripts with hardcoded values
- ❌ Documentation files

## Secure Files (Git-Safe)

- ✅ `.env.secrets` - Template with non-sensitive configuration
- ✅ `secrets/README.md` - Documentation
- ✅ `secrets/.example-*` - Example templates
- ✅ All source code and configuration files

## Getting Your Actual Credentials

### DigitalOcean Managed Databases
1. Go to your DigitalOcean dashboard
2. Navigate to Databases
3. Click on your Valkey/PostgreSQL database
4. Find the connection details and passwords

### Creating Secure Passwords
```bash
# Generate a secure password
openssl rand -base64 32

# Or use a password manager like 1Password, Bitwarden, etc.
```

## Troubleshooting

### "Environment variable is required" Error
This means you haven't set the required environment variables. Set them and try again:

```bash
export VALKEY_PASSWORD="your_password"
export POSTGRES_PASSWORD="your_password"  
export AUTH_PASSWORD="your_password"
export SPACES_SECRET_KEY="your_secret"
./create-secrets.sh
```

### Secrets Not Working
1. Verify secrets files exist: `ls -la secrets/`
2. Check file permissions: `ls -la secrets/` (should be 400)
3. Verify Docker secrets are mounted: `docker exec -it webapp-python ls -la /run/secrets/`

## Contact

If you need help with security setup, contact the development team. **Never share actual credentials in communications.**