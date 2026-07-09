#!/bin/bash
# update.sh - Pull latest code and restart the backend container
# Run this on the VPS after changes.

set -e

echo "=== Updating gironasa-backend (local folder: backend) ==="

cd "$(dirname "$0")/.."

echo "1. Git pull..."
git pull --rebase || echo "Warning: git pull had issues (maybe uncommitted changes)"

echo "2. Rebuilding and restarting container..."
docker compose pull || true
docker compose up -d --build

echo "3. Checking status..."
docker compose ps

echo "Done. Backend restarted."
echo "Check logs: docker logs -f backend"