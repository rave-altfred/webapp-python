# Database Statistics Dashboard

A Flask web application that provides real-time monitoring and statistics for Valkey (Redis-compatible) and PostgreSQL databases running in a DigitalOcean VPC.

## Features

- **Real-time Database Monitoring**: Live statistics from both Valkey and PostgreSQL
- **Responsive Dashboard**: Modern, mobile-friendly web interface
- **Health Monitoring**: Built-in health checks and status monitoring
- **Containerized Deployment**: Docker-based deployment with automatic builds
- **HTTPS Support**: Automatic SSL/TLS with Let's Encrypt via Caddy
- **Production Ready**: Includes security headers, rate limiting, and logging
- **Auto-deployment**: Automated CI/CD pipeline for DigitalOcean

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Internet      │────│   Caddy Proxy   │────│  Flask WebApp   │
│                 │    │  (HTTPS/HTTP)   │    │    (Port 8080)  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                       │
                                                       │
                              ┌────────────────────────┼────────────────────────┐
                              │                        │                        │
                              ▼                        ▼                        │
                    ┌─────────────────┐    ┌─────────────────┐                 │
                    │ Valkey Database │    │PostgreSQL DB   │                 │
                    │ (Redis-like)    │    │                 │                 │
                    └─────────────────┘    └─────────────────┘                 │
                                                                                │
                              ┌─────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ DO Container    │
                    │ Registry        │
                    └─────────────────┘
```

## Quick Start

### Prerequisites

- DigitalOcean account with Container Registry enabled
- Valkey/Redis and PostgreSQL databases in the same VPC
- Domain name (optional, for HTTPS)
- Local development environment with:
  - Docker
  - DigitalOcean CLI (`doctl`)
  - SSH access to your droplet

### 1. Clone and Configure

```bash
git clone <your-repo-url>
cd webapp-python
```

### 2. Configure Environment Variables

Edit `.env.production` with your actual database connection details:

```bash
cp .env.production .env.production.local
nano .env.production.local
```

Update the following variables:
- `VALKEY_HOST` - Your Valkey server IP in VPC
- `VALKEY_PASSWORD` - Your Valkey password
- `POSTGRES_HOST` - Your PostgreSQL server IP in VPC
- `POSTGRES_PASSWORD` - Your PostgreSQL password
- `DOMAIN_NAME` - Your domain name (if using HTTPS)

### 3. Deploy

Simply run the automated deployment script:

```bash
./build-push-deploy.sh
```

This script will:
1. Build the Docker image
2. Push to DigitalOcean Container Registry
3. Deploy to your droplet
4. Start services with Caddy reverse proxy
5. Perform health checks

## Manual Deployment

If you prefer manual deployment:

### 1. Build and Push Image

```bash
# Login to DO registry
doctl registry login

# Build image
docker build -t registry.digitalocean.com/altfred-registry/webapp-python:latest .

# Push to registry
docker push registry.digitalocean.com/altfred-registry/webapp-python:latest
```

### 2. Deploy to Droplet

```bash
# Copy files to droplet
scp docker-compose.production.yml production.config.json .env.production Caddyfile root@your-droplet-ip:/opt/webapp-python/

# SSH to droplet and start services
ssh root@your-droplet-ip
cd /opt/webapp-python
docker-compose -f docker-compose.production.yml up -d
```

## Database Setup

### PostgreSQL Schema

Run the included schema on your PostgreSQL database:

```bash
psql -h your-postgres-host -U webapp_user -d webapp_db -f schema.sql
```

### Valkey Configuration

Ensure your Valkey instance is accessible from the webapp droplet and has the correct password configured.

## Configuration Files

- `app.py` - Main Flask application
- `requirements.txt` - Python dependencies
- `Dockerfile` - Container definition
- `docker-compose.production.yml` - Production container configuration
- `production.config.json` - Application configuration
- `.env.production` - Environment variables (passwords, secrets)
- `Caddyfile` - Reverse proxy configuration
- `build-push-deploy.sh` - Automated deployment script
- `schema.sql` - PostgreSQL database schema

## API Endpoints

- `GET /` - Main dashboard
- `GET /api/stats` - Combined database statistics (JSON)
- `GET /api/valkey` - Valkey-specific statistics (JSON)
- `GET /api/postgres` - PostgreSQL-specific statistics (JSON)
- `GET /health` - Health check endpoint

## Monitoring

### Health Checks

The application includes built-in health checks:
- Container health check via Docker
- Application health endpoint at `/health`
- Database connectivity verification

### Logging

Logs are available via Docker:

```bash
# Application logs
docker logs webapp-python

# Caddy logs
docker logs webapp-caddy

# All services
docker-compose -f docker-compose.production.yml logs -f
```

### Metrics

Access real-time metrics through the dashboard at your domain or droplet IP.

## Security Features

- Non-root container execution
- Security headers via Caddy
- Rate limiting
- HTTPS with automatic certificate renewal
- Content Security Policy
- XSS and CSRF protection

## Troubleshooting

### Connection Issues

1. **Cannot connect to databases**:
   - Verify VPC networking and firewall rules
   - Check database credentials in `.env.production`
   - Test connectivity from droplet: `telnet database-ip port`

2. **Docker deployment fails**:
   - Check if registry authentication is valid: `doctl registry login`
   - Verify image exists: `doctl registry repository list-tags webapp-python`

3. **HTTPS not working**:
   - Ensure domain points to droplet IP
   - Check Caddy logs: `docker logs webapp-caddy`
   - Verify port 80/443 are open in firewall

### Performance Tuning

Adjust these settings in `docker-compose.production.yml`:

```yaml
environment:
  - WORKERS=4  # Number of Gunicorn workers
deploy:
  resources:
    limits:
      memory: 512M  # Increase if needed
```

## Development

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Set environment variables for local development
export VALKEY_HOST=localhost
export POSTGRES_HOST=localhost
# ... other variables

# Run development server
python app.py
```

### Testing

```bash
# Test database connections
curl http://localhost:8080/health

# Test API endpoints
curl http://localhost:8080/api/stats
```

## Production Considerations

1. **Security**:
   - Change default passwords in `.env.production`
   - Generate a secure `SECRET_KEY`
   - Review and update Caddy security headers
   - Consider enabling fail2ban on the droplet

2. **Monitoring**:
   - Set up external monitoring for uptime
   - Configure log aggregation
   - Monitor resource usage

3. **Backups**:
   - Regular database backups
   - Container registry backup
   - Configuration file backups

4. **Scaling**:
   - Use load balancers for high availability
   - Consider horizontal scaling with multiple droplets
   - Database connection pooling

## Support

For issues and questions:
1. Check the logs first
2. Verify database connectivity
3. Review configuration files
4. Check DigitalOcean droplet resources

## License

This project is licensed under the MIT License.