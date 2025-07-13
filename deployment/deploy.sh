#!/bin/bash

# AlphaView Portfolio Dashboard Deployment Script
# Usage: ./deploy.sh [--backup] [--restart-only]

set -e  # Exit on any error

# Configuration
PRODUCTION_SERVER="35.80.141.177"
SSH_KEY="deployment/lightsail-django-8gb.pem"
REMOTE_USER="ubuntu"
REMOTE_PATH="/opt/alphaview"
LOCAL_SOURCE="src/alphaview_fully_functional.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if SSH key exists
if [ ! -f "$SSH_KEY" ]; then
    log_error "SSH key not found at $SSH_KEY"
    exit 1
fi

# Check if source file exists
if [ ! -f "$LOCAL_SOURCE" ]; then
    log_error "Source file not found at $LOCAL_SOURCE"
    exit 1
fi

# Parse command line arguments
BACKUP=false
RESTART_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --backup)
            BACKUP=true
            shift
            ;;
        --restart-only)
            RESTART_ONLY=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Usage: $0 [--backup] [--restart-only]"
            exit 1
            ;;
    esac
done

# Create backup if requested
if [ "$BACKUP" = true ]; then
    log_info "Creating backup of current deployment..."
    BACKUP_NAME="alphaview_backup_$(date +%Y%m%d_%H%M%S).py"
    ssh -i "$SSH_KEY" "$REMOTE_USER@$PRODUCTION_SERVER" \
        "cp $REMOTE_PATH/alphaview_fully_functional.py $REMOTE_PATH/$BACKUP_NAME"
    log_info "Backup created: $BACKUP_NAME"
fi

# Deploy new code (unless restart-only)
if [ "$RESTART_ONLY" = false ]; then
    log_info "Deploying new code to production server..."
    scp -i "$SSH_KEY" "$LOCAL_SOURCE" "$REMOTE_USER@$PRODUCTION_SERVER:$REMOTE_PATH/"
    log_info "Code deployment complete"
fi

# Restart the service
log_info "Restarting AlphaView service..."
ssh -i "$SSH_KEY" "$REMOTE_USER@$PRODUCTION_SERVER" "sudo systemctl restart alphaview"

# Check service status
log_info "Checking service status..."
sleep 3
ssh -i "$SSH_KEY" "$REMOTE_USER@$PRODUCTION_SERVER" "sudo systemctl is-active alphaview" > /dev/null

if [ $? -eq 0 ]; then
    log_info "✅ Deployment successful! Service is running."
    log_info "Dashboard available at: http://$PRODUCTION_SERVER"
else
    log_error "❌ Service failed to start. Check logs with:"
    log_error "ssh -i $SSH_KEY $REMOTE_USER@$PRODUCTION_SERVER 'sudo journalctl -u alphaview -f'"
    exit 1
fi