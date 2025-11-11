# Roadmap

## Phase 1 – Immediate Improvements (1-2 weeks)
- **Stabilize audit tooling**
  - Polish `/audit_logs.html` UX (infinite scroll, detail modal).
  - Add automated cleanup policy (retention threshold) with configurable env vars.
  - Finish error-handling tests for `POST /api/audit-logs/clear`.
- **Developer Workflow**
  - Set up lint/format hooks (pre-commit, Ruff/Black).
  - Containerize dev environment with compose override for hot reload.

## Phase 2 – Data Layer Modernization (2-4 weeks)
- **Database Migration Feasibility**
  - Abstract SQLite access behind repository interfaces.
  - Prototype Supabase/PostgreSQL back end: define schemas/migrations, compare latency.
  - Plan data migration scripts & backup strategy.
- **Observability**
  - Centralize logging/metrics (Structured logs, Prometheus/Grafana).
  - Add tracing to LINE webhook & API routes.

## Phase 3 – Feature Expansion (4-8 weeks)
- **Event Management Enhancements**
  - Role-based permissions (admin vs. viewer, per-route access).
  - Bulk editing/import validation UI improvements.
  - Notification flows (email/Slack) when new events arrive.
- **User Experience**
  - Responsive redesign of `events_admin.html` & public pages.
  - Localization cleanup (fix garbled strings, support en/zh toggle).

## Phase 4 – Long-Term Initiatives (8+ weeks)
- **Scalability & Hosting**
  - Deploy to managed platform (Render/Fly.io/Supabase Edge) with CI/CD pipeline.
  - Enable multi-instance LINE webhook handling with shared state/cache.
- **Data Products**
  - Build analytics dashboard (historical charts, KPIs).
  - Expose public API with API keys & rate limiting.
- **Security & Compliance**
  - Security review, penetration testing.
  - Implement audit log immutability / export to external archive.

> Timeline estimates assume one developer; adjust for team size & priorities.
