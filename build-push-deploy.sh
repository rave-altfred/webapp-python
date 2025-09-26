#!/bin/bash

# Build, Push & Deploy Script for Database Statistics Dashboard
# This script builds the Docker image, pushes it to DigitalOcean Container Registry,
# and deploys it to the management-web-app droplet.

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
REGISTRY="registry.digitalocean.com/altfred-registry"
IMAGE_NAME="webapp-python"
TAG="latest"
FULL_IMAGE_NAME="${REGISTRY}/${IMAGE_NAME}:${TAG}"
DROPLET_NAME="management-web-app"
DROPLET_IP="138.68.100.153"  # Hardcoded for reliability

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
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

# Check if required tools are installed
check_requirements() {
    log "Checking requirements..."
    
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed or not in PATH"
        exit 1
    fi
    
    if ! command -v doctl &> /dev/null; then
        error "doctl (DigitalOcean CLI) is not installed or not in PATH"
        exit 1
    fi
    
    if ! command -v ssh &> /dev/null; then
        error "SSH is not installed or not in PATH"
        exit 1
    fi
    
    success "All required tools are available"
}

# Authenticate with DigitalOcean Container Registry
auth_registry() {
    log "Authenticating with DigitalOcean Container Registry..."
    
    if ! doctl registry login; then
        error "Failed to authenticate with DigitalOcean Container Registry"
        exit 1
    fi
    
    success "Successfully authenticated with registry"
}

# Check if we need to rebuild the Docker image
check_build_needed() {
    # Check if key application files have changed
    local app_files=("app.py" "requirements.txt" "Dockerfile" "templates/" "schema.sql")
    local last_build_file=".last_build_hash"
    
    # Calculate current hash of application files
    local current_hash=""
    for file in "${app_files[@]}"; do
        if [ -e "$file" ]; then
            if [ -d "$file" ]; then
                if command -v sha256sum >/dev/null 2>&1; then
                    current_hash+=$(find "$file" -type f -exec sha256sum {} \; 2>/dev/null | sort | sha256sum | cut -d' ' -f1)
                else
                    current_hash+=$(find "$file" -type f -exec shasum -a 256 {} \; 2>/dev/null | sort | shasum -a 256 | cut -d' ' -f1)
                fi
            else
                if command -v sha256sum >/dev/null 2>&1; then
                    current_hash+=$(sha256sum "$file" 2>/dev/null | cut -d' ' -f1)
                else
                    current_hash+=$(shasum -a 256 "$file" 2>/dev/null | cut -d' ' -f1)
                fi
            fi
        fi
    done
    if command -v sha256sum >/dev/null 2>&1; then
        current_hash=$(echo "$current_hash" | sha256sum | cut -d' ' -f1)
    else
        current_hash=$(echo "$current_hash" | shasum -a 256 | cut -d' ' -f1)
    fi
    
    # Check if image exists locally
    if ! docker image inspect "${FULL_IMAGE_NAME}" >/dev/null 2>&1; then
        log "Image not found locally, build needed"
        return 0
    fi
    
    # Check if we have previous build hash
    if [ ! -f "$last_build_file" ]; then
        log "No previous build hash found, build needed"
        return 0
    fi
    
    local last_hash=$(cat "$last_build_file" 2>/dev/null || echo "")
    if [ "$current_hash" != "$last_hash" ]; then
        log "Application files changed, build needed"
        return 0
    fi
    
    log "No changes detected, skipping build"
    return 1
}

# Build the Docker image for AMD64 architecture
build_image() {
    if ! check_build_needed; then
        success "Using existing image: ${FULL_IMAGE_NAME}"
        export SKIP_PUSH=true
        return 0
    fi
    
    export SKIP_PUSH=false
    
    log "Building Docker image for AMD64: ${FULL_IMAGE_NAME}"
    
    # Build arguments for metadata
    BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
    VERSION=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    VCS_REF=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
    
    # Build for AMD64 platform with cache optimization
    if ! docker buildx build \
        --platform linux/amd64 \
        --build-arg BUILD_DATE="${BUILD_DATE}" \
        --build-arg VERSION="${VERSION}" \
        --build-arg VCS_REF="${VCS_REF}" \
        --tag "${FULL_IMAGE_NAME}" \
        --cache-from "${FULL_IMAGE_NAME}" \
        --load \
        .; then
        error "Failed to build Docker image"
        exit 1
    fi
    
    # Save current hash for future comparisons
    local app_files=("app.py" "requirements.txt" "Dockerfile" "templates/" "schema.sql")
    local current_hash=""
    for file in "${app_files[@]}"; do
        if [ -e "$file" ]; then
            if [ -d "$file" ]; then
                if command -v sha256sum >/dev/null 2>&1; then
                    current_hash+=$(find "$file" -type f -exec sha256sum {} \; 2>/dev/null | sort | sha256sum | cut -d' ' -f1)
                else
                    current_hash+=$(find "$file" -type f -exec shasum -a 256 {} \; 2>/dev/null | sort | shasum -a 256 | cut -d' ' -f1)
                fi
            else
                if command -v sha256sum >/dev/null 2>&1; then
                    current_hash+=$(sha256sum "$file" 2>/dev/null | cut -d' ' -f1)
                else
                    current_hash+=$(shasum -a 256 "$file" 2>/dev/null | cut -d' ' -f1)
                fi
            fi
        fi
    done
    if command -v sha256sum >/dev/null 2>&1; then
        current_hash=$(echo "$current_hash" | sha256sum | cut -d' ' -f1)
    else
        current_hash=$(echo "$current_hash" | shasum -a 256 | cut -d' ' -f1)
    fi
    echo "$current_hash" > .last_build_hash
    
    success "Successfully built image: ${FULL_IMAGE_NAME}"
}

# Push the image to the registry
push_image() {
    if [ "$SKIP_PUSH" = "true" ]; then
        success "Skipping push - using existing image in registry"
        return 0
    fi
    
    log "Pushing image to registry: ${FULL_IMAGE_NAME}"
    
    if ! docker push "${FULL_IMAGE_NAME}"; then
        error "Failed to push image to registry"
        exit 1
    fi
    
    success "Successfully pushed image to registry"
    
    # Clean up local image to save disk space
    log "Cleaning up local image to save disk space"
    if docker rmi "${FULL_IMAGE_NAME}" >/dev/null 2>&1; then
        success "Local image cleaned up successfully"
    else
        warning "Could not remove local image (may be in use)"
    fi
    
    # Also clean up any dangling images
    docker image prune -f >/dev/null 2>&1 || true
}

# Copy configuration files to droplet
copy_config_files() {
    log "Copying configuration files to droplet..."
    
    local config_files=(
        "docker-compose.production.yml"
        "production.config.json"
        ".env"
        "Caddyfile"
    )
    
    # Create a comprehensive .env file with all required values
    log "Creating complete .env file with actual passwords"
    cat > .env << EOF
# Flask Application Configuration
FLASK_APP=app.py
FLASK_ENV=production
FLASK_DEBUG=false

# Server Configuration
HOST=0.0.0.0
PORT=8080
WORKERS=4

# Database Configuration - Valkey (Redis)
VALKEY_HOST=db-redis-ams3-81766-do-user-9636095-0.c.db.ondigitalocean.com
VALKEY_PORT=25061
VALKEY_PASSWORD=${VALKEY_PASSWORD}
VALKEY_SSL=true
VALKEY_SSL_CERT_REQS=required
VALKEY_SSL_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

# Database Configuration - PostgreSQL
POSTGRES_HOST=db-postgresql-ams3-81766-do-user-9636095-0.c.db.ondigitalocean.com
POSTGRES_PORT=25060
POSTGRES_DATABASE=defaultdb
POSTGRES_USER=doadmin
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_SSLMODE=require

# Security Configuration
AUTH_USERNAME=admin
AUTH_PASSWORD=secure_admin_password_2024

# Optional: Additional Security
IP_WHITELIST=
SECURITY_TOKEN=

# Domain Configuration (optional)
DOMAIN_NAME=
EOF
    
    # Create directory on droplet
    if ! ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" "mkdir -p /opt/webapp-python"; then
        error "Failed to create directory on droplet"
        exit 1
    fi
    
    # Copy files
    local files_to_copy=""
    for file in "${config_files[@]}"; do
        if [ -f "$file" ]; then
            files_to_copy+="$file "
        else
            warning "File $file not found, skipping..."
        fi
    done
    
    if [ -n "$files_to_copy" ]; then
        if ! scp -o StrictHostKeyChecking=no $files_to_copy root@"${DROPLET_IP}":/opt/webapp-python/; then
            error "Failed to copy configuration files"
            exit 1
        fi
        success "Configuration files copied successfully"
    else
        error "No configuration files found to copy"
        exit 1
    fi
}

# Deploy to droplet
deploy_to_droplet() {
    log "Deploying to droplet: ${DROPLET_IP}"
    
    # Create deployment script to run on the droplet
    local deploy_script=$(cat << 'EOF'
#!/bin/bash
set -euo pipefail

echo "[INFO] Starting deployment on droplet..."

# Navigate to app directory
cd /opt/webapp-python

# Update Docker registry credentials (refresh auth)
if command -v doctl &> /dev/null; then
    echo "[INFO] Refreshing registry authentication..."
    doctl registry login || echo "[WARNING] doctl not available, using existing credentials"
else
    echo "[INFO] Using existing Docker registry credentials..."
fi

# Pull the latest image
echo "[INFO] Pulling latest image..."
docker pull registry.digitalocean.com/altfred-registry/webapp-python:latest

# Stop existing containers if running
echo "[INFO] Stopping existing containers..."
docker-compose -f docker-compose.production.yml down --remove-orphans || true

# Start new containers
echo "[INFO] Starting new containers..."
docker-compose -f docker-compose.production.yml up -d

# Wait for containers to start
sleep 5

# Clean up old images (keep last 2 versions)
echo "[INFO] Cleaning up old Docker images..."
docker image prune -f || true

# Show status
echo "[INFO] Container status:"
docker-compose -f docker-compose.production.yml ps

# Show recent logs
echo "[INFO] Recent application logs:"
docker-compose -f docker-compose.production.yml logs webapp --tail=5

echo "[SUCCESS] Deployment completed successfully!"
EOF
)
    
    # Execute deployment script on droplet
    if ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" "$deploy_script"; then
        success "Successfully deployed to droplet: ${DROPLET_IP}"
    else
        error "Deployment failed on droplet: ${DROPLET_IP}"
        exit 1
    fi
}

# Health check after deployment
health_check() {
    log "Performing health check..."
    
    local max_attempts=30
    local attempt=1
    local health_url="https://${DROPLET_IP}/health"
    local auth_url="https://${DROPLET_IP}/"
    
    log "Waiting for application to start..."
    sleep 10
    
    while [ $attempt -le $max_attempts ]; do
        log "Health check attempt ${attempt}/${max_attempts}..."
        
        # Test health endpoint (should work without auth)
        if curl -f -s -k "$health_url" > /dev/null; then
            success "Health check passed! Application is responding."
            
            # Show health status
            local health_response=$(curl -s -k "$health_url" 2>/dev/null || echo "Could not retrieve health status")
            log "Health status: $health_response"
            
            # Test authentication (should return 401 without creds)
            local auth_test=$(curl -s -k -o /dev/null -w "%{http_code}" "$auth_url" 2>/dev/null || echo "000")
            if [ "$auth_test" = "401" ]; then
                success "Authentication is properly configured (returns 401 without credentials)"
            else
                warning "Authentication test returned HTTP $auth_test (expected 401)"
            fi
            
            return 0
        fi
        
        if [ $attempt -lt $max_attempts ]; then
            log "Health check failed, retrying in 5 seconds..."
            sleep 5
        fi
        
        ((attempt++))
    done
    
    error "Health check failed after ${max_attempts} attempts"
    warning "The application may still be starting up. You can check manually:"
    warning "  curl -k https://${DROPLET_IP}/health"
    warning "  ssh root@${DROPLET_IP} 'cd /opt/webapp-python && docker-compose -f docker-compose.production.yml logs webapp'"
    return 1
}

# Display final information
show_deployment_info() {
    log "🎉 Deployment Information:"
    echo ""
    echo "  📍 Application URLs:"
    echo "    • Health Check:  https://${DROPLET_IP}/health (no auth required)"
    echo "    • Dashboard:     https://${DROPLET_IP}/ (requires auth)"
    echo "    • API Stats:     https://${DROPLET_IP}/api/stats (requires auth)"
    echo "    • Observations:  https://${DROPLET_IP}/observations (requires auth)"
    echo ""
    echo "  🔐 Authentication (HTTP Basic Auth):"
    echo "    • Username: admin"
    echo "    • Password: secure_admin_password_2024"
    echo ""
    echo "  🐳 Docker Image: ${FULL_IMAGE_NAME}"
    echo "  🖥️  Droplet: ${DROPLET_NAME} (${DROPLET_IP})"
    echo ""
    echo "  📋 Useful Commands:"
    echo "    • Check logs: ssh root@${DROPLET_IP} 'cd /opt/webapp-python && docker-compose -f docker-compose.production.yml logs -f'"
    echo "    • Restart app: ssh root@${DROPLET_IP} 'cd /opt/webapp-python && docker-compose -f docker-compose.production.yml restart'"
    echo "    • Check status: ssh root@${DROPLET_IP} 'cd /opt/webapp-python && docker-compose -f docker-compose.production.yml ps'"
    echo ""
}

# Main execution
main() {
    log "🚀 Starting build-push-deploy process..."
    echo ""
    
    # Change to script directory
    cd "$(dirname "${BASH_SOURCE[0]}")"
    
    # Validate we're in the right directory
    if [ ! -f "app.py" ]; then
        error "app.py not found. Make sure you're running this script from the webapp-python directory."
        exit 1
    fi
    
    # Execute deployment pipeline
    check_requirements
    auth_registry
    build_image
    push_image
    copy_config_files
    deploy_to_droplet
    
    # Perform health check (non-blocking)
    if health_check; then
        success "✅ Full deployment completed successfully!"
    else
        warning "⚠️  Deployment completed but health check failed. Check the application manually."
    fi
    
    show_deployment_info
    
    log "🎯 Deployment pipeline completed!"
}

# Handle script interruption
trap 'error "Script interrupted by user"; exit 130' INT

# Run main function only if script is executed directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
