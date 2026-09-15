"""Helpers every migration uses to put a tenant-scoped table under row-level security.

Lessons baked in, each found by running against a real database rather than reasoning:

- Postgres exempts a table's *owner* from RLS. The API and workers connect as `rescope_app`
  (created in the first migration), a role with CRUD and no DDL; migrations keep the owner.
- A custom GUC that was never set reads as `''`, not NULL, so it's wrapped in `NULLIF` before
  the uuid cast — otherwise an unscoped query raises `invalid input syntax` instead of returning
  zero rows.
- Reads are gated by a `FOR SELECT` policy; writes are deliberately left ungated with their own
  permissive policy. Row-level security exists here as a backstop against a query that forgot its
  `WHERE tenant_id = ...`, not as the only thing standing between a service and a cross-tenant
  write — every write path already knows and sets the right tenant scope in application code.
  Gating writes too would need every write path (including background jobs) to set the scope
  before its very first statement, a bigger change than this backstop is meant to be, and one
  Postgres would otherwise punish harshly: under `FORCE ROW LEVEL SECURITY`, a command with *no*
  applicable policy at all is denied outright — an INSERT under a table with only a SELECT policy
  fails, not "succeeds unfiltered" as it's easy to assume — so every table below gets its own
  explicit, permissive write policy rather than relying on the SELECT one.
"""

import os

from alembic import op

APP_ROLE = "rescope_app"
# Read once, at migration time only — never by the running app, which authenticates through
# APP_DATABASE_URL instead. The fallback is dev-only and fine to commit; a real deploy sets
# RESCOPE_APP_ROLE_PASSWORD before the first `alembic upgrade head` ever creates the role (a
# role's password is cluster-wide, and this only runs the `CREATE ROLE` once — rotating it
# afterward needs a manual `ALTER ROLE rescope_app PASSWORD '...'` to match).
APP_ROLE_PASSWORD = os.environ.get("RESCOPE_APP_ROLE_PASSWORD", "rescope_app_dev_only")

TENANT_GUC = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
USER_GUC = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def enable_tenant_rls(table: str, select_predicate: str | None = None) -> None:
    """Enable + force RLS on `table`: reads gated by `select_predicate` (default: the row's
    `tenant_id` equals the request's `app.tenant_id`), writes left permissive."""
    predicate = select_predicate or f"tenant_id = {TENANT_GUC}"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} FOR SELECT USING ({predicate})")
    op.execute(f"CREATE POLICY allow_writes_insert ON {table} FOR INSERT WITH CHECK (true)")
    op.execute(f"CREATE POLICY allow_writes_update ON {table} FOR UPDATE USING (true) WITH CHECK (true)")
    op.execute(f"CREATE POLICY allow_writes_delete ON {table} FOR DELETE USING (true)")


def disable_tenant_rls(table: str) -> None:
    """Reverse `enable_tenant_rls` for a downgrade."""
    for policy in ("allow_writes_delete", "allow_writes_update", "allow_writes_insert", "tenant_isolation"):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
