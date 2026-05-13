# Migration Versions

This directory contains Alembic migration scripts.

## Usage

```bash
# Create a new migration (auto-detect changes)
alembic revision --autogenerate -m "description"

# Apply all pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View current revision
alembic current

# View migration history
alembic history
```
