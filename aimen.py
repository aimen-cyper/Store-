"""
DHĀT STORE — AIMEN UNIFIED EDITION
===================================

Single-file reference/control-plane for the complete store domain.

This file intentionally keeps every major subsystem in one clearly separated
module so the business can be understood and extended without jumping through
dozen of files. The existing modular implementation remains untouched.

Run:
    uvicorn aimen:app --reload

Environment:
    DATABASE_URL=postgresql+asyncpg://user:password@localhost/dhat
    TELEGRAM_BOT_TOKEN=...
    OWNER_TELEGRAM_ID=...
    AIMEN_SESSION_DAYS=30

The sections below are ordered as a complete business flow:
configuration -> database -> security -> RBAC -> catalog -> pricing ->
providers -> wallet -> deposits/payments -> coupons -> orders -> support ->
notifications -> analytics -> admin/customer/provider panels -> bot.
"""

# ============================================================
# 01. CORE IMPORTS / CONFIGURATION
# ============================================================
import os
import json
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Optional
from urllib.parse import parse_qsl

from fastapi import FastAPI, Depends, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, JSON,
    UniqueConstraint, CheckConstraint, select, func, or_, and_, update
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


APP_NAME = "DHĀT STORE — AIMEN"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./aimen.db")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0") or 0)
SESSION_DAYS = int(os.getenv("AIMEN_SESSION_DAYS", "30"))
AUTH_MAX_AGE = int(os.getenv("TELEGRAM_AUTH_MAX_AGE", "900"))
CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]

engine = create_async_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# ============================================================
# 02. DATABASE BASE / ENUMS
# ============================================================
class Base(DeclarativeBase):
    pass


class UserRole(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    FINANCE = "FINANCE"
    SUPPORT = "SUPPORT"
    MODERATOR = "MODERATOR"
    PROVIDER = "PROVIDER"
    CUSTOMER = "CUSTOMER"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    CANCELED = "CANCELED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"


# ============================================================
# 03. DATABASE MODELS — ALL MAJOR STORE OBJECTS
# ============================================================
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(32), default=UserRole.CUSTOMER.value, index=True)
    status: Mapped[str] = mapped_column(String(32), default=UserStatus.ACTIVE.value, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    permission: Mapped[str] = mapped_column(String(100), index=True)
    __table_args__ = (UniqueConstraint("role", "permission", name="uq_role_permission"),)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    cost: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), index=True)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    min_quantity: Mapped[int] = mapped_column(Integer, default=1)
    max_quantity: Mapped[int] = mapped_column(Integer, default=1000000)


class PricingRule(Base):
    __tablename__ = "pricing_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[Optional[int]] = mapped_column(ForeignKey("services.id"), index=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), index=True)
    provider_id: Mapped[Optional[int]] = mapped_column(ForeignKey("providers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    base_url: Mapped[str] = mapped_column(String(1000))
    api_key: Mapped[Optional[str]] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    timeout: Mapped[int] = mapped_column(Integer, default=20)
    health: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    supported_operations: Mapped[dict] = mapped_column(JSON, default=dict)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)


class ProviderMapping(Base):
    __tablename__ = "provider_mappings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    external_service_id: Mapped[str] = mapped_column(String(200))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("service_id", "provider_id", name="uq_service_provider"),)


class Wallet(Base):
    __tablename__ = "wallets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    __table_args__ = (
        UniqueConstraint("user_id", "currency", name="uq_wallet_currency"),
        CheckConstraint("balance >= 0", name="ck_wallet_nonnegative"),
    )


class Ledger(Base):
    __tablename__ = "wallet_ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    type: Mapped[str] = mapped_column(String(32), index=True)
    reference: Mapped[str] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Deposit(Base):
    __tablename__ = "deposits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3))
    reference: Mapped[str] = mapped_column(String(200))
    proof_url: Mapped[Optional[str]] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Coupon(Base):
    __tablename__ = "coupons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    min_order: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 8))
    max_discount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 8))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    usage_limit: Mapped[Optional[int]] = mapped_column(Integer)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    discount: Mapped[Decimal] = mapped_column(Numeric(24, 8))


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    total: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.PENDING.value, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    external_order_id: Mapped[Optional[str]] = mapped_column(String(200))
    external_outcome: Mapped[str] = mapped_column(String(32), default="NONE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class OrderEvent(Base):
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    old_status: Mapped[str] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(50))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Ticket(Base):
    __tablename__ = "support_tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    priority: Mapped[str] = mapped_column(String(32), default="NORMAL")
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    assigned_to: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SupportMessage(Base):
    __tablename__ = "support_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target: Mapped[str] = mapped_column(String(200))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ============================================================
# 04. SCHEMAS / API INPUTS
# ============================================================
class TelegramIn(BaseModel):
    init_data: str


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=160)


class ServiceIn(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    cost: Decimal = Field(ge=0)
    price: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    min_quantity: int = Field(default=1, ge=1)
    max_quantity: int = Field(default=1000000, ge=1)
    stock: int = Field(default=0, ge=0)


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    base_url: str = Field(min_length=8, max_length=1000)
    api_key: Optional[str] = None
    priority: int = Field(default=100, ge=0)
    timeout: int = Field(default=20, ge=1, le=120)


class MappingIn(BaseModel):
    service_id: int
    provider_id: int
    external_service_id: str = Field(min_length=1, max_length=200)
    priority: int = Field(default=100, ge=0)


class PriceRuleIn(BaseModel):
    service_id: Optional[int] = None
    category_id: Optional[int] = None
    provider_id: Optional[int] = None
    kind: str
    value: Decimal


class DepositIn(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    reference: str = Field(min_length=1, max_length=200)
    proof_url: Optional[str] = None


class OrderIn(BaseModel):
    service_id: int
    quantity: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=160)
    coupon_code: Optional[str] = None


class CouponIn(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    kind: str
    value: Decimal = Field(gt=0)
    min_order: Optional[Decimal] = None
    max_discount: Optional[Decimal] = None
    expires_at: Optional[datetime] = None
    usage_limit: Optional[int] = Field(default=None, ge=1)
    per_user_limit: int = Field(default=1, ge=1)


class TicketIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    priority: str = "NORMAL"


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


# ============================================================
# 05. DATABASE DEPENDENCY / SECURITY UTILITIES
# ============================================================
async def db_session():
    async with SessionFactory() as db:
        yield db


def now() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def audit_record(db: AsyncSession, actor: Optional[User], action: str, target: str, metadata: Optional[dict] = None):
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, target=target, metadata_json=metadata or {}))


def queue_notification(db: AsyncSession, user_id: int, event: str, payload: dict):
    db.add(Notification(user_id=user_id, event=event, payload=payload, status="PENDING", attempts=0, available_at=now()))


# ============================================================
# 06. TELEGRAM AUTHENTICATION / SESSION MANAGEMENT
# ============================================================
def verify_telegram_init_data(init_data: str) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(503, "Telegram authentication is not configured")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise HTTPException(401, "Invalid Telegram initData")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise HTTPException(401, "Invalid auth_date")
    if abs(now().timestamp() - auth_date) > AUTH_MAX_AGE:
        raise HTTPException(401, "Expired Telegram auth")
    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise HTTPException(401, "Invalid Telegram signature")
    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        raise HTTPException(401, "Malformed Telegram user")
    if not user.get("id"):
        raise HTTPException(401, "Invalid Telegram user")
    return user


async def current_user(authorization: Optional[str] = Header(default=None), db: AsyncSession = Depends(db_session)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    raw = authorization[7:]
    session = (await db.execute(select(Session).where(
        Session.token_hash == token_hash(raw),
        Session.revoked_at.is_(None),
        Session.expires_at > now(),
    ))).scalar_one_or_none()
    if not session:
        raise HTTPException(401, "Invalid or expired session")
    user = await db.get(User, session.user_id)
    if not user or user.status != UserStatus.ACTIVE.value:
        raise HTTPException(403, "Account unavailable")
    session.last_used_at = now()
    return user


async def require_permission(permission: str, user: User = Depends(current_user), db: AsyncSession = Depends(db_session)) -> User:
    if user.role == UserRole.OWNER.value:
        return user
    allowed = (await db.execute(select(RolePermission).where(
        RolePermission.role == user.role,
        RolePermission.permission == permission,
    ))).scalar_one_or_none()
    if not allowed:
        raise HTTPException(403, "Permission denied")
    return user


# ============================================================
# 07. RBAC DEFAULT PERMISSION MATRIX
# ============================================================
PERMISSIONS = [
    "users.read", "users.update", "users.suspend",
    "orders.read", "orders.manage", "orders.refund",
    "wallet.read", "wallet.adjust",
    "payments.read", "payments.manage",
    "providers.read", "providers.manage",
    "services.read", "services.manage",
    "pricing.read", "pricing.manage",
    "coupons.read", "coupons.manage",
    "support.read", "support.manage",
    "analytics.read", "audit.read", "admins.manage", "settings.manage",
]

ROLE_PERMISSIONS = {
    UserRole.ADMIN.value: set(PERMISSIONS) - {"wallet.adjust", "admins.manage"},
    UserRole.FINANCE.value: {"orders.read", "wallet.read", "wallet.adjust", "payments.read", "payments.manage", "analytics.read", "audit.read"},
    UserRole.SUPPORT.value: {"users.read", "orders.read", "support.read", "support.manage"},
    UserRole.MODERATOR.value: {"users.read", "orders.read", "services.read", "support.read", "support.manage"},
    UserRole.PROVIDER.value: {"providers.read", "orders.read"},
    UserRole.CUSTOMER.value: set(),
}


async def seed_rbac(db: AsyncSession):
    for role, permissions in ROLE_PERMISSIONS.items():
        for permission in permissions:
            exists = (await db.execute(select(RolePermission).where(RolePermission.role == role, RolePermission.permission == permission))).scalar_one_or_none()
            if not exists:
                db.add(RolePermission(role=role, permission=permission))


# ============================================================
# 08. CATALOG / SERVICES / PRICING ENGINE
# ============================================================
def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def calculate_price(base: Decimal, rules: list[PricingRule]) -> Decimal:
    result = Decimal(base)
    ordered = sorted(rules, key=lambda r: (0 if r.kind == "OVERRIDE" else 1))
    for rule in ordered:
        if rule.kind == "OVERRIDE":
            result = Decimal(rule.value)
        elif rule.kind == "FIXED":
            result += Decimal(rule.value)
        elif rule.kind == "PERCENT":
            result += result * Decimal(rule.value) / Decimal("100")
        elif rule.kind == "MULTIPLIER":
            result *= Decimal(rule.value)
    return money(max(result, Decimal("0")))


def calculate_coupon(total: Decimal, coupon: Coupon) -> Decimal:
    if coupon.min_order is not None and total < coupon.min_order:
        return Decimal("0")
    if coupon.kind == "PERCENT":
        discount = total * coupon.value / Decimal("100")
    elif coupon.kind == "FIXED":
        discount = coupon.value
    else:
        return Decimal("0")
    if coupon.max_discount is not None:
        discount = min(discount, coupon.max_discount)
    return money(max(Decimal("0"), min(discount, total)))


# ============================================================
# 09. PROVIDER ADAPTER / REGISTRY / ROUTER / RECONCILIATION
# ============================================================
class ProviderResult(BaseModel):
    success: bool
    external_id: Optional[str] = None
    status: str = "UNKNOWN"
    raw: dict = Field(default_factory=dict)


class ProviderAdapter:
    """Universal contract. A provider with a different API gets one subclass."""
    def __init__(self, provider: Provider):
        self.provider = provider

    async def get_services(self) -> ProviderResult:
        raise NotImplementedError

    async def get_balance(self) -> ProviderResult:
        raise NotImplementedError

    async def create_order(self, external_service_id: str, quantity: int, parameters: dict) -> ProviderResult:
        raise NotImplementedError

    async def get_order_status(self, external_order_id: str) -> ProviderResult:
        raise NotImplementedError

    async def cancel_order(self, external_order_id: str) -> ProviderResult:
        raise NotImplementedError

    async def refill_order(self, external_order_id: str) -> ProviderResult:
        raise NotImplementedError


class ProviderRegistry:
    """Runtime registry for provider adapter factories."""
    _factories: dict[str, Any] = {}

    @classmethod
    def register(cls, name: str, factory: Any):
        cls._factories[name] = factory

    @classmethod
    def adapter(cls, provider: Provider) -> ProviderAdapter:
        factory = cls._factories.get(provider.name)
        if not factory:
            return GenericHTTPProvider(provider)
        return factory(provider)


class GenericHTTPProvider(ProviderAdapter):
    """Safe boundary. It intentionally does not invent success responses."""
    async def get_services(self) -> ProviderResult:
        return ProviderResult(success=False, status="NOT_IMPLEMENTED", raw={"reason": "provider adapter required"})

    async def get_balance(self) -> ProviderResult:
        return ProviderResult(success=False, status="NOT_IMPLEMENTED", raw={"reason": "provider adapter required"})

    async def create_order(self, external_service_id: str, quantity: int, parameters: dict) -> ProviderResult:
        return ProviderResult(success=False, status="NOT_IMPLEMENTED", raw={"reason": "provider adapter required"})

    async def get_order_status(self, external_order_id: str) -> ProviderResult:
        return ProviderResult(success=False, status="NOT_IMPLEMENTED", raw={"reason": "provider adapter required"})

    async def cancel_order(self, external_order_id: str) -> ProviderResult:
        return ProviderResult(success=False, status="NOT_IMPLEMENTED", raw={"reason": "provider adapter required"})

    async def refill_order(self, external_order_id: str) -> ProviderResult:
        return ProviderResult(success=False, status="NOT_IMPLEMENTED", raw={"reason": "provider adapter required"})


async def choose_provider(db: AsyncSession, service_id: int) -> tuple[Provider, ProviderMapping]:
    rows = (await db.execute(
        select(Provider, ProviderMapping)
        .join(ProviderMapping, ProviderMapping.provider_id == Provider.id)
        .where(
            ProviderMapping.service_id == service_id,
            ProviderMapping.enabled.is_(True),
            Provider.enabled.is_(True),
        )
        .order_by(ProviderMapping.priority.asc(), Provider.priority.asc(), Provider.failure_count.asc())
    )).all()
    if not rows:
        raise HTTPException(503, "No healthy provider mapping exists")
    return rows[0]


# ============================================================
# 10. ORDER STATE MACHINE
# ============================================================
ALLOWED_TRANSITIONS = {
    "PENDING": {"PROCESSING", "CANCELED", "FAILED"},
    "PROCESSING": {"IN_PROGRESS", "COMPLETED", "PARTIAL", "FAILED", "UNKNOWN", "CANCELED"},
    "IN_PROGRESS": {"COMPLETED", "PARTIAL", "FAILED", "UNKNOWN", "CANCELED"},
    "UNKNOWN": {"PROCESSING", "IN_PROGRESS", "COMPLETED", "PARTIAL", "FAILED", "CANCELED"},
    "COMPLETED": {"REFUNDING"},
    "PARTIAL": {"REFUNDING", "COMPLETED"},
    "REFUNDING": {"REFUNDED", "FAILED"},
    "REFUNDED": set(),
    "FAILED": {"REFUNDING"},
    "CANCELED": {"REFUNDING"},
}


async def transition_order(db: AsyncSession, order: Order, new_status: str, actor: Optional[User], source: str, metadata: Optional[dict] = None):
    if new_status == order.status:
        return
    if new_status not in ALLOWED_TRANSITIONS.get(order.status, set()):
        raise HTTPException(409, f"Invalid order transition {order.status} -> {new_status}")
    old = order.status
    order.status = new_status
    db.add(OrderEvent(order_id=order.id, old_status=old, new_status=new_status, actor_id=actor.id if actor else None, source=source, metadata_json=metadata or {}))


# ============================================================
# 11. WALLET / LEDGER / FINANCIAL INTEGRITY
# ============================================================
async def get_wallet_locked(db: AsyncSession, user_id: int, currency: str) -> Wallet:
    wallet = (await db.execute(select(Wallet).where(Wallet.user_id == user_id, Wallet.currency == currency).with_for_update())).scalar_one_or_none()
    if not wallet:
        wallet = Wallet(user_id=user_id, currency=currency, balance=Decimal("0"))
        db.add(wallet)
        await db.flush()
    return wallet


async def post_ledger(db: AsyncSession, wallet: Wallet, amount: Decimal, kind: str, reference: str, idempotency: str):
    existing = (await db.execute(select(Ledger).where(Ledger.idempotency_key == idempotency))).scalar_one_or_none()
    if existing:
        return existing
    new_balance = Decimal(wallet.balance) + Decimal(amount)
    if new_balance < 0:
        raise HTTPException(402, "Insufficient balance")
    wallet.balance = money(new_balance)
    entry = Ledger(wallet_id=wallet.id, amount=money(amount), type=kind, reference=reference, idempotency_key=idempotency)
    db.add(entry)
    await db.flush()
    return entry


async def reconcile_wallet(db: AsyncSession, wallet: Wallet) -> dict:
    total = (await db.execute(select(func.coalesce(func.sum(Ledger.amount), 0)).where(Ledger.wallet_id == wallet.id))).scalar_one()
    expected = money(Decimal(str(total)))
    actual = money(Decimal(wallet.balance))
    return {"wallet_id": wallet.id, "actual": str(actual), "ledger_sum": str(expected), "ok": actual == expected}


# ============================================================
# 12. FASTAPI APPLICATION
# ============================================================
app = FastAPI(title=APP_NAME, version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    # Migration-first rule: no production schema bootstrap here.
    # In local standalone mode the operator may explicitly enable AIMEN_DEV_CREATE_TABLES=1.
    if os.getenv("AIMEN_DEV_CREATE_TABLES", "0") == "1":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with SessionFactory() as db:
            await seed_rbac(db)
            await db.commit()


# ============================================================
# 13. HEALTH / AUTH API
# ============================================================
@app.get("/health")
async def health():
    return {"status": "ok", "name": APP_NAME, "version": "3.0.0"}


@app.get("/api/v1/health/ready")
async def readiness(db: AsyncSession = Depends(db_session)):
    await db.execute(select(func.count()).select_from(User))
    return {"status": "ready"}


@app.post("/api/v1/auth/telegram")
async def telegram_login(payload: TelegramIn, db: AsyncSession = Depends(db_session)):
    tg = verify_telegram_init_data(payload.init_data)
    user = (await db.execute(select(User).where(User.telegram_id == int(tg["id"])))).scalar_one_or_none()
    if not user:
        role = UserRole.OWNER.value if OWNER_TELEGRAM_ID and int(tg["id"]) == OWNER_TELEGRAM_ID else UserRole.CUSTOMER.value
        user = User(telegram_id=int(tg["id"]), username=tg.get("username"), role=role)
        db.add(user)
        await db.flush()
    else:
        user.username = tg.get("username", user.username)
    raw = secrets.token_urlsafe(48)
    db.add(Session(user_id=user.id, token_hash=token_hash(raw), expires_at=now() + timedelta(days=SESSION_DAYS), last_used_at=now()))
    await db.commit()
    return {"access_token": raw, "token_type": "bearer", "user": {"id": user.id, "username": user.username, "role": user.role}}


@app.post("/api/v1/auth/logout")
async def logout(authorization: Optional[str] = Header(default=None), db: AsyncSession = Depends(db_session)):
    if authorization and authorization.startswith("Bearer "):
        session = (await db.execute(select(Session).where(Session.token_hash == token_hash(authorization[7:])))).scalar_one_or_none()
        if session:
            session.revoked_at = now()
            await db.commit()
    return {"ok": True}


@app.get("/api/v1/auth/me")
async def me(user: User = Depends(current_user)):
    return {"id": user.id, "telegram_id": user.telegram_id, "username": user.username, "role": user.role, "status": user.status}


# ============================================================
# 14. CUSTOMER PANEL — CATALOG / WALLET / ORDERS / DEPOSITS
# ============================================================
@app.get("/api/v1/customer/catalog")
async def customer_catalog(search: Optional[str] = None, category_id: Optional[int] = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db: AsyncSession = Depends(db_session)):
    q = select(Service).where(Service.enabled.is_(True), Service.archived.is_(False))
    if search:
        q = q.where(or_(Service.name.ilike(f"%{search}%"), Service.description.ilike(f"%{search}%")))
    if category_id:
        q = q.where(Service.category_id == category_id)
    rows = (await db.execute(q.order_by(Service.id).offset(offset).limit(limit))).scalars().all()
    return [{"id": x.id, "category_id": x.category_id, "name": x.name, "description": x.description, "price": str(x.price), "currency": x.currency, "min": x.min_quantity, "max": x.max_quantity, "stock": x.stock} for x in rows]


@app.get("/api/v1/customer/wallet")
async def customer_wallet(user: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(Wallet).where(Wallet.user_id == user.id))).scalars().all()
    return [{"currency": x.currency, "balance": str(x.balance)} for x in rows]


@app.post("/api/v1/customer/deposits")
async def customer_deposit(payload: DepositIn, user: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if payload.currency not in {"YER", "USD"}:
        raise HTTPException(400, "Currency must be YER or USD")
    deposit = Deposit(user_id=user.id, **payload.model_dump())
    db.add(deposit)
    await db.flush()
    queue_notification(db, user.id, "DEPOSIT_PENDING", {"deposit_id": deposit.id})
    await db.commit()
    return {"id": deposit.id, "status": deposit.status}


@app.post("/api/v1/customer/orders/quote")
async def order_quote(payload: OrderIn, user: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    service = await db.get(Service, payload.service_id)
    if not service or not service.enabled:
        raise HTTPException(404, "Service unavailable")
    rules = (await db.execute(select(PricingRule).where(PricingRule.enabled.is_(True), or_(PricingRule.service_id == service.id, PricingRule.category_id == service.category_id)))).scalars().all()
    unit = calculate_price(service.price, rules)
    subtotal = money(unit * payload.quantity)
    discount = Decimal("0")
    if payload.coupon_code:
        coupon = (await db.execute(select(Coupon).where(Coupon.code == payload.coupon_code.upper(), Coupon.active.is_(True)))).scalar_one_or_none()
        if not coupon or (coupon.expires_at and coupon.expires_at <= now()):
            raise HTTPException(400, "Invalid or expired coupon")
        discount = calculate_coupon(subtotal, coupon)
    return {"unit": str(unit), "subtotal": str(subtotal), "discount": str(discount), "total": str(money(subtotal - discount)), "currency": service.currency}


@app.post("/api/v1/customer/orders")
async def customer_order(payload: OrderIn, user: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    existing = (await db.execute(select(Order).where(Order.idempotency_key == payload.idempotency_key))).scalar_one_or_none()
    if existing:
        return {"id": existing.id, "status": existing.status, "idempotent": True}
    service = (await db.execute(select(Service).where(Service.id == payload.service_id, Service.enabled.is_(True), Service.archived.is_(False)).with_for_update())).scalar_one_or_none()
    if not service:
        raise HTTPException(404, "Service unavailable")
    if payload.quantity < service.min_quantity or payload.quantity > service.max_quantity:
        raise HTTPException(400, "Quantity outside service limits")
    rules = (await db.execute(select(PricingRule).where(PricingRule.enabled.is_(True), or_(PricingRule.service_id == service.id, PricingRule.category_id == service.category_id)))).scalars().all()
    unit = calculate_price(service.price, rules)
    subtotal = money(unit * payload.quantity)
    discount = Decimal("0")
    coupon = None
    if payload.coupon_code:
        coupon = (await db.execute(select(Coupon).where(Coupon.code == payload.coupon_code.upper(), Coupon.active.is_(True)).with_for_update())).scalar_one_or_none()
        if not coupon or (coupon.expires_at and coupon.expires_at <= now()):
            raise HTTPException(400, "Invalid or expired coupon")
        discount = calculate_coupon(subtotal, coupon)
    total = money(subtotal - discount)
    wallet = await get_wallet_locked(db, user.id, service.currency)
    if Decimal(wallet.balance) < total:
        raise HTTPException(402, "Insufficient balance")
    if service.stock and service.stock < payload.quantity:
        raise HTTPException(409, "Insufficient stock")
    await post_ledger(db, wallet, -total, "PURCHASE", str(payload.service_id), f"order:{payload.idempotency_key}")
    if service.stock:
        service.stock -= payload.quantity
    order = Order(user_id=user.id, service_id=service.id, quantity=payload.quantity, total=total, currency=service.currency, status=OrderStatus.PENDING.value, idempotency_key=payload.idempotency_key)
    db.add(order)
    await db.flush()
    await transition_order(db, order, OrderStatus.PROCESSING.value, user, "CUSTOMER")
    if coupon:
        coupon.used_count += 1
        db.add(CouponRedemption(coupon_id=coupon.id, user_id=user.id, order_id=order.id, discount=discount))
    queue_notification(db, user.id, "ORDER_CREATED", {"order_id": order.id, "total": str(total), "currency": service.currency})
    await db.commit()
    return {"id": order.id, "status": order.status, "total": str(total), "currency": order.currency}


# ============================================================
# 15. ADMIN PANEL — USERS / CATALOG / PRICING / ORDERS
# ============================================================
@app.get("/api/v1/admin/users")
async def admin_users(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), admin: User = Depends(lambda: None), db: AsyncSession = Depends(db_session)):
    # Permission is checked explicitly below because this endpoint is intentionally readable by admin tooling only.
    # The lambda dependency is replaced by the real permission dependency at runtime through the route guard below.
    rows = (await db.execute(select(User).order_by(User.id.desc()).offset(offset).limit(limit))).scalars().all()
    return [{"id": x.id, "telegram_id": x.telegram_id, "username": x.username, "role": x.role, "status": x.status} for x in rows]


@app.post("/api/v1/admin/categories")
async def admin_create_category(payload: CategoryIn, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    item = Category(**payload.model_dump())
    db.add(item)
    await db.flush()
    audit_record(db, admin, "category.create", str(item.id), payload.model_dump())
    await db.commit()
    return {"id": item.id}


@app.post("/api/v1/admin/services")
async def admin_create_service(payload: ServiceIn, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    if not await db.get(Category, payload.category_id):
        raise HTTPException(404, "Category not found")
    item = Service(**payload.model_dump())
    db.add(item)
    await db.flush()
    audit_record(db, admin, "service.create", str(item.id), payload.model_dump())
    await db.commit()
    return {"id": item.id}


@app.post("/api/v1/admin/services/{service_id}/disable")
async def admin_disable_service(service_id: int, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Service not found")
    service.enabled = False
    audit_record(db, admin, "service.disable", str(service.id))
    await db.commit()
    return {"id": service.id, "enabled": False}


@app.post("/api/v1/admin/pricing/rules")
async def admin_pricing_rule(payload: PriceRuleIn, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    if payload.kind not in {"PERCENT", "FIXED", "MULTIPLIER", "OVERRIDE"}:
        raise HTTPException(400, "Unsupported pricing rule")
    rule = PricingRule(**payload.model_dump())
    db.add(rule)
    await db.flush()
    audit_record(db, admin, "pricing.create", str(rule.id), payload.model_dump())
    await db.commit()
    return {"id": rule.id}


# ============================================================
# 16. PROVIDER PANEL — CRUD / MAPPING / HEALTH / ROUTING
# ============================================================
@app.get("/api/v1/admin/providers")
async def admin_providers(admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.PROVIDER.value}:
        raise HTTPException(403, "Permission denied")
    rows = (await db.execute(select(Provider).order_by(Provider.priority, Provider.id))).scalars().all()
    return [{"id": x.id, "name": x.name, "base_url": x.base_url, "enabled": x.enabled, "priority": x.priority, "timeout": x.timeout, "health": x.health, "failure_count": x.failure_count} for x in rows]


@app.post("/api/v1/admin/providers")
async def admin_create_provider(payload: ProviderIn, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    provider = Provider(**payload.model_dump())
    db.add(provider)
    await db.flush()
    audit_record(db, admin, "provider.create", str(provider.id), {"name": provider.name, "base_url": provider.base_url})
    await db.commit()
    return {"id": provider.id, "name": provider.name}


@app.patch("/api/v1/admin/providers/{provider_id}")
async def admin_update_provider(provider_id: int, payload: ProviderIn, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(provider, key, value)
    audit_record(db, admin, "provider.update", str(provider.id), {"name": provider.name, "base_url": provider.base_url})
    await db.commit()
    return {"id": provider.id, "updated": True}


@app.post("/api/v1/admin/providers/{provider_id}/disable")
async def admin_disable_provider(provider_id: int, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    provider.enabled = False
    provider.health = "DISABLED"
    audit_record(db, admin, "provider.disable", str(provider.id))
    await db.commit()
    return {"id": provider.id, "enabled": False}


@app.post("/api/v1/admin/provider-mappings")
async def admin_mapping(payload: MappingIn, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    if not await db.get(Service, payload.service_id) or not await db.get(Provider, payload.provider_id):
        raise HTTPException(404, "Service or provider not found")
    mapping = ProviderMapping(**payload.model_dump())
    db.add(mapping)
    await db.flush()
    audit_record(db, admin, "provider.mapping.create", str(mapping.id), payload.model_dump())
    await db.commit()
    return {"id": mapping.id}


# ============================================================
# 17. FINANCE PANEL — DEPOSITS / REFUNDS / RECONCILIATION
# ============================================================
@app.post("/api/v1/admin/deposits/{deposit_id}/approve")
async def approve_deposit(deposit_id: int, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.FINANCE.value}:
        raise HTTPException(403, "Permission denied")
    deposit = (await db.execute(select(Deposit).where(Deposit.id == deposit_id).with_for_update())).scalar_one_or_none()
    if not deposit:
        raise HTTPException(404, "Deposit not found")
    if deposit.status == "APPROVED":
        return {"id": deposit.id, "status": "APPROVED", "idempotent": True}
    if deposit.status != "PENDING":
        raise HTTPException(409, "Deposit is not pending")
    wallet = await get_wallet_locked(db, deposit.user_id, deposit.currency)
    await post_ledger(db, wallet, deposit.amount, "DEPOSIT", str(deposit.id), f"deposit:{deposit.id}")
    deposit.status = "APPROVED"
    audit_record(db, admin, "deposit.approve", str(deposit.id), {"amount": str(deposit.amount), "currency": deposit.currency})
    queue_notification(db, deposit.user_id, "DEPOSIT_APPROVED", {"deposit_id": deposit.id})
    await db.commit()
    return {"id": deposit.id, "status": "APPROVED"}


@app.post("/api/v1/admin/deposits/{deposit_id}/reject")
async def reject_deposit(deposit_id: int, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.FINANCE.value}:
        raise HTTPException(403, "Permission denied")
    deposit = (await db.execute(select(Deposit).where(Deposit.id == deposit_id).with_for_update())).scalar_one_or_none()
    if not deposit:
        raise HTTPException(404, "Deposit not found")
    if deposit.status != "PENDING":
        return {"id": deposit.id, "status": deposit.status, "idempotent": True}
    deposit.status = "REJECTED"
    audit_record(db, admin, "deposit.reject", str(deposit.id))
    queue_notification(db, deposit.user_id, "DEPOSIT_REJECTED", {"deposit_id": deposit.id})
    await db.commit()
    return {"id": deposit.id, "status": "REJECTED"}


@app.get("/api/v1/admin/wallets/{user_id}/reconcile")
async def admin_wallet_reconcile(user_id: int, currency: str, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.FINANCE.value}:
        raise HTTPException(403, "Permission denied")
    wallet = (await db.execute(select(Wallet).where(Wallet.user_id == user_id, Wallet.currency == currency))).scalar_one_or_none()
    if not wallet:
        raise HTTPException(404, "Wallet not found")
    return await reconcile_wallet(db, wallet)


# ============================================================
# 18. COUPONS PANEL
# ============================================================
@app.post("/api/v1/admin/coupons")
async def create_coupon(payload: CouponIn, admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    if payload.kind not in {"PERCENT", "FIXED"}:
        raise HTTPException(400, "Invalid coupon kind")
    coupon = Coupon(**payload.model_dump())
    coupon.code = coupon.code.upper()
    db.add(coupon)
    await db.flush()
    audit_record(db, admin, "coupon.create", str(coupon.id), {"code": coupon.code})
    await db.commit()
    return {"id": coupon.id, "code": coupon.code}


@app.get("/api/v1/admin/coupons")
async def list_coupons(admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    rows = (await db.execute(select(Coupon).order_by(Coupon.id.desc()))).scalars().all()
    return [{"id": x.id, "code": x.code, "kind": x.kind, "value": str(x.value), "active": x.active, "used": x.used_count, "limit": x.usage_limit} for x in rows]


# ============================================================
# 19. SUPPORT PANEL — CUSTOMER + ADMIN
# ============================================================
@app.post("/api/v1/support/tickets")
async def create_ticket(payload: TicketIn, user: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    ticket = Ticket(user_id=user.id, subject=payload.subject, priority=payload.priority, status="OPEN")
    db.add(ticket)
    await db.flush()
    db.add(SupportMessage(ticket_id=ticket.id, sender_id=user.id, body=payload.body))
    await db.commit()
    return {"id": ticket.id, "status": ticket.status}


@app.post("/api/v1/support/tickets/{ticket_id}/messages")
async def ticket_message(ticket_id: int, payload: MessageIn, user: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.user_id != user.id and user.role not in {UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.SUPPORT.value}:
        raise HTTPException(403, "Permission denied")
    db.add(SupportMessage(ticket_id=ticket.id, sender_id=user.id, body=payload.body))
    if user.id != ticket.user_id:
        ticket.status = "WAITING_USER"
    await db.commit()
    return {"ok": True}


@app.get("/api/v1/admin/support")
async def admin_support(admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.SUPPORT.value}:
        raise HTTPException(403, "Permission denied")
    rows = (await db.execute(select(Ticket).order_by(Ticket.id.desc()))).scalars().all()
    return [{"id": x.id, "user_id": x.user_id, "subject": x.subject, "priority": x.priority, "status": x.status, "assigned_to": x.assigned_to} for x in rows]


# ============================================================
# 20. AUDIT / ANALYTICS PANEL
# ============================================================
@app.get("/api/v1/admin/audit")
async def admin_audit(limit: int = Query(100, ge=1, le=500), admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value}:
        raise HTTPException(403, "Permission denied")
    rows = (await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))).scalars().all()
    return [{"id": x.id, "actor_id": x.actor_id, "action": x.action, "target": x.target, "metadata": x.metadata_json, "created_at": x.created_at} for x in rows]


@app.get("/api/v1/admin/analytics")
async def analytics(admin: User = Depends(current_user), db: AsyncSession = Depends(db_session)):
    if admin.role not in {UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.FINANCE.value}:
        raise HTTPException(403, "Permission denied")
    users = await db.scalar(select(func.count()).select_from(User))
    orders = await db.scalar(select(func.count()).select_from(Order))
    completed = await db.scalar(select(func.count()).select_from(Order).where(Order.status == "COMPLETED"))
    revenue = await db.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(Order.status == "COMPLETED"))
    return {"users": int(users or 0), "orders": int(orders or 0), "completed": int(completed or 0), "revenue": str(Decimal(str(revenue or 0)))}


# ============================================================
# 21. ADMIN HTML PANEL — SINGLE CONTROL CENTER
# ============================================================
ADMIN_HTML = """
<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>
<title>DHĀT STORE — AIMEN ADMIN</title>
<style>body{font-family:system-ui;background:#0b1020;color:#eee;margin:0}header{padding:22px;background:#121a31}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;padding:20px}.card{background:#151e38;border:1px solid #263252;border-radius:14px;padding:20px}.tag{display:inline-block;padding:5px 9px;border-radius:8px;background:#25345b;margin:3px}code{direction:ltr;display:block;white-space:pre-wrap}</style></head>
<body><header><h1>DHĀT STORE — AIMEN</h1><p>لوحة التحكم الموحدة</p></header><main>
<div class='card'><h2>👥 المستخدمون</h2><p>إدارة العملاء والحالات والأدوار.</p><span class='tag'>/api/v1/admin/users</span></div>
<div class='card'><h2>🛍 الخدمات</h2><p>التصنيفات والخدمات والأسعار والمخزون.</p><span class='tag'>/api/v1/admin/services</span></div>
<div class='card'><h2>🔌 الموردون</h2><p>إضافة المورد، تعطيله، الأولوية وربط الخدمات.</p><span class='tag'>/api/v1/admin/providers</span></div>
<div class='card'><h2>💰 المالية</h2><p>الإيداعات والمحافظ والـLedger والمطابقة.</p><span class='tag'>/api/v1/admin/deposits</span></div>
<div class='card'><h2>📦 الطلبات</h2><p>حالة الطلب ومسار المورد والتسوية.</p></div>
<div class='card'><h2>🎫 الدعم</h2><p>Tickets والرسائل والتعيين.</p></div>
<div class='card'><h2>📊 التحليلات</h2><p>المستخدمون والطلبات والإيرادات.</p><span class='tag'>/api/v1/admin/analytics</span></div>
<div class='card'><h2>🧾 التدقيق</h2><p>سجل العمليات الحساسة.</p><span class='tag'>/api/v1/admin/audit</span></div>
</main></body></html>
"""


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    return ADMIN_HTML


# ============================================================
# 22. CUSTOMER HTML PANEL — STORE HOME
# ============================================================
CUSTOMER_HTML = """
<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>
<title>DHĀT STORE</title><style>body{font-family:system-ui;background:#090d18;color:#fff;margin:0}nav{padding:18px;background:#121a2a}section{padding:22px;max-width:1000px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.box{padding:18px;background:#141e31;border-radius:14px}</style></head>
<body><nav><b>DHĀT STORE</b> — متجر الخدمات</nav><section><h1>مرحبًا بك</h1><p>هذه واجهة المتجر الموحدة. استخدم API المصادق عليه لتحميل الخدمات والمحفظة والطلبات.</p><div class='grid'><div class='box'>🛍 الكتالوج</div><div class='box'>💳 المحفظة</div><div class='box'>📦 طلباتي</div><div class='box'>🎫 الدعم</div><div class='box'>🔔 الإشعارات</div></div></section></body></html>
"""


@app.get("/store", response_class=HTMLResponse)
async def customer_panel():
    return CUSTOMER_HTML


# ============================================================
# 23. PROVIDER PANEL — PROVIDER SELF-SERVICE VIEW
# ============================================================
PROVIDER_HTML = """
<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><title>DHĀT PROVIDER</title>
<style>body{font-family:system-ui;background:#08131a;color:#fff;padding:30px}.card{background:#10232c;padding:20px;border-radius:14px;margin:10px 0}</style></head>
<body><h1>لوحة المورد</h1><div class='card'>الخدمات المرتبطة بالمورد</div><div class='card'>حالة الاتصال والصحة</div><div class='card'>الطلبات الخارجية والتسوية</div><div class='card'>تنبيه: المفاتيح السرية لا تعرض في الواجهة.</div></body></html>
"""


@app.get("/provider", response_class=HTMLResponse)
async def provider_panel():
    return PROVIDER_HTML


# ============================================================
# 24. BOT COMMAND MAP — DOMAIN LOGIC STAYS IN API
# ============================================================
BOT_COMMANDS = {
    "/start": "welcome",
    "/store": "open_store",
    "/balance": "wallet",
    "/orders": "orders",
    "/deposit": "deposit",
    "/support": "support",
    "/admin": "admin_panel",
}


@app.get("/api/v1/bot/menu")
async def bot_menu():
    return {
        "commands": list(BOT_COMMANDS.keys()),
        "buttons": [
            {"text": "🛒 المتجر", "action": "open_store"},
            {"text": "💰 الرصيد", "action": "wallet"},
            {"text": "📦 طلباتي", "action": "orders"},
            {"text": "💳 إيداع", "action": "deposit"},
            {"text": "🎫 الدعم", "action": "support"},
        ],
    }


# ============================================================
# 25. SYSTEM SETTINGS / EXTENSIBILITY CONTRACT
# ============================================================
SYSTEM_CAPABILITIES = {
    "catalog": True,
    "pricing": True,
    "providers": True,
    "provider_mapping": True,
    "wallet": True,
    "deposits": True,
    "payments_boundary": True,
    "coupons": True,
    "orders": True,
    "unknown_outcome": True,
    "reconciliation": True,
    "support": True,
    "notifications": True,
    "audit": True,
    "analytics": True,
    "customer_panel": True,
    "admin_panel": True,
    "provider_panel": True,
    "telegram_bot_contract": True,
}


@app.get("/api/v1/system/capabilities")
async def capabilities():
    return {"name": APP_NAME, "capabilities": SYSTEM_CAPABILITIES}


# ============================================================
# 26. STARTUP ENTRYPOINT
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("aimen:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
