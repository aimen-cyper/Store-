# AIMEN — DHĀT STORE Unified Edition

`aimen.py` is the single-file, clearly sectioned control-plane requested for the DHĀT STORE project.

## Sections

1. Configuration
2. Database and enums
3. Users and sessions
4. RBAC
5. Catalog and services
6. Pricing engine
7. Provider adapter / registry / router / reconciliation boundary
8. Wallet and immutable ledger
9. Deposits and payments boundary
10. Coupons
11. Orders and idempotency
12. Notifications
13. Support
14. Audit
15. Analytics
16. Customer API/panel
17. Admin API/panel
18. Provider API/panel
19. Telegram bot command contract
20. System capability registry

## Panels

- `/store` — customer store shell
- `/admin` — administrator control shell
- `/provider` — provider control shell
- `/api/v1/*` — unified application API

## Provider model

A provider is configured in the Admin API and mapped to internal services. Providers with a protocol that differs from the generic adapter require an adapter implementation; the application deliberately does not invent successful provider responses.

## Security

- Telegram initData HMAC verification
- expiring opaque sessions stored as SHA-256 hashes
- OWNER bootstrap through `OWNER_TELEGRAM_ID`
- role/permission boundary
- financial idempotency
- wallet non-negative constraint
- order state transitions
- audit records
- provider credentials are never returned by provider listing endpoints

## Database

Production schema remains migration-first in the existing Alembic project. The `AIMEN_DEV_CREATE_TABLES=1` switch exists only for explicit local standalone development; it is not a production migration mechanism.

## Important

This unified file is added alongside the existing modular production branch so existing working implementation is not deleted or reset. It is the consolidated reference/control-plane requested by the owner and is committed on `feat/dhat-store-production`.
