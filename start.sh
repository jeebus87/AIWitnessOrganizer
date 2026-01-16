#!/bin/bash
set -e
set -x  # Print commands for debugging

echo "--- STARTUP DEBUG INFO ---"
echo "Current directory: $(pwd)"
ls -la
echo "Python version: $(python --version)"
echo "Checking uvicorn installation..."
pip show uvicorn
echo "Checking critical modules..."
python -c "import magic; import pdf2image; print('Modules ok')"
echo "--- END DEBUG INFO ---"

echo "Running database migrations..."
alembic upgrade head

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT
