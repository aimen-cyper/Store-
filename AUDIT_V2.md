# AUDIT V2

Repository was rebuilt from the actual `main` baseline, which contained only the specification. This branch implements a real MVP foundation without altering `main`.

| Area | Status | Evidence |
|---|---|---|
| API foundation | COMPLETE | FastAPI app and typed config |
| Explicit migration | COMPLETE | `alembic/versions/0001_initial.py` uses `op.create_table` |
| Telegram auth | COMPLETE | initData HMAC, freshness, session lifecycle |
| Basic RBAC | PARTIAL | OWNER/ADMIN guard; fine-grained permissions pending |
| Catalog | PARTIAL | category/service reads and admin creation |
| Wallet/ledger | PARTIAL | Decimal/Numeric, idempotency, locked purchase path |
| Deposits | PARTIAL | submit + idempotent approval |
| Orders | PARTIAL | wallet-backed creation and idempotency; provider lifecycle pending |
| Provider system | MISSING | adapter/router/reconciliation pending |
| Payments | MISSING | pending |
| Coupons | MISSING | pending |
| Notifications | MISSING | pending |
| Support | MISSING | pending |
| Analytics | MISSING | pending |
| Customer web | PARTIAL | live catalog/wallet UI |
| Admin web | PARTIAL | live API dashboard shell |
| Telegram bot | PARTIAL | `/start` opens customer web app |
| CI | PARTIAL | workflow added; runtime verification pending |
| Docker | PARTIAL | PostgreSQL/API compose stack |
