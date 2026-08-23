# DHĀT STORE — MVP GAP CLOSURE

This document records the concrete work added after the production-core audit. It intentionally separates code completion from environment-dependent verification.

## Added

- Central permission matrix for OWNER, ADMIN, FINANCE, SUPPORT, MODERATOR, CUSTOMER.
- Fine-grained permission dependency for sensitive management endpoints.
- Category update/archive endpoints.
- Product creation endpoint.
- Service update/archive endpoints.
- User listing, suspension/blocking, and role management with OWNER protection.
- Admin order listing and audit listing.
- Admin analytics aggregates.
- Support ticket creation, listing, detail, messages, assignment/status/priority management.
- Payment-method configuration boundary without exposing account secrets.
- Verified payment webhook boundary with HMAC validation and external-event idempotency.
- Explicit Alembic hardening migration with proof URL storage, indexes, and RBAC seed data.
- Composed API entrypoint that mounts management and payment routers.
- Docker now starts the composed API entrypoint.
- Static completion-contract tests.

## Still environment-dependent

- PostgreSQL upgrade/downgrade/upgrade runtime execution.
- Telegram live authentication with a real bot token.
- Real provider submission/reconciliation with provider credentials.
- Real payment-provider webhook verification with a configured secret.
- Browser E2E execution.
- Docker runtime execution.
- GitHub Actions execution result.

These are not marked COMPLETE merely because the source code exists.
