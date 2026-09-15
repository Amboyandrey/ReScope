"""Helpers every migration uses to put a tenant-scoped table under row-level security.

Lessons baked in, each found by running against a real database rather than reasoning:

- Postgres exempts a table's *owner* from RLS. The API and workers connect as `rescope_app`
  (created in the first migration), a role with CRUD and no DDL; migrations keep the owner.
- A custom GUC that was never set reads as `''`, not NULL, so it's wrapped in `NULLIF` before
  the uuid cast — otherwise an unscoped query raises `invalid input syntax` instead of returning
  zero rows.
- Under `FORCE ROW LEVEL SECURITY`, any command with no applicable policy is denied outright, so
  writes are gated explicitly with the same predicate — a query that forgot to set the tenant
  scope can neither read nor write another tenant's rows.
"""

from alembic import op

APP_ROLE = "rescope_app"
# Dev-only, fine to commit. A role's password is cluster-wide, so rotate it for any real deploy.
APP_ROLE_PASSWORD = "rescope_app_dev_only"

TENANT_GUC = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
USER_GUC = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def enable_tenant_rls(table: str, predicate: str | None = None) -> None:
    """Enable + force RLS on `table` with one policy gating every command by `predicate`
    (default: the row's `tenant_id` equals the request's `app.tenant_id`)."""
    predicate = predicate or f"tenant_id = {TENANT_GUC}"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL USING ({predicate}) WITH CHECK ({predicate})"
    )


def disable_tenant_rls(table: str) -> None:
    """Reverse `enable_tenant_rls` for a downgrade."""
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
