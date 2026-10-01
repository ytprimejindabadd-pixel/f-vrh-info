#!/bin/bash
set -e

echo "Installing system dependencies..."
apt-get update -qq || true
apt-get install -y -qq \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    || true

pip install --upgrade pip
pip install -r requirements.txt

playwright install chromium
playwright install-deps chromium || true

echo "✅ Build complete!"
