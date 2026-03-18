#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Start postgres if not running
if ! pg_isready -q 2>/dev/null; then
  echo "Starting PostgreSQL..."
  sudo service postgresql start
  sleep 1
fi

# Create DB and user if they don't exist
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='postgres'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE USER postgres WITH SUPERUSER PASSWORD 'postgres';"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='hindsightbot'" | grep -q 1 || \
  sudo -u postgres createdb -O postgres hindsightbot

# Build Tailwind CSS
if [ ! -f ./tailwindcss ]; then
  bash scripts/download_tailwind.sh
fi
./tailwindcss -i web/input.css -o web/static/styles.css --minify

# Run migrations
uv run --env-file .env alembic upgrade head

# Start app
uv run --env-file .env uvicorn web.main:app --reload
