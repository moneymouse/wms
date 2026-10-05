#!/bin/bash
# =============================================================================
# Docker Entrypoint Script for WMS Backend
# Waits for database, runs migrations, then starts the application
# =============================================================================

set -e

echo "=== WMS Backend Starting ==="

# ---------------------------------------------------------------------------
# Wait for MySQL to be ready
# ---------------------------------------------------------------------------
echo "Waiting for MySQL to be ready..."

MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if python -c "
from sqlalchemy import create_engine, text
import os
try:
    engine = create_engine(os.environ.get('DATABASE_URL', ''))
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    exit(0)
except Exception as e:
    print(f'Database not ready: {e}')
    exit(1)
" 2>/dev/null; then
        echo "MySQL is ready!"
        break
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Attempt $RETRY_COUNT/$MAX_RETRIES - waiting for database..."
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "ERROR: Could not connect to MySQL after $MAX_RETRIES attempts"
    exit 1
fi

if [ "${FLASK_ENV:-}" = "development" ]; then
    echo "Dev mode, quit"
    exit 1
fi

# ---------------------------------------------------------------------------
# Run Alembic migrations
# ---------------------------------------------------------------------------
echo "migration: ${RUN_MIGRATIONS:-false}"
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    echo "RUN_MIGRATIONS=true, running database migrations..."

    # Check if alembic_version table exists (indicates existing database)
    HAS_VERSION=$(python -c "
from sqlalchemy import create_engine, text, inspect
import os
try:
    engine = create_engine(os.environ.get('DATABASE_URL', ''))
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print('yes' if 'alembic_version' in tables else 'no')
except:
    print('no')
" 2>/dev/null)

    HAS_TABLES=$(python -c "
from sqlalchemy import create_engine, text, inspect
import os
try:
    engine = create_engine(os.environ.get('DATABASE_URL', ''))
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    # Check for main tables (excluding alembic_version)
    main_tables = [t for t in tables if t != 'alembic_version']
    print('yes' if len(main_tables) > 0 else 'no')
except:
    print('no')
" 2>/dev/null)

    if [ "$HAS_VERSION" = "no" ] && [ "$HAS_TABLES" = "yes" ]; then
        if [ -z "${ALEMBIC_BASELINE_REVISION:-}" ] || [ "$ALEMBIC_BASELINE_REVISION" = "head" ] || [ "$ALEMBIC_BASELINE_REVISION" = "heads" ]; then
            echo "ERROR: Existing database has no Alembic version. Set ALEMBIC_BASELINE_REVISION to the verified schema revision before upgrading."
            exit 1
        fi
        echo "Stamping existing database at verified baseline ${ALEMBIC_BASELINE_REVISION}..."
        alembic stamp "$ALEMBIC_BASELINE_REVISION"
        echo "Running pending migrations..."
        alembic upgrade head
    elif [ "$HAS_VERSION" = "no" ] && [ "$HAS_TABLES" = "no" ]; then
        echo "Fresh database detected. Running all migrations..."
        alembic upgrade head
    else
        echo "Running pending migrations..."
        alembic upgrade head
    fi

    echo "Migrations complete!"
else
    echo "RUN_MIGRATIONS=${RUN_MIGRATIONS:-false}, skipping database migrations."
fi

# ---------------------------------------------------------------------------
# Create initial admin user if configured
# ---------------------------------------------------------------------------
if [ -n "$ADMIN_PHONE" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "Checking for initial admin user..."
    python -m scripts.init_admin
fi

# ---------------------------------------------------------------------------
# Start the application
# ---------------------------------------------------------------------------
echo "Starting Gunicorn..."
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 1 \
    --timeout 120 \
    --access-logfile log/access.log \
    --error-logfile log/gunicorn_error.log \
    wsgi:application
