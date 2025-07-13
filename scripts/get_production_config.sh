#!/bin/bash

# Script to retrieve configuration files from production server
# Usage: ./get_production_config.sh

set -e

PRODUCTION_SERVER="35.80.141.177"
SSH_KEY="../deployment/lightsail-django-8gb.pem"
REMOTE_USER="ubuntu"
REMOTE_PATH="/opt/alphaview"

echo "🔄 Retrieving configuration files from production server..."

# Get cognito_config.py
echo "📥 Downloading cognito_config.py..."
scp -i "$SSH_KEY" "$REMOTE_USER@$PRODUCTION_SERVER:$REMOTE_PATH/cognito_config.py" "../src/"

# Get auth_utils.py
echo "📥 Downloading auth_utils.py..."
scp -i "$SSH_KEY" "$REMOTE_USER@$PRODUCTION_SERVER:$REMOTE_PATH/auth_utils.py" "../src/"

echo "✅ Configuration files retrieved successfully!"
echo "⚠️  Remember: These files contain sensitive information and are gitignored"