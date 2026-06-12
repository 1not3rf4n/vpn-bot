#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

echo "========================================="
echo "   Updating VPN Telegram Bot Project     "
echo "========================================="

# 1. Pull latest code changes
echo "-> 1. Fetching latest changes from git..."
git pull

# 2. Update dependencies
echo "-> 2. Skipping requirements update..."
# if [ -d "venv" ]; then
#     source venv/bin/activate
#     pip install --upgrade pip
#     pip install -r requirements.txt
# else
#     echo "⚠️ Warning: venv folder not found. Installing requirements on system Python..."
#     pip install -r requirements.txt
# fi

# 3. Run migrations
echo "-> 3. Running database migrations..."
if [ -f "alembic.ini" ]; then
    alembic upgrade head
else
    echo "⚠️ Warning: alembic.ini not found. Skipping migrations."
fi

# 4. Restart vpn-bot service
echo "-> 4. Restarting vpn-bot systemd service..."
sudo systemctl daemon-reload
sudo systemctl restart vpn-bot

# 5. Show service status
echo "-> 5. Fetching service status..."
sudo systemctl status vpn-bot --no-pager -l

echo "========================================="
echo "         Update Completed!               "
echo "========================================="
