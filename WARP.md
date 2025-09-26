# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

This is a Flask-based database statistics dashboard that monitors Valkey (Redis-compatible) and PostgreSQL databases in a DigitalOcean VPC environment. The application provides real-time monitoring through a web interface and API endpoints.

### Architecture

- **Web Framework**: Flask 2.3.3 with Gunicorn for production
- **Databases**: Valkey (Redis) for caching, PostgreSQL for persistent data
- **Deployment**: Docker containers with Caddy reverse proxy
- **Infrastructure**: DigitalOcean droplets with container registry
- **Frontend**: Server-rendered HTML with responsive dashboard

### Key Components

- `app.py`: Main Flask application with database connection handlers and API endpoints
- `templates/dashboard.html`: Frontend dashboard with real-time statistics display
- `schema.sql`: PostgreSQL database schema with user management and metrics tables
- `production.config.json`: Application configuration for production environment
- `Dockerfile`: Multi-stage build with non-root user and health checks
- `docker-compose.production.yml`: Production deployment with Caddy proxy

## Security: Docker Secrets

This application now uses Docker Compose secrets for secure credential management instead of embedding passwords in environment files.

### Secrets Setup

1. **Create secrets from environment variables:**
   ```bash
   # Set your actual passwords as environment variables
   export VALKEY_PASSWORD="your_actual_valkey_password"
   export POSTGRES_PASSWORD="your_actual_postgres_password"
   export AUTH_PASSWORD="your_secure_web_password"
   export SPACES_SECRET_KEY="your_digitalocean_spaces_secret"
   export SECURITY_TOKEN="your_optional_api_token"  # optional
   
   # Create secrets files securely
   ./create-secrets.sh
   ```

2. **Manual secrets creation:**
   ```bash
   mkdir -p secrets
   echo "your_valkey_password" > secrets/valkey_password
   echo "your_postgres_password" > secrets/postgres_password
   echo "your_auth_password" > secrets/auth_password
   echo "your_security_token" > secrets/security_token  # optional
   echo "your_spaces_secret" > secrets/spaces_secret_key
   
   # Set secure permissions
   chmod 400 secrets/*
   ```

3. **Non-sensitive configuration:**
   ```bash
   # Use the provided template for non-sensitive config
   cp .env.secrets .env
   # Edit .env to adjust non-sensitive settings as needed
   ```

## Development Commands

### Local Development

```bash
# Set up virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Set up secrets (see Security section above)
./create-secrets.sh

# Run development server
python app.py

# Alternative: Run with specific config
CONFIG_FILE=production.config.json python app.py
```

### Testing and Health Checks

```bash
# Test application health
curl http://localhost:8080/health

# Test API endpoints
curl http://localhost:8080/api/stats
curl http://localhost:8080/api/valkey
curl http://localhost:8080/api/postgres

# Test database connections
python -c "
import app
valkey = app.get_valkey_connection()
postgres = app.get_postgres_connection()
print('Valkey:', valkey is not None)
print('PostgreSQL:', postgres is not None)
"
```

### Docker Development

```bash
# Set up secrets first
./create-secrets.sh

# Build image locally
docker build -t webapp-python:dev .

# Run with docker-compose (uses secrets)
docker-compose -f docker-compose.production.yml up -d

# View logs
docker-compose -f docker-compose.production.yml logs -f webapp

# Exec into running container
docker exec -it webapp-python bash

# Verify secrets are mounted correctly
docker exec -it webapp-python ls -la /run/secrets/
```

### Database Management

```bash
# Set up PostgreSQL schema
psql -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DATABASE -f schema.sql

# Test Valkey connection
redis-cli -h $VALKEY_HOST -p $VALKEY_PORT -a $VALKEY_PASSWORD ping

# View application tables
psql -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DATABASE -c "\dt"
```

## Deployment Commands

### Automated Deployment

```bash
# Set up credentials as environment variables first
export VALKEY_PASSWORD="your_actual_valkey_password"
export POSTGRES_PASSWORD="your_actual_postgres_password"
export AUTH_PASSWORD="your_secure_web_password"
export SPACES_SECRET_KEY="your_digitalocean_spaces_secret"
export SECURITY_TOKEN="your_optional_api_token"  # optional

# Full build-push-deploy cycle (now uses secrets)
./build-push-deploy.sh
```

### Manual Deployment

```bash
# Set up secrets first
export VALKEY_PASSWORD="your_actual_valkey_password"
export POSTGRES_PASSWORD="your_actual_postgres_password"
export AUTH_PASSWORD="your_secure_web_password"
export SPACES_SECRET_KEY="your_digitalocean_spaces_secret"
./create-secrets.sh

# Authenticate with DigitalOcean registry
doctl registry login

# Build and push image
docker build -t registry.digitalocean.com/altfred-registry/webapp-python:latest .
docker push registry.digitalocean.com/altfred-registry/webapp-python:latest

# Deploy to droplet (requires SSH access and secrets)
scp docker-compose.production.yml production.config.json .env Caddyfile root@your-droplet-ip:/opt/webapp-python/
scp -r secrets/ root@your-droplet-ip:/opt/webapp-python/
ssh root@your-droplet-ip "cd /opt/webapp-python && chmod -R 400 secrets/* && docker-compose -f docker-compose.production.yml up -d"
```

### Production Monitoring

```bash
# Check deployment status
doctl compute droplet list
ssh root@your-droplet-ip "docker-compose -f /opt/webapp-python/docker-compose.production.yml ps"

# View application logs
ssh root@your-droplet-ip "docker logs webapp-python"
ssh root@your-droplet-ip "docker logs webapp-caddy"

# Monitor resource usage
ssh root@your-droplet-ip "docker stats"
```

## Architecture Details

### Database Connection Pattern

The application uses connection factories (`get_valkey_connection()`, `get_postgres_connection()`) that handle authentication, SSL configuration, and timeouts. Connections are created per request and properly closed to avoid connection leaks.

### Configuration Management

Configuration is loaded hierarchically:
1. Environment variables (highest priority)
2. `production.config.json` file
3. Default values in `load_config()` function

### Error Handling Strategy

Database operations return dictionaries with error messages instead of raising exceptions, allowing the API to provide consistent JSON responses even when databases are unavailable.

### Security Features

- Non-root container execution
- Security headers via Caddy
- SSL/TLS termination with Let's Encrypt
- Connection timeouts to prevent hanging requests
- Resource limits in production deployment

### API Endpoints

- `GET /`: Dashboard interface
- `GET /api/stats`: Combined database statistics
- `GET /api/valkey`: Valkey-specific metrics
- `GET /api/postgres`: PostgreSQL-specific metrics  
- `GET /health`: Health check with database connectivity

## Common Issues and Solutions

### Database Connection Problems

1. Check VPC networking and firewall rules
2. Verify credentials in `.env.production`
3. Test connectivity: `telnet database-ip port`
4. Check SSL requirements for managed databases

### Docker Registry Issues

1. Re-authenticate: `doctl registry login`
2. Verify image exists: `doctl registry repository list-tags webapp-python`
3. Check registry quotas in DigitalOcean console

### HTTPS/Domain Issues

1. Ensure domain DNS points to droplet IP
2. Check Caddy logs: `docker logs webapp-caddy`
3. Verify ports 80/443 are open in firewall
4. Update `DOMAIN_NAME` in `.env.production`

### Performance Tuning

Adjust Gunicorn workers in `docker-compose.production.yml`:
- Increase `WORKERS` for CPU-bound workloads
- Increase memory limits for data-heavy operations
- Monitor with `docker stats` and adjust accordingly

## Development Workflow

1. Make changes to application code
2. Test locally with `python app.py`
3. Verify database connectivity and API responses
4. Build and test Docker image locally
5. Deploy using `./build-push-deploy.sh`
6. Monitor deployment health and logs
7. Commit changes after successful deployment

## Important Files Structure

```
├── app.py                          # Main Flask application
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Container definition with multi-stage build
├── docker-compose.production.yml   # Production deployment configuration (uses secrets)
├── production.config.json          # Application settings
├── .env.secrets                    # Non-sensitive environment variables template
├── .env                           # Non-sensitive environment variables (generated)
├── secrets/                        # Docker secrets directory (NOT in git)
│   ├── README.md                  # Documentation for secrets
│   ├── valkey_password            # Valkey database password
│   ├── postgres_password          # PostgreSQL database password
│   ├── auth_password              # Web interface authentication
│   ├── security_token             # Optional API security token
│   └── spaces_secret_key          # DigitalOcean Spaces secret key
├── create-secrets.sh              # Script to create secrets from environment
├── Caddyfile                       # Reverse proxy configuration
├── build-push-deploy.sh            # Automated deployment script (now uses secrets)
├── schema.sql                      # PostgreSQL database schema
├── templates/dashboard.html        # Frontend dashboard template
└── README.md                       # Comprehensive documentation
```
