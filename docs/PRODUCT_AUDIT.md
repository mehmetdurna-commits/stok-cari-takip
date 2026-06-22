# StokCari Product Audit

Last updated: 2026-06-02

## Current Position

StokCari has a broad operational foundation: inventory, warehouse movements,
POS sales, returns, customer accounts, quotes, cash accounts, reconciliation,
reports, personnel workflows, tenant administration, support, audit logs and
backups. The next objective is consistency and reliability before adding more
surface area.

## Immediate Release Blockers

- Complete PostgreSQL migrations and verify them against a staging database.
- Run a real Linux staging deployment with Nginx, HTTPS and systemd.
- Exercise release upload, health-check failure and rollback scenarios.
- Remove generated databases, uploads and old template backups from tracked
  release content.
- Normalize mojibake text and move all source files to UTF-8.

## Product Simplification

- Keep the core navigation focused on inventory, sales, customers, finance,
  quotes and reports.
- Keep personnel management as an optional module, not a default core flow.
- Remove obsolete duplicate templates after route usage is verified.
- Avoid adding country-specific accounting automation until the target market
  and compliance scope are explicitly selected.

## Recommended Feature Order

1. Purchase orders and supplier receiving.
2. Inventory counting with adjustment approval.
3. Structured product import and export.
4. Multi-currency foundations and exchange-rate audit trail.
5. Public API keys, webhooks and integration logs.
6. Centralized notification preferences and delivery history.

## Engineering Program

1. Split `app.py` into application factory, models, services and route modules.
2. Establish a reusable UI component layer for forms, tables, empty states and
   confirmation dialogs.
3. Add PostgreSQL-backed integration tests and browser smoke tests.
4. Add error monitoring, structured logs and operational dashboards.
5. Add accessibility and mobile regression checks for critical workflows.
