# Store Platform — Project Specification

## 1. Vision

Build a production-oriented e-commerce platform from an empty repository with two primary interfaces:

- **Customer Web Store** — product browsing, search, cart, checkout/order creation, account/order tracking, responsive mobile-first UI.
- **Telegram Admin Panel** — secure administrative control center for products, categories, inventory, orders, customers, discounts, notifications, reports, settings, and administrator roles.

Both interfaces must use the **same backend services and database**. Telegram is an administration interface, not a second backend.

## 2. Core Architecture

Use a modular, maintainable architecture with clear separation of concerns:

- `apps/web` — customer storefront.
- `apps/api` — backend/API and business logic.
- `apps/bot` — Telegram administration interface.
- `packages/shared` — shared schemas/types/utilities where appropriate.
- `infra` — Docker/deployment/configuration assets.
- `tests` — automated tests.
- `docs` — architecture, setup, API and operational documentation.

The exact framework choices may be selected by the implementation agent based on current ecosystem stability, but they must be documented and consistently applied. Prefer a typed, modern stack, PostgreSQL for production data, migrations, environment-based secrets, structured logging, validation, and automated testing.

## 3. Customer Store

Required capabilities:

- Home page and promotional sections.
- Product catalog.
- Categories and filtering.
- Product search.
- Product details with images, price, stock status, description and variants when applicable.
- Cart with quantity updates and stock-aware validation.
- Checkout/order creation.
- Customer profile and order history where authentication is enabled.
- Order status tracking.
- Responsive mobile-first design.
- Accessible UI and clear loading/error/empty states.
- SEO-friendly public pages where applicable.

## 4. Telegram Admin

Provide an authenticated Telegram bot for authorized administrators only.

Main sections:

- Dashboard/statistics.
- Products.
- Categories.
- Inventory.
- Orders.
- Customers.
- Discounts/coupons.
- Notifications/broadcasts.
- Reports.
- Store settings.
- Administrator accounts/roles.
- System health/status.

Administrative actions should use confirmations for destructive operations. Do not expose secrets or sensitive credentials in Telegram messages or logs.

## 5. Orders

Order lifecycle should be explicit and auditable, for example:

`pending -> confirmed -> processing -> shipped -> completed`

with a safe cancellation/rejection path where appropriate.

Every status change should be validated server-side and recorded in an audit trail.

## 6. Inventory

Inventory must be managed centrally. Order creation and status transitions must not allow negative stock. Stock-changing operations must be transactional to avoid race conditions.

## 7. Security

Minimum requirements:

- Secrets only through environment/configuration management; never hard-code credentials.
- Strong authentication and authorization for administration.
- Role-based access control for Telegram administrators.
- Server-side validation for all inputs.
- Protection against common web/API vulnerabilities.
- Rate limiting where appropriate.
- Secure password/token handling if customer authentication is implemented.
- Audit logging for sensitive administrative actions.
- Safe error messages without leaking internals.
- Production CORS/CSRF/session configuration appropriate to the selected architecture.

## 8. Database

Use normalized relational models with migrations. At minimum plan for:

- users/customers
- admin users/roles
- products
- product images
- categories
- inventory
- orders
- order items
- coupons/discounts
- order status history
- audit logs
- store settings
- notification records

Use foreign keys, indexes and constraints where appropriate.

## 9. API

The API must be the single source of business truth. Web and Telegram must not duplicate business rules.

Provide documented endpoints/services for:

- catalog/products/categories
- authentication/authorization
- cart/order creation
- order management
- inventory
- customers
- discounts
- admin operations
- health/readiness

Use consistent validation, error responses and logging.

## 10. Configuration and Deployment

Provide:

- `.env.example` with variable names only and safe placeholders.
- Docker/Docker Compose configuration suitable for local development where practical.
- Database migration commands.
- Seed/demo data strategy.
- Production deployment documentation.
- Health checks.
- Backup/restore guidance.

Never commit real API keys, Telegram bot tokens, database passwords, private keys or other secrets.

## 11. Testing

The implementation is not complete until automated checks cover critical paths.

Required categories:

- Unit tests for business logic.
- API/integration tests.
- Database/migration tests where practical.
- Order and inventory concurrency-sensitive behavior.
- Authorization tests.
- Telegram admin authorization and critical actions.
- Frontend build/type/lint checks.
- End-to-end tests for the main customer purchase flow where practical.

## 12. Engineering Rules

- Start from the empty repository and build deliberately; do not invent existing code.
- Do not create duplicate business logic between Web and Telegram.
- Do not hard-code secrets.
- Do not mark unfinished features as complete.
- Prefer simple, maintainable solutions over unnecessary microservices.
- Keep modules cohesive and interfaces explicit.
- Add documentation for non-obvious architectural decisions.
- Every major feature must include validation and tests.
- Before declaring completion, run the complete available test/build/lint/type-check suite and fix discovered issues.

## 13. Definition of Done

The project is considered ready for the next stage only when:

1. The application builds successfully.
2. The database can be created from migrations on a clean environment.
3. The API starts and passes health checks.
4. The Web Store starts and communicates with the API.
5. Telegram Admin starts and authenticates authorized administrators.
6. Product/category/inventory/order flows work end-to-end.
7. Critical authorization and validation paths are tested.
8. No real secrets are committed.
9. Documentation explains setup, environment variables, migrations, running tests, and deployment.
10. The implementation agent provides a final audit report listing completed features, tests run, known limitations, and any remaining work.
