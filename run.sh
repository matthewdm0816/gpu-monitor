#!/usr/bin/env bash
set -e

# Check if uv is installed, fall back to installing it via pip if missing
if ! command -v uv &> /dev/null; then
    echo "'uv' is not installed. Installing uv via pip..."
    pip install --user uv || pip install uv
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment with uv..."
    uv venv
fi

# Sync dependencies
echo "Syncing dependencies..."
uv pip install -r requirements.txt

# Start GPU Monitor
echo "Starting GPU Monitor..."
.venv/bin/python gpu_monitor.py "$@"
