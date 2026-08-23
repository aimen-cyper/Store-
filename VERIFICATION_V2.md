# VERIFICATION V2

| Feature | Status | Evidence | Tests | Remaining Issue |
|---|---|---|---|---|
| Repository safety | COMPLETE | isolated feature branch; no reset/force | git review | merge requires review |
| Explicit migration | COMPLETE | Alembic revision uses explicit operations | static contract | PostgreSQL runtime BLOCKED until dependencies/environment available |
| Auth | PARTIAL | Telegram HMAC + opaque sessions | static only | live Telegram credentials required |
| RBAC | PARTIAL | OWNER/ADMIN backend guard | static only | fine-grained permission matrix |
| Catalog | PARTIAL | DB-backed API | static only | update/archive/search/pagination |
| Wallet | PARTIAL | NUMERIC, constraints, idempotent ledger | static only | PostgreSQL concurrency test |
| Deposits | PARTIAL | approval is idempotent by deposit ledger key | static only | proof/payment methods/notification |
| Orders | PARTIAL | idempotency + wallet deduction + stock check | static only | provider state machine |
| Provider routing | MISSING | none | - | implement adapter/router/reconciliation |
| Payments | MISSING | none | - | implement provider boundary/webhooks |
| Coupons | MISSING | none | - | implement |
| Notifications | MISSING | none | - | implement outbox |
| Support | MISSING | none | - | implement |
| Analytics | MISSING | none | - | implement PostgreSQL queries |
| Customer UI | PARTIAL | live catalog/wallet | build pending | full checkout/profile/orders/support |
| Admin UI | PARTIAL | live API dashboard | build pending | full admin modules |
| Telegram bot | PARTIAL | `/start` + Mini App button | dependency/runtime pending | admin flows |
| CI | PARTIAL | workflow committed | unverified in environment | GitHub Actions run |
| Docker | PARTIAL | API + PostgreSQL compose | unverified | frontend/bot services |
