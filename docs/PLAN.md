# ReScope — build plan

ReScope is a multi-tenant company-intelligence CRM. Each tenant lives on its own subdomain
(`acme.rescope.app`). A member pastes a company's website; a background pipeline profiles the
company — basics, overview, products, services, competencies, each with evidence — and embeds the
result into pgvector so the tenant can search its accounts semantically and find similar companies.

This document is the source of truth for *what* we're building and *why*. `ARCHITECTURE.md`
(written in Phase 5) will describe what was actually built.

## 1. Decisions

These were made up front and the rest of the plan depends on them.

- **Shared database, shared schema.** One Postgres, one schema, `tenant_id` on every tenant-scoped
  row. Isolation is enforced three times: tenant resolved from the `Host` header (never from the
  request body or path), composite foreign keys that make cross-tenant references impossible at the
  database, and row-level security as the backstop. See §3.
- **Per-tenant copies of scraped data.** When two tenants add `acme.com`, each gets its own profile
  rows from its own scrape job. The only tables without a `tenant_id` are `users`, `tenants`, and
  `plans`. A global scrape cache is a possible later optimization, not part of the design.
- **Platform-paid LLM, quotas per plan.** ReScope holds one Anthropic key (in the environment, never
  the database). Tenants get `N` profiles and `M` deep runs per calendar month by plan, enforced
  before a job is enqueued and metered per job into an append-only usage ledger.
- **Light CRM.** Companies (accounts), contacts, notes, tags, saved searches, CSV import. No deals
  or pipeline. The profiling pipeline is the product; the CRM layer makes it usable day to day.
- **New codebase, not a fork of ReCore.** Same stack and the same two conventions that kept ReCore
  maintainable — *routers contain no logic, services never import FastAPI* — but written fresh.
- **Tiered scraping.** A cheap text pass handles most sites; a visual browser agent
  (`browser-use`) runs only when the text pass is not enough or the user asks for a deep run.
- **Self-hosted embeddings.** `Qwen/Qwen3-Embedding-0.6B` served by Hugging Face
  text-embeddings-inference, 1024 dimensions, fixed in the schema. Switching models later is a
  re-embed job, not a migration.

## 2. Stack

| Layer | Choice |
|---|---|
| API | FastAPI, SQLAlchemy 2 (async, asyncpg), Alembic, Pydantic v2, structlog |
| Data | PostgreSQL 16 + pgvector, Redis 7 |
| Jobs | arq. Two worker processes off two images: `worker` (embeddings, scheduling, CSV import) and `scraper` (Playwright + Chromium + browser-use — heavy, isolated so a crash never takes the API worker with it) |
| Embeddings | text-embeddings-inference container serving `Qwen/Qwen3-Embedding-0.6B` |
| LLM | Anthropic SDK. `claude-opus-5` drives the visual agent; `claude-sonnet-5` does bulk structured extraction; `claude-haiku-4-5` does classification and dedupe |
| Web | Next.js 16 (App Router), React 19, Tailwind 4 |
| Infra | docker compose for everything; Caddy with a wildcard certificate in production |
| Tooling | uv, ruff, mypy, pytest (against a real `_test` database); pnpm, eslint, tsc, Playwright e2e; GitHub Actions |

## 3. Tenancy

**Resolution.** The web app's middleware reads the `Host` header, extracts the tenant slug, and
rewrites `acme.rescope.app/companies` to the internal route `/t/acme/companies`. Every API call the
web app makes carries `X-Tenant-Slug`; the API resolves it to a tenant, loads the caller's
membership, and returns **404** (not 403, which would confirm the tenant exists) if there is none.
The root domain (`rescope.app`) hosts signup, login, and the tenant switcher.

**Sessions.** Opaque session id in an `httpOnly; Secure; SameSite=Lax` cookie with
`Domain=.rescope.app`, so one login works across every tenant the user belongs to. Resolved
against Redis with a sliding TTL; revocation is a `DEL`. No JWTs.

**Schema rules.** Every tenant-scoped table has `tenant_id uuid NOT NULL`. Unique constraints are
always scoped by tenant: `UNIQUE (tenant_id, domain)`. Parent tables additionally carry
`UNIQUE (tenant_id, id)` so children can declare composite foreign keys:

```sql
FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id) ON DELETE CASCADE
```

A contact can therefore never point at another tenant's company, even if application code passes
the wrong id.

**Row-level security.** The API and workers connect as `rescope_app`, a role with CRUD and no DDL,
subject to RLS. Each request's transaction runs `SET LOCAL app.tenant_id = '<uuid>'`, and every
tenant table has one policy: `tenant_id = current_setting('app.tenant_id', true)::uuid`. Workers
re-set it after every commit because the setting is transaction-local. Migrations run as the owner
role. Unlike ReCore there are no excluded tables — everything except `users`, `tenants`, and
`plans` has a tenant.

**Roles.** `viewer < member < admin < owner`, ordered, so a permission check is one comparison.
A separate `users.is_superadmin` flag gates the platform-operator area (tenants, spend, quotas,
the scraping killswitch) and has nothing to do with tenant roles.

**Local development.** `rescope.localhost` is the root and `acme.rescope.localhost:3000` is a
tenant — browsers resolve every `*.localhost` name to loopback and accept cookies with
`Domain=.rescope.localhost`, so no hosts-file edits. The API is `localhost:8000`.

## 4. Data model

```
plans(id, name, profiles_per_month, deep_runs_per_month, max_companies, max_members)
tenants(id, slug UNIQUE, name, plan_id, status, settings jsonb, created_at)
users(id, email UNIQUE, password_hash, is_superadmin, created_at)
memberships(tenant_id, user_id, role, created_at)              PK (tenant_id, user_id)
invitations(id, tenant_id, email, role, token_hash, expires_at, accepted_at)

companies(id, tenant_id, domain, name, website_url, industry, hq_country, hq_city,
          employee_range, founded_year, socials jsonb, logo_url, overview text,
          profile_status, last_profiled_at, created_by, created_at, updated_at)
          UNIQUE (tenant_id, domain), UNIQUE (tenant_id, id)
offerings(id, tenant_id, company_id, kind product|service, name, description,
          category, url, evidence jsonb, created_at)
competencies(id, tenant_id, company_id,
          kind capability|technology|certification|industry_served|partnership,
          name, description, evidence jsonb, created_at)
embeddings(id, tenant_id, company_id, source_kind, source_id, content text,
          embedding vector(1024), model, created_at)
          UNIQUE (tenant_id, source_kind, source_id)

scrape_jobs(id, tenant_id, company_id, mode fast|deep, status, tier_reached,
          pages_fetched, tokens_in, tokens_out, cost_usd, error,
          queued_at, started_at, finished_at)
scrape_pages(id, tenant_id, job_id, url, status_code, content_hash,
          markdown text, screenshot_key, fetched_at)              -- raw artifacts, TTL'd
profile_changes(id, tenant_id, company_id, job_id, diff jsonb, created_at)

contacts(id, tenant_id, company_id, first_name, last_name, email, title,
          phone, linkedin_url, source, created_at, updated_at)
notes(id, tenant_id, company_id, author_id, body, created_at)
tags(id, tenant_id, name, color)                                UNIQUE (tenant_id, name)
company_tags(tenant_id, company_id, tag_id)
saved_searches(id, tenant_id, owner_id, name, query jsonb)
imports(id, tenant_id, kind, status, row_count, error_count, created_by, created_at)

usage_events(id, tenant_id, job_id, kind, model, tokens_in, tokens_out, cost_usd, created_at)
audit_logs(id, tenant_id, actor_id, action, target_type, target_id, metadata jsonb, created_at)
```

`evidence` is a list of `{url, quote}`. Every product, service and competency links back to the
page and sentence it was extracted from; that provenance is what makes an AI-written profile
trustworthy.

Quotas are computed on read from `usage_events` for the current calendar month. A rollup table is
the answer if that ever gets slow, and adding one changes nothing above the service.

## 5. The scraping pipeline

Each job moves through tiers and stops as soon as the profile is good enough.

**Tier 0 — discovery (no LLM).** Normalize the domain, run the SSRF guard, read `robots.txt` and
`sitemap.xml`, fetch the homepage with httpx. Rank candidate URLs by path and anchor text
(`/about`, `/products`, `/services`, `/solutions`, `/industries`, `/capabilities`,
`/case-studies`, `/contact`). Estimate whether the site is client-rendered from its
text-to-markup ratio.

**Tier 1 — text extraction.** Render up to ~25 pages with headless Playwright (no vision),
convert each to markdown, and make one structured-output call (`claude-sonnet-5`, low/medium
effort, `output_config.format` with the profile schema) that returns the profile with a confidence
per field and a source URL per item. This is expected to fully handle the majority of sites.

**Tier 2 — visual agent.** Runs when Tier 1 confidence is low, the site is an SPA, offerings sit
behind tabs / accordions / infinite scroll / mega-menus, or the user chose *deep*. `browser-use`
drives Chromium with `claude-opus-5`, given the same output schema, bounded by max steps, max
minutes, max pages and a per-job token ceiling. Screenshots are stored as evidence.

**Merge, normalize, embed.** Deduplicate offerings by name similarity, map competencies onto a
small canonical taxonomy while keeping the free-text label, then embed one row per offering and
competency plus one company-summary row. The summary embedding powers similar-company search.

**Re-profile.** On a plan-dependent schedule (e.g. every 30 days) the job runs again; the diff
against the previous profile lands in `profile_changes` and surfaces as a per-account changes feed.

**Cost controls.** Quota check before enqueue; per-job token and time ceilings inside the worker;
tokens and USD written to `usage_events` for every model call; a platform-level killswitch flag
that pauses all scraping.

## 6. Search

- **Semantic:** embed the query with the same model, `WHERE tenant_id = :t ORDER BY embedding <=> :q`,
  group by company, rank by best chunk.
- **Similar companies:** cosine distance on the company-summary embedding, within the tenant.
- **Hybrid:** `tsvector` full-text combined with vector results by reciprocal rank fusion, for
  exact product names semantic search misses.
- **Filtered ANN:** an HNSW index post-filters, so a small tenant in a large table loses recall.
  pgvector ≥ 0.8 `hnsw.iterative_scan = relaxed_order` is the fix; set it per session.

## 7. Phases

| Phase | Deliverable | Est. |
|---|---|---|
| 0 | Repo, compose (postgres, redis, api, worker, scraper, tei, web), auth + sessions, tenants + subdomain routing, memberships and roles, invitations, RLS + composite FKs, audit, CI | 2 wk |
| 1 | Companies CRUD, Tier 0 + Tier 1 scrape, structured extraction, profile page with evidence, job status UI | 1–2 wk |
| 2 | TEI service, embeddings, semantic search, similar companies, hybrid search | 1 wk |
| 3 | browser-use deep mode, screenshot evidence, usage ledger, plans + quotas, killswitch, superadmin panel | 1–2 wk |
| 4 | Contacts, notes, tags, saved searches, CSV import, scheduled re-profile + changes feed | 1–2 wk |
| 5 | ARCHITECTURE.md, production deploy with wildcard domain, demo tenant, README with recordings | 1 wk |

Phase 1 is the first demoable cut; everything after it is additive.

## 8. Conventions

- Routers contain no logic; services take plain arguments and never import FastAPI.
- One Alembic revision per schema change, with a docstring explaining anything non-obvious.
- Secrets are never fields on a response schema.
- Every privileged action writes an audit row.
- Tests run against a real Postgres and Redis, on a `_test`-suffixed database and a separate Redis
  db index, so the suite can never touch a dev stack's data.
- Work happens on a branch per phase, committed and pushed one coherent feature at a time, and
  lands through a pull request the repository owner reviews and merges.
