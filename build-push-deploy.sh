#!/bin/bash

# Build, Push & Deploy Script for Database Statistics Dashboard
# This script builds the Docker image, pushes it to DigitalOcean Container Registry,
# and deploys it to a droplet via SSH.

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
REGISTRY="registry.digitalocean.com/altfred-registry"
IMAGE_NAME="webapp-python"
TAG="latest"
FULL_IMAGE_NAME="${REGISTRY}/${IMAGE_NAME}:${TAG}"

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

# Build the Docker image with BuildKit cache
build_image() {
    log "Building Docker image: ${FULL_IMAGE_NAME}"
    
    # Build arguments for metadata
    BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
    VERSION=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    VCS_REF=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
    
    # Enable BuildKit for better caching and performance
    export DOCKER_BUILDKIT=1
    
    if ! docker build \
        --build-arg BUILD_DATE="${BUILD_DATE}" \
        --build-arg VERSION="${VERSION}" \
        --build-arg VCS_REF="${VCS_REF}" \
        --tag "${FULL_IMAGE_NAME}" \
        --cache-from "${FULL_IMAGE_NAME}" \
        --pull \
        .; then
        error "Failed to build Docker image"
        exit 1
    fi
    
    success "Successfully built image: ${FULL_IMAGE_NAME}"
}

# Push the image to the registry
push_image() {
    log "Pushing image to registry: ${FULL_IMAGE_NAME}"
    
    if ! docker push "${FULL_IMAGE_NAME}"; then
        error "Failed to push image to registry"
        exit 1
    fi
    
    success "Successfully pushed image to registry"
}

# Get droplet IP using DigitalOcean API
get_droplet_ip() {
    log "Finding droplet IP address..."
    
    # You can customize this to match your droplet name or tag
    DROPLET_NAME="webapp-droplet"
    
    DROPLET_IP=$(doctl compute droplet list --format "Name,PublicIPv4" --no-header | \
                 grep -i "${DROPLET_NAME}" | \
                 awk '{print $2}' | \
                 head -1)
    
    if [ -z "${DROPLET_IP}" ]; then
        # Try finding by tag if name doesn't work
        DROPLET_IP=$(doctl compute droplet list --tag-name "webapp" --format "PublicIPv4" --no-header | head -1)
    fi
    
    if [ -z "${DROPLET_IP}" ]; then
        error "Could not find droplet IP. Please ensure your droplet is named '${DROPLET_NAME}' or tagged with 'webapp'"
        warning "Available droplets:"
        doctl compute droplet list --format "Name,PublicIPv4,Tags"
        exit 1
    fi
    
    success "Found droplet IP: ${DROPLET_IP}"
    echo "${DROPLET_IP}"
}

# Deploy to droplet via SSH
deploy_to_droplet() {
    local droplet_ip=$1
    log "Deploying to droplet: ${droplet_ip}"
    
    # SSH key path - customize as needed
    SSH_KEY_PATH="${HOME}/.ssh/id_rsa"
    SSH_USER="root"  # or your preferred user
    
    if [ ! -f "${SSH_KEY_PATH}" ]; then
        warning "SSH key not found at ${SSH_KEY_PATH}. Using default SSH configuration."
        SSH_OPTIONS=""
    else
        SSH_OPTIONS="-i ${SSH_KEY_PATH}"
    fi
    
    # Create deployment script to run on the droplet
    DEPLOY_SCRIPT=$(cat << 'EOF'
#!/bin/bash
set -euo pipefail

echo "[INFO] Starting deployment on droplet..."

# Navigate to app directory
cd /opt/webapp-python || {
    echo "[ERROR] Application directory not found. Creating it..."
    mkdir -p /opt/webapp-python
    cd /opt/webapp-python
}

# Pull the latest image
echo "[INFO] Pulling latest image..."
docker pull registry.digitalocean.com/altfred-registry/webapp-python:latest

# Stop existing containers if running
echo "[INFO] Stopping existing containers..."
docker-compose -f docker-compose.production.yml down --remove-orphans || true

# Start new containers
echo "[INFO] Starting new containers..."
docker-compose -f docker-compose.production.yml up -d

# Clean up old images
echo "[INFO] Cleaning up old Docker images..."
docker image prune -f

# Show status
echo "[INFO] Deployment completed. Container status:"
docker-compose -f docker-compose.production.yml ps

echo "[SUCCESS] Deployment completed successfully!"
EOF
)
    
    # Copy necessary files to droplet first
    log "Copying configuration files to droplet..."
    
    # Create the app directory on droplet if it doesn't exist
    ssh ${SSH_OPTIONS} -o StrictHostKeyChecking=no "${SSH_USER}@${droplet_ip}" \
        "mkdir -p /opt/webapp-python"
    
    # Copy required files
    scp ${SSH_OPTIONS} -o StrictHostKeyChecking=no \
        docker-compose.production.yml \
        production.config.json \
        .env.production \
        Caddyfile \
        "${SSH_USER}@${droplet_ip}:/opt/webapp-python/"
    
    # Execute deployment script on droplet
    log "Executing deployment on droplet..."
    
    if ssh ${SSH_OPTIONS} -o StrictHostKeyChecking=no "${SSH_USER}@${droplet_ip}" "${DEPLOY_SCRIPT}"; then
        success "Successfully deployed to droplet: ${droplet_ip}"
    else
        error "Deployment failed on droplet: ${droplet_ip}"
        exit 1
    fi
}

# Health check after deployment
health_check() {
    local droplet_ip=$1
    log "Performing health check..."
    
    # Wait a moment for services to start
    sleep 10
    
    MAX_ATTEMPTS=30
    ATTEMPT=1
    
    while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
        if curl -f -s "http://${droplet_ip}:8080/health" > /dev/null; then
            success "Health check passed! Application is running."
            return 0
        fi
        
        log "Health check attempt ${ATTEMPT}/${MAX_ATTEMPTS} failed. Retrying in 5 seconds..."
        sleep 5
        ((ATTEMPT++))
    done
    
    error "Health check failed after ${MAX_ATTEMPTS} attempts"
    return 1
}

# Main execution
main() {
    log "Starting build-push-deploy process..."
    
    # Change to script directory
    cd "$(dirname "${BASH_SOURCE[0]}")"
    
    check_requirements
    auth_registry
    build_image
    push_image
    
    DROPLET_IP=$(get_droplet_ip)
    deploy_to_droplet "${DROPLET_IP}"
    
    if health_check "${DROPLET_IP}"; then
        success "🎉 Deployment completed successfully!"
        log "Application is available at:"
        log "  - HTTP:  http://${DROPLET_IP}"
        log "  - HTTPS: https://your-domain.com (if configured)"
        log "  - Health: http://${DROPLET_IP}:8080/health"
    else
        error "Deployment completed but health check failed. Please check the logs."
        exit 1
    fi
}

# Run main function
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi