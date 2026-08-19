#!/usr/bin/env bash
# Render build script — builds the React app, then prepares Django.
set -o errexit

echo "--- frontend build ---"
cd frontend
npm ci
npm run build
cd ..

echo "--- backend setup ---"
cd backend
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
