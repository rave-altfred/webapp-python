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
DROPLET_IP="164.90.240.205"  # Reserved IP address

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
    
    # No app changes detected, check if we have image locally
    if ! docker image inspect "${FULL_IMAGE_NAME}" >/dev/null 2>&1; then
        log "Image not found locally but no app changes, attempting to pull from registry"
        if docker pull "${FULL_IMAGE_NAME}" >/dev/null 2>&1; then
            success "Successfully pulled existing image from registry for deployment"
        else
            log "Could not pull from registry, build needed"
            return 0
        fi
    fi
    
    log "No changes detected and image available, skipping build"
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
    
    # Keep the current image locally for future build caching
    log "Keeping current image locally for future build caching"
    
    # Only clean up dangling/unused images to save space
    local cleaned=$(docker image prune -f 2>&1 | grep "Total reclaimed space" || echo "No dangling images to clean")
    log "Cleaned up dangling images: $cleaned"
    
    success "Image kept locally for future build caching"
}

# Setup Let's Encrypt SSL certificate
setup_letsencrypt_certificate() {
    local domain="$1"
    log "Setting up Let's Encrypt certificate for ${domain}"
    
    # Install certbot if not already installed
    ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" "
        if ! command -v certbot &> /dev/null; then
            log 'Installing certbot...'
            apt-get update && apt-get install -y certbot
        fi
    "
    
    # Stop nginx temporarily for standalone authentication
    log "Temporarily stopping nginx for certificate generation"
    ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" "
        cd /opt/webapp-python && 
        docker-compose -f docker-compose.production.yml stop nginx 2>/dev/null || true
    "
    
    # Generate Let's Encrypt certificate
    log "Generating Let's Encrypt certificate for ${domain}"
    if ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" "
        certbot certonly --standalone \
            --preferred-challenges http \
            --email admin@altfred.com \
            --agree-tos \
            --no-eff-email \
            --non-interactive \
            -d ${domain}
    "; then
        # Copy certificates to nginx ssl directory
        log "Copying Let's Encrypt certificates to nginx directory"
        ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" "
            cp /etc/letsencrypt/live/${domain}/fullchain.pem /opt/webapp-python/ssl/cert.pem &&
            cp /etc/letsencrypt/live/${domain}/privkey.pem /opt/webapp-python/ssl/key.pem &&
            chmod 644 /opt/webapp-python/ssl/cert.pem &&
            chmod 600 /opt/webapp-python/ssl/key.pem
        "
        
        # Set up automatic renewal hook
        ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" "
            mkdir -p /etc/letsencrypt/renewal-hooks/deploy
            cat > /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh << 'EOF'
#!/bin/bash
# Copy renewed certificates and reload nginx
cp /etc/letsencrypt/live/${domain}/fullchain.pem /opt/webapp-python/ssl/cert.pem
cp /etc/letsencrypt/live/${domain}/privkey.pem /opt/webapp-python/ssl/key.pem
chmod 644 /opt/webapp-python/ssl/cert.pem
chmod 600 /opt/webapp-python/ssl/key.pem
cd /opt/webapp-python && docker-compose -f docker-compose.production.yml restart nginx
EOF
            chmod +x /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh
        "
        success "Let's Encrypt certificate generated successfully for ${domain}"
    else
        error "Failed to generate Let's Encrypt certificate, falling back to self-signed"
        setup_selfsigned_certificate "$domain"
    fi
}

# Setup self-signed SSL certificate
setup_selfsigned_certificate() {
    local domain="$1"
    log "Generating self-signed certificate for ${domain}"
    
    local subject_alt_name=""
    if [[ "$domain" =~ ^[0-9.]+$ ]]; then
        # IP address
        subject_alt_name="IP:${domain}"
    else
        # Domain name
        subject_alt_name="DNS:${domain}"
    fi
    
    ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" "cd /opt/webapp-python && \
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout ssl/key.pem -out ssl/cert.pem \
            -subj '/C=US/ST=DE/L=Frankfurt/O=Altfred/CN=${domain}' \
            -addext 'subjectAltName=${subject_alt_name}'"
    
    if [ $? -ne 0 ]; then
        error "Failed to generate self-signed certificate"
        exit 1
    fi
    success "Self-signed certificate generated successfully for ${domain}"
}

# Copy configuration files to droplet
copy_config_files() {
    log "Copying configuration files to droplet..."
    
    local config_files=(
        "docker-compose.production.yml"
        "production.config.json"
        ".env"
        "nginx.conf"
    )
    
    local secret_dirs=(
        "secrets"
    )
    
    # Create secure secrets files from environment variables
    log "Creating Docker secrets files securely"
    
    # Handle existing secrets directory gracefully
    if [ -d "secrets" ]; then
        log "Updating existing secrets files"
        # Make existing secrets writable so they can be updated
        chmod -R 644 secrets/* 2>/dev/null || true
    else
        log "Creating new secrets directory"
        mkdir -p secrets
    fi
    
    # Read sensitive values from environment variables (REQUIRED)
    if [ -z "${VALKEY_PASSWORD:-}" ]; then
        error "VALKEY_PASSWORD environment variable is required"
        exit 1
    fi
    if [ -z "${POSTGRES_PASSWORD:-}" ]; then
        error "POSTGRES_PASSWORD environment variable is required"
        exit 1
    fi
    if [ -z "${AUTH_PASSWORD:-}" ]; then
        error "AUTH_PASSWORD environment variable is required"
        exit 1
    fi
    if [ -z "${SPACES_SECRET_KEY:-}" ]; then
        error "SPACES_SECRET_KEY environment variable is required"
        exit 1
    fi
    
    VALKEY_PASSWORD="$VALKEY_PASSWORD"
    POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
    AUTH_PASSWORD="$AUTH_PASSWORD"
    SECURITY_TOKEN="${SECURITY_TOKEN:-}"  # Optional
    SPACES_SECRET_KEY="$SPACES_SECRET_KEY"
    
    # Create secrets files (these will NOT be committed to git)
    echo "$VALKEY_PASSWORD" > secrets/valkey_password
    echo "$POSTGRES_PASSWORD" > secrets/postgres_password
    echo "$AUTH_PASSWORD" > secrets/auth_password
    echo "$SECURITY_TOKEN" > secrets/security_token
    echo "$SPACES_SECRET_KEY" > secrets/spaces_secret_key
    
    # Set secure permissions
    chmod 400 secrets/*
    
    # Create clean .env file with non-sensitive values
    log "Creating non-sensitive .env file"
    cp .env.secrets .env
    
    success "Secrets files created securely"
    
    # Create directories on droplet
    if ! ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" "mkdir -p /opt/webapp-python/ssl /opt/webapp-python/secrets"; then
        error "Failed to create directories on droplet"
        exit 1
    fi
    
    # Get domain from .env file
    local DOMAIN_NAME=$(grep '^DOMAIN_NAME=' .env | cut -d'=' -f2 | tr -d '"')
    if [ -z "$DOMAIN_NAME" ]; then
        DOMAIN_NAME="${DROPLET_IP}"  # Fallback to IP
    fi
    
    log "Checking SSL certificate for ${DOMAIN_NAME}"
    
    # Check if valid certificate exists
    CERT_VALID=$(ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" \
        "cd /opt/webapp-python && \
        if [ -f ssl/cert.pem ] && [ -f ssl/key.pem ]; then \
            openssl x509 -in ssl/cert.pem -checkend 2592000 -noout 2>/dev/null && \
            openssl x509 -in ssl/cert.pem -text -noout | grep -q '${DOMAIN_NAME}' && \
            echo 'valid' || echo 'invalid'; \
        else \
            echo 'missing'; \
        fi" 2>/dev/null || echo 'missing')
    
    if [ "$CERT_VALID" = "valid" ]; then
        log "Existing SSL certificate is valid for ${DOMAIN_NAME}, skipping generation"
    else
        log "Setting up SSL certificate for ${DOMAIN_NAME} (${CERT_VALID:-missing} certificate)"
        
        # Check if domain looks like a real domain (not an IP)
        if [[ "$DOMAIN_NAME" =~ ^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
            log "Domain ${DOMAIN_NAME} detected - using Let's Encrypt"
            setup_letsencrypt_certificate "$DOMAIN_NAME"
        else
            log "IP address or invalid domain ${DOMAIN_NAME} detected - using self-signed certificate"
            setup_selfsigned_certificate "$DOMAIN_NAME"
        fi
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
    
    # Copy secrets directory securely
    log "Copying secrets directory to droplet..."
    if [ -d "secrets" ]; then
        if ! scp -o StrictHostKeyChecking=no -r secrets/ root@"${DROPLET_IP}":/opt/webapp-python/; then
            error "Failed to copy secrets directory"
            exit 1
        fi
        
        # Set secure permissions on secrets files on the droplet
        # Make secrets readable by the webapp user (UID 1000) in the container
        if ! ssh -o StrictHostKeyChecking=no root@"${DROPLET_IP}" "chmod -R 444 /opt/webapp-python/secrets/* && chown -R root:root /opt/webapp-python/secrets"; then
            error "Failed to set secure permissions on secrets"
            exit 1
        fi
        
        success "Secrets directory copied and secured successfully"
    else
        error "Secrets directory not found"
        exit 1
    fi
}

# Deploy to droplet
deploy_to_droplet() {
    log "Deploying to droplet: ${DROPLET_IP}"
    
    # Get registry authentication token
    local registry_token=""
    if command -v doctl >/dev/null 2>&1; then
        local auth_string=$(doctl registry docker-config --expiry-seconds 3600 2>/dev/null | jq -r '.auths."registry.digitalocean.com".auth' || echo "")
        if [ -n "$auth_string" ] && [ "$auth_string" != "null" ]; then
            registry_token=$(echo "$auth_string" | base64 -d | cut -d: -f2)
        fi
    fi
    
    # Create deployment script to run on the droplet
    local deploy_script=$(cat << EOF
#!/bin/bash
set -euo pipefail

echo "[INFO] Starting deployment on droplet..."

# Navigate to app directory
cd /opt/webapp-python

# Authenticate with Docker registry using local credentials
echo "[INFO] Authenticating with DigitalOcean registry..."
if [ -n "${registry_token}" ]; then
    echo "${registry_token}" | docker login registry.digitalocean.com --username unused --password-stdin
    echo "[INFO] Registry authentication successful"
else
    echo "[WARNING] No registry token provided, using existing credentials"
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

echo "[INFO] Recent nginx logs:"
docker-compose -f docker-compose.production.yml logs nginx --tail=5

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
        
        # Test health endpoint (should work without auth, accept both 200 and 503)
        local health_code=$(curl -s -k -o /dev/null -w "%{http_code}" "$health_url" 2>/dev/null || echo "000")
        if [ "$health_code" = "200" ] || [ "$health_code" = "503" ]; then
            success "Health check passed! Application is responding (HTTP $health_code)."
            
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
    echo "    • Password: [Set via AUTH_PASSWORD environment variable]"
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
    
    # Auto-load environment variables if .env.local exists
    if [ -f ".env.local" ]; then
        log "Loading environment variables from .env.local"
        set -a  # automatically export all variables
        source .env.local
        set +a  # stop auto-exporting
        success "Environment variables loaded from .env.local"
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
