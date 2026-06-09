# SQL scripts (legacy reference)

**Schema changes are managed with Alembic**, not manual `psql` applies.

- Models: `src/digital_twin/db/models.py`
- Migrations: `alembic/versions/`
- Apply locally: `uv run alembic upgrade head` (with `DATABASE_URL` set)
- CI/production: **Deploy API** workflow runs `uv run python -m digital_twin.migrate` before Cloud Run deploy

The `001_conversations.sql` and `002_archive_messages.sql` files are kept as historical reference only and match the initial Alembic revision `001_initial`.
