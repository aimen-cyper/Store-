# VERIFICATION_V2

| Feature | Status | Evidence | Tests | Remaining Issue |
|---|---|---|---|---|
| Telegram authentication | COMPLETE | `apps/api/dhat_store/main.py` HMAC + freshness + sessions | `tests/test_static_contract.py` | Runtime Telegram verification requires bot token |
| Session lifecycle | COMPLETE | hashed opaque tokens, expiry, revocation | static tests | PostgreSQL runtime unverified locally |
| Catalog | COMPLETE | DB-backed category/service APIs with pagination/search | static + business tests | Admin CRUD breadth can be expanded |
| Pricing engine | COMPLETE | Decimal deterministic rules in `core.py` | `test_business_rules.py` | Provider-specific pricing rule UI remains |
| Wallet/ledger | COMPLETE | NUMERIC balances, row locks, immutable idempotency keys | business/static tests | PostgreSQL concurrency test required |
| Manual deposits | COMPLETE | pending/approve/reject + idempotent ledger credit | static tests | Proof upload storage not implemented |
| Orders/idempotency | COMPLETE | locked service/wallet + unique idempotency key | business/static tests | Full provider dispatch is separate step |
| Provider adapters | COMPLETE | HTTP adapter with timeout/error handling | static contract | Real provider credentials unavailable |
| Provider routing | PARTIAL | priority mappings + health gate | static | Health automation/circuit breaker remains |
| UNKNOWN provider outcome | COMPLETE | timeout records UNKNOWN and blocks blind retry | static | Real provider integration test blocked without credentials |
| Reconciliation | COMPLETE | explicit provider status reconciliation endpoint | static | Requires configured provider |
| Refunds | COMPLETE | wallet credit with unique `refund:{order}` ledger key | static | External provider refund integration remains |
| Coupons | PARTIAL | create + quote + discount calculation | business tests | usage-limit enforcement should be extended |
| Notifications/outbox | COMPLETE | persisted retry-safe notification worker | static | Telegram delivery requires bot token |
| Support | COMPLETE | ticket/message persistence and authorization | static | Admin assignment/status UI remains |
| Audit | COMPLETE | critical actions persisted | static | Request-ID enrichment remains |
| Analytics | COMPLETE | PostgreSQL/SQLAlchemy aggregates | static | time-range dashboards remain |
| Fine-grained RBAC | PARTIAL | roles/permissions schema + role gates | static | permission-code enforcement needs expansion |
| Customer Mini App | COMPLETE | Telegram-aware React/Vite app using real APIs | frontend build | Full E2E browser validation remains |
| Admin Mini App | PARTIAL | authenticated dashboard + audit/deposit actions | frontend build | Full management screens remain |
| Telegram bot | COMPLETE | `/start` + store/balance/orders/support navigation | static | production webhook/polling deployment requires token |
| Alembic migrations | COMPLETE | explicit 0001 + 0002 operations | CI migration commands | Runtime CI result depends on GitHub Actions execution |
| Docker | COMPLETE | PostgreSQL/API/worker/bot compose | CI/static | frontend container deployment can be added |
| CI | COMPLETE | lint/tests/compile/migrations/frontend build configured | GitHub Actions | latest workflow run must pass |
| PostgreSQL runtime | UNVERIFIED | configured in compose | not run in this environment | requires Docker/runtime execution |
| Production credentials | BLOCKED | environment/config boundaries exist | n/a | Telegram/provider/payment secrets required |

## Allowed statuses
COMPLETE, PARTIAL, MISSING, BROKEN, BLOCKED, UNVERIFIED

No feature is marked COMPLETE merely because an interface exists; the matrix reflects implemented integration boundaries and explicitly records runtime/configuration dependencies.
