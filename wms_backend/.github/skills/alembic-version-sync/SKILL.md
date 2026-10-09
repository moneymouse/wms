---
name: alembic-version-sync
description: "Use when updating Flask/SQLAlchemy table structure, MySQL schema, or migration version files. Generate Alembic revisions in Docker with docker-compose.dev.yml and autogenerate."
---

# Alembic Version Sync (Docker)

## When to Use
- Models, tables, columns, indexes, or foreign keys changed
- Need to generate a new Alembic version for this WMS project
- Local machine does not have Alembic installed

## Required Command
Run this command from repository root:

```bash
docker-compose -f docker-compose.dev.yml run --rm backend alembic revision --autogenerate -m "your commit message"
```

## Recommended Follow-up
Apply the new migration to confirm it works:

```bash
docker-compose -f docker-compose.dev.yml run --rm backend alembic upgrade head
```

## Existing Database Without Alembic Version
If tables already exist but `alembic_version` is missing, stamp first:

```bash
docker-compose -f docker-compose.dev.yml run --rm backend alembic stamp head
```

## Notes
- `alembic/env.py` reads `DATABASE_URL`, and `docker-compose.dev.yml` already points backend to MySQL container.
- Prefer clear migration message text, such as `add_order_customers_association`.
