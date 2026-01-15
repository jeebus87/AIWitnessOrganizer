#!/bin/bash
set -e

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT
