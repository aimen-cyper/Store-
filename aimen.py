"""
DHĀT STORE — AIMEN
Unified single-file production-oriented commerce system.

This file is the application: API + database models + security + RBAC +
pricing + providers + wallet + deposits + coupons + orders + support +
audit + notifications + admin/customer/provider panels + Telegram webhook.

Run:
    uvicorn aimen:app --host 0.0.0.0 --port 8000

Required environment:
    DATABASE_URL=sqlite+aiosqlite:///./aimen.db
    TELEGRAM_BOT_TOKEN=
    OWNER_TELEGRAM_ID=0
    SESSION_DAYS=30
    TELEGRAM_AUTH_MAX_AGE=900
    CORS_ORIGINS=*

PostgreSQL example:
    postgresql+asyncpg://user:password@localhost/dhat

The application intentionally keeps business logic in one file as requested.
External provider credentials are configuration data and are never returned
by API responses. Production PostgreSQL should be used for deployment.
"""

# ============================================================
# 01 — IMPORTS / CONFIGURATION
# ============================================================
import os
import json
import hmac
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from enum import Enum
from typing import Any, Optional
from urllib.parse import parse_qsl

import httpx
from fastapi import FastAPI, Depends, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, JSON,
    UniqueConstraint, CheckConstraint, select, func, or_, and_
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

APP_NAME = "DHĀT STORE — AIMEN"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./aimen.db")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0") or 0)
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))
AUTH_MAX_AGE = int(os.getenv("TELEGRAM_AUTH_MAX_AGE", "900"))
CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
SECRET_PEPPER = os.getenv("AIMEN_SECRET_PEPPER", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aimen")
engine = create_async_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# ============================================================
# 02 — ENUMS / CONSTANTS
# ============================================================
class Role(str, Enum):
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

ORDER_TRANSITIONS = {
    "PENDING": {"PROCESSING", "CANCELED", "FAILED", "UNKNOWN"},
    "PROCESSING": {"IN_PROGRESS", "COMPLETED", "PARTIAL", "FAILED", "CANCELED", "UNKNOWN"},
    "IN_PROGRESS": {"COMPLETED", "PARTIAL", "FAILED", "CANCELED", "UNKNOWN"},
    "UNKNOWN": {"PROCESSING", "IN_PROGRESS", "COMPLETED", "PARTIAL", "FAILED", "CANCELED"},
    "COMPLETED": {"REFUNDING"},
    "PARTIAL": {"REFUNDING"},
    "FAILED": {"REFUNDING"},
    "REFUNDING": {"REFUNDED", "FAILED"},
    "CANCELED": {"REFUNDING"},
    "REFUNDED": set(),
}
PERMISSIONS = {
    "users.read", "users.update", "users.suspend", "admins.manage",
    "orders.read", "orders.manage", "orders.refund",
    "wallet.read", "wallet.adjust", "payments.read", "payments.manage",
    "providers.read", "providers.manage", "services.read", "services.manage",
    "pricing.read", "pricing.manage", "coupons.read", "coupons.manage",
    "support.read", "support.manage", "analytics.read", "audit.read",
    "settings.read", "settings.manage",
}
ROLE_PERMISSIONS = {
    Role.OWNER.value: PERMISSIONS,
    Role.ADMIN.value: PERMISSIONS - {"admins.manage", "settings.manage"},
    Role.FINANCE.value: {"users.read", "orders.read", "wallet.read", "wallet.adjust", "payments.read", "payments.manage", "coupons.read", "analytics.read", "audit.read"},
    Role.SUPPORT.value: {"users.read", "orders.read", "support.read", "support.manage"},
    Role.MODERATOR.value: {"users.read", "users.update", "orders.read", "orders.manage", "services.read", "providers.read", "support.read", "support.manage"},
    Role.PROVIDER.value: {"providers.read", "orders.read"},
    Role.CUSTOMER.value: set(),
}

# ============================================================
# 03 — DATABASE BASE / MODELS
# ============================================================
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(160))
    first_name: Mapped[Optional[str]] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(32), default=Role.CUSTOMER.value, index=True)
    status: Mapped[str] = mapped_column(String(32), default=UserStatus.ACTIVE.value, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

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
    permission: Mapped[str] = mapped_column(String(120), index=True)
    __table_args__ = (UniqueConstraint("role", "permission", name="uq_role_permission"),)

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
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
    __table_args__ = (UniqueConstraint("user_id", "currency", name="uq_wallet_currency"), CheckConstraint("balance >= 0", name="ck_wallet_nonnegative"))

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
    method: Mapped[str] = mapped_column(String(120), default="MANUAL")
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

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    total: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.PENDING.value, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    external_order_id: Mapped[Optional[str]] = mapped_column(String(200))
    external_outcome: Mapped[str] = mapped_column(String(32), default="NONE")
    requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

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
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[Optional[str]] = mapped_column(String(120))
    old_value: Mapped[Optional[dict]] = mapped_column(JSON)
    new_value: Mapped[Optional[dict]] = mapped_column(JSON)
    request_id: Mapped[Optional[str]] = mapped_column(String(120))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[Optional[str]] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

# ============================================================
# 04 — SCHEMAS / DTOs
# ============================================================
class TelegramAuthIn(BaseModel):
    init_data: str = Field(min_length=10)

class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    sort_order: int = 0

class ServiceIn(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    cost: Decimal = Field(ge=0)
    price: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    min_quantity: int = Field(default=1, ge=1)
    max_quantity: int = Field(default=1000000, ge=1)
    enabled: bool = True

class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    base_url: str = Field(min_length=1, max_length=1000)
    api_key: Optional[str] = None
    priority: int = 100
    timeout: int = Field(default=20, ge=1, le=120)
    enabled: bool = True
    supported_operations: dict[str, bool] = Field(default_factory=lambda: {"create_order": True, "status": True, "balance": True, "cancel": False, "refill": False})

class MappingIn(BaseModel):
    service_id: int
    provider_id: int
    external_service_id: str = Field(min_length=1, max_length=200)
    priority: int = 100
    enabled: bool = True

class DepositIn(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    method: str = Field(default="MANUAL", max_length=120)
    reference: str = Field(min_length=1, max_length=200)
    proof_url: Optional[str] = None

class OrderIn(BaseModel):
    service_id: int
    quantity: int = Field(gt=0)
    requirements: dict[str, Any] = Field(default_factory=dict)
    coupon: Optional[str] = None

class CouponIn(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    kind: str
    value: Decimal = Field(gt=0)
    min_order: Optional[Decimal] = Field(default=None, ge=0)
    max_discount: Optional[Decimal] = Field(default=None, ge=0)
    expires_at: Optional[datetime] = None
    usage_limit: Optional[int] = Field(default=None, ge=1)
    per_user_limit: int = Field(default=1, ge=1)
    active: bool = True

class TicketIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    priority: str = "NORMAL"

class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)

class UserRoleIn(BaseModel):
    role: Role

class UserStatusIn(BaseModel):
    status: UserStatus

# ============================================================
# 05 — UTILITIES / SECURITY PRIMITIVES
# ============================================================
def now() -> datetime:
    return datetime.now(timezone.utc)

def money(v: Decimal | int | float | str) -> Decimal:
    try:
        return Decimal(str(v)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(422, "invalid monetary value") from exc

def safe_currency(currency: str) -> str:
    currency = currency.upper().strip()
    if currency not in {"YER", "USD"}:
        raise HTTPException(422, "currency must be YER or USD")
    return currency

def hash_token(token: str) -> str:
    return hashlib.sha256((SECRET_PEPPER + token).encode()).hexdigest()

def create_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)

def clean_secret_provider(p: Provider) -> dict:
    return {"id": p.id, "name": p.name, "base_url": p.base_url, "enabled": p.enabled, "priority": p.priority, "timeout": p.timeout, "health": p.health, "supported_operations": p.supported_operations, "failure_count": p.failure_count}

# ============================================================
# 06 — TELEGRAM AUTHENTICATION
# ============================================================
def verify_telegram_init_data(init_data: str) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(503, "Telegram authentication is not configured")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise HTTPException(401, "missing Telegram signature")
    auth_date = pairs.get("auth_date")
    if not auth_date:
        raise HTTPException(401, "missing auth_date")
    try:
        if abs(int(datetime.now(timezone.utc).timestamp()) - int(auth_date)) > AUTH_MAX_AGE:
            raise HTTPException(401, "expired Telegram authentication")
    except ValueError as exc:
        raise HTTPException(401, "invalid auth_date") from exc
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise HTTPException(401, "invalid Telegram signature")
    raw_user = pairs.get("user")
    if not raw_user:
        raise HTTPException(401, "missing Telegram user")
    try:
        user = json.loads(raw_user)
        telegram_id = int(user["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(401, "invalid Telegram user payload") from exc
    return {"telegram_id": telegram_id, "username": user.get("username"), "first_name": user.get("first_name")}

# ============================================================
# 07 — DATABASE / DEPENDENCIES
# ============================================================
async def db_session():
    async with SessionFactory() as db:
        yield db

async def audit(db: AsyncSession, actor_id: Optional[int], action: str, target_type: str, target_id: Optional[str] = None, old: Optional[dict] = None, new: Optional[dict] = None, request_id: Optional[str] = None, metadata: Optional[dict] = None):
    db.add(AuditLog(actor_id=actor_id, action=action, target_type=target_type, target_id=target_id, old_value=old, new_value=new, request_id=request_id, metadata_json=metadata or {}))

async def get_current_user(authorization: Optional[str] = Header(default=None), db: AsyncSession = Depends(db_session)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "authentication required")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(401, "authentication required")
    result = await db.execute(select(Session, User).join(User, User.id == Session.user_id).where(Session.token_hash == hash_token(token)))
    row = result.first()
    if not row:
        raise HTTPException(401, "invalid session")
    session, user = row
    if session.revoked_at or session.expires_at <= now():
        raise HTTPException(401, "session expired")
    if user.status != UserStatus.ACTIVE.value:
        raise HTTPException(403, "account is not active")
    session.last_used_at = now()
    return user

def require_roles(*roles: str):
    async def guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "insufficient role")
        return user
    return guard

def require_permission(permission: str):
    async def guard(user: User = Depends(get_current_user), db: AsyncSession = Depends(db_session)) -> User:
        if user.role == Role.OWNER.value:
            return user
        result = await db.execute(select(RolePermission).where(RolePermission.role == user.role, RolePermission.permission == permission))
        if not result.scalar_one_or_none() and permission not in ROLE_PERMISSIONS.get(user.role, set()):
            raise HTTPException(403, "permission denied")
        return user
    return guard

# ============================================================
# 08 — AUTH ROUTES
# ============================================================
app = FastAPI(title=APP_NAME, version="1.0.0", docs_url="/docs", redoc_url="/redoc")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health():
    return {"status": "ok", "service": APP_NAME, "time": now().isoformat()}

@app.post("/api/v1/auth/telegram")
async def telegram_login(payload: TelegramAuthIn, db: AsyncSession = Depends(db_session)):
    data = verify_telegram_init_data(payload.init_data)
    result = await db.execute(select(User).where(User.telegram_id == data["telegram_id"]))
    user = result.scalar_one_or_none()
    if not user:
        role = Role.OWNER.value if OWNER_TELEGRAM_ID and data["telegram_id"] == OWNER_TELEGRAM_ID else Role.CUSTOMER.value
        user = User(telegram_id=data["telegram_id"], username=data.get("username"), first_name=data.get("first_name"), role=role)
        db.add(user)
        await db.flush()
    else:
        user.username = data.get("username")
        user.first_name = data.get("first_name")
    if user.status != UserStatus.ACTIVE.value:
        raise HTTPException(403, "account is not active")
    raw, hashed = create_token()
    db.add(Session(user_id=user.id, token_hash=hashed, expires_at=now() + timedelta(days=SESSION_DAYS)))
    await audit(db, user.id, "AUTH_LOGIN", "USER", str(user.id))
    await db.commit()
    return {"access_token": raw, "token_type": "bearer", "expires_in": SESSION_DAYS * 86400, "user": {"id": user.id, "telegram_id": user.telegram_id, "username": user.username, "role": user.role, "status": user.status}}

@app.post("/api/v1/auth/logout")
async def logout(authorization: Optional[str] = Header(default=None), db: AsyncSession = Depends(db_session)):
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        result = await db.execute(select(Session).where(Session.token_hash == hash_token(token)))
        s = result.scalar_one_or_none()
        if s:
            s.revoked_at = now()
            await db.commit()
    return {"ok": True}

@app.get("/api/v1/auth/me")
async def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "telegram_id": user.telegram_id, "username": user.username, "first_name": user.first_name, "role": user.role, "status": user.status}

# ============================================================
# 09 — CATALOG / SERVICE MANAGEMENT
# ============================================================
@app.get("/api/v1/catalog/categories")
async def categories(db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(Category).where(Category.enabled == True, Category.archived == False).order_by(Category.sort_order, Category.id))).scalars().all()
    return [{"id": x.id, "name": x.name, "slug": x.slug, "sort_order": x.sort_order} for x in rows]

@app.post("/api/v1/admin/categories")
async def create_category(payload: CategoryIn, user: User = Depends(require_permission("services.manage")), db: AsyncSession = Depends(db_session)):
    exists = await db.execute(select(Category).where(Category.slug == payload.slug))
    if exists.scalar_one_or_none(): raise HTTPException(409, "category slug already exists")
    c = Category(**payload.model_dump())
    db.add(c); await db.flush(); await audit(db, user.id, "CATEGORY_CREATE", "CATEGORY", str(c.id), new=payload.model_dump()); await db.commit()
    return {"id": c.id, **payload.model_dump()}

@app.get("/api/v1/catalog/services")
async def services(search: Optional[str] = None, category_id: Optional[int] = None, currency: Optional[str] = None, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(db_session)):
    q = select(Service).where(Service.enabled == True, Service.archived == False)
    if search: q = q.where(or_(Service.name.ilike(f"%{search}%"), Service.description.ilike(f"%{search}%")))
    if category_id: q = q.where(Service.category_id == category_id)
    if currency: q = q.where(Service.currency == safe_currency(currency))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.order_by(Service.id.desc()).offset((page-1)*size).limit(size))).scalars().all()
    return {"items": [{"id": s.id, "category_id": s.category_id, "name": s.name, "description": s.description, "price": str(s.price), "cost": str(s.cost), "currency": s.currency, "min_quantity": s.min_quantity, "max_quantity": s.max_quantity} for s in rows], "page": page, "size": size, "total": total}

@app.get("/api/v1/catalog/services/{service_id}")
async def service_detail(service_id: int, db: AsyncSession = Depends(db_session)):
    s = await db.get(Service, service_id)
    if not s or not s.enabled or s.archived: raise HTTPException(404, "service not found")
    return {"id": s.id, "category_id": s.category_id, "name": s.name, "description": s.description, "price": str(s.price), "currency": s.currency, "min_quantity": s.min_quantity, "max_quantity": s.max_quantity}

@app.post("/api/v1/admin/services")
async def create_service(payload: ServiceIn, user: User = Depends(require_permission("services.manage")), db: AsyncSession = Depends(db_session)):
    safe_currency(payload.currency)
    if payload.max_quantity < payload.min_quantity: raise HTTPException(422, "invalid quantity range")
    if not await db.get(Category, payload.category_id): raise HTTPException(404, "category not found")
    s = Service(**payload.model_dump()); db.add(s); await db.flush(); await audit(db, user.id, "SERVICE_CREATE", "SERVICE", str(s.id), new=payload.model_dump(mode="json")); await db.commit()
    return {"id": s.id, **payload.model_dump(mode="json")}

@app.put("/api/v1/admin/services/{service_id}")
async def update_service(service_id: int, payload: ServiceIn, user: User = Depends(require_permission("services.manage")), db: AsyncSession = Depends(db_session)):
    s = await db.get(Service, service_id)
    if not s: raise HTTPException(404, "service not found")
    old = {"name": s.name, "price": str(s.price), "cost": str(s.cost), "enabled": s.enabled}
    safe_currency(payload.currency)
    for k, v in payload.model_dump().items(): setattr(s, k, v)
    await audit(db, user.id, "SERVICE_UPDATE", "SERVICE", str(s.id), old=old, new=payload.model_dump(mode="json")); await db.commit()
    return {"id": s.id, **payload.model_dump(mode="json")}

@app.delete("/api/v1/admin/services/{service_id}")
async def archive_service(service_id: int, user: User = Depends(require_permission("services.manage")), db: AsyncSession = Depends(db_session)):
    s = await db.get(Service, service_id)
    if not s: raise HTTPException(404, "service not found")
    s.archived = True; s.enabled = False
    await audit(db, user.id, "SERVICE_ARCHIVE", "SERVICE", str(service_id)); await db.commit()
    return {"ok": True}

# ============================================================
# 10 — PRICING ENGINE
# ============================================================
def calculate_discount(coupon: Coupon, subtotal: Decimal) -> Decimal:
    if not coupon.active or (coupon.expires_at and coupon.expires_at <= now()): return Decimal("0")
    if coupon.min_order is not None and subtotal < coupon.min_order: return Decimal("0")
    if coupon.kind == "percentage": discount = subtotal * coupon.value / Decimal("100")
    elif coupon.kind == "fixed": discount = coupon.value
    else: raise HTTPException(422, "invalid coupon kind")
    if coupon.max_discount is not None: discount = min(discount, coupon.max_discount)
    return max(Decimal("0"), min(discount, subtotal))

@app.post("/api/v1/pricing/quote")
async def quote(payload: OrderIn, db: AsyncSession = Depends(db_session)):
    s = await db.get(Service, payload.service_id)
    if not s or not s.enabled or s.archived: raise HTTPException(404, "service not found")
    if not s.min_quantity <= payload.quantity <= s.max_quantity: raise HTTPException(422, "quantity outside allowed range")
    unit = money(s.price); subtotal = money(unit * payload.quantity); discount = Decimal("0")
    if payload.coupon:
        c = (await db.execute(select(Coupon).where(func.upper(Coupon.code) == payload.coupon.upper()))).scalar_one_or_none()
        if not c: raise HTTPException(404, "coupon not found")
        discount = calculate_discount(c, subtotal)
    total = money(subtotal - discount)
    return {"service_id": s.id, "quantity": payload.quantity, "currency": s.currency, "cost": str(money(s.cost * payload.quantity)), "subtotal": str(subtotal), "discount": str(discount), "total": str(total), "profit": str(money(total - s.cost * payload.quantity))}

@app.post("/api/v1/admin/pricing/rules")
async def create_pricing_rule(service_id: Optional[int] = None, category_id: Optional[int] = None, provider_id: Optional[int] = None, kind: str = "percentage", value: Decimal = Decimal("0"), user: User = Depends(require_permission("pricing.manage")), db: AsyncSession = Depends(db_session)):
    if kind not in {"percentage", "fixed", "multiplier", "override"}: raise HTTPException(422, "invalid pricing rule")
    if value < 0: raise HTTPException(422, "negative pricing rule")
    r = PricingRule(service_id=service_id, category_id=category_id, provider_id=provider_id, kind=kind, value=money(value)); db.add(r); await db.flush(); await audit(db, user.id, "PRICING_RULE_CREATE", "PRICING_RULE", str(r.id)); await db.commit(); return {"id": r.id}

# ============================================================
# 11 — PROVIDER ADAPTER / REGISTRY / ROUTER
# ============================================================
class ProviderAdapter:
    def __init__(self, provider: Provider): self.provider = provider
    def headers(self): return {"Authorization": f"Bearer {self.provider.api_key}"} if self.provider.api_key else {}
    async def request(self, method: str, path: str, **kwargs):
        url = self.provider.base_url.rstrip("/") + "/" + path.lstrip("/")
        timeout = httpx.Timeout(self.provider.timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.request(method, url, headers=self.headers(), **kwargs)
    async def get_services(self): return await self.request("GET", "/services")
    async def get_balance(self): return await self.request("GET", "/balance")
    async def create_order(self, external_service_id: str, quantity: int, requirements: dict):
        return await self.request("POST", "/orders", json={"service": external_service_id, "quantity": quantity, **requirements})
    async def get_order_status(self, external_order_id: str): return await self.request("GET", f"/orders/{external_order_id}")
    async def cancel_order(self, external_order_id: str): return await self.request("POST", f"/orders/{external_order_id}/cancel")
    async def refill_order(self, external_order_id: str): return await self.request("POST", f"/orders/{external_order_id}/refill")

async def choose_provider(db: AsyncSession, service_id: int, operation: str = "create_order") -> tuple[Provider, ProviderMapping]:
    result = await db.execute(select(Provider, ProviderMapping).join(ProviderMapping, Provider.id == ProviderMapping.provider_id).where(ProviderMapping.service_id == service_id, ProviderMapping.enabled == True, Provider.enabled == True).order_by(ProviderMapping.priority, Provider.priority))
    rows = result.all()
    for p, m in rows:
        if p.health == "DOWN": continue
        if p.supported_operations and not p.supported_operations.get(operation, False): continue
        return p, m
    raise HTTPException(503, "no healthy provider mapping available")

@app.get("/api/v1/admin/providers")
async def list_providers(user: User = Depends(require_permission("providers.read")), db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(Provider).order_by(Provider.priority, Provider.id))).scalars().all()
    return [clean_secret_provider(x) for x in rows]

@app.post("/api/v1/admin/providers")
async def create_provider(payload: ProviderIn, user: User = Depends(require_permission("providers.manage")), db: AsyncSession = Depends(db_session)):
    p = Provider(**payload.model_dump()); db.add(p); await db.flush(); await audit(db, user.id, "PROVIDER_CREATE", "PROVIDER", str(p.id), new={"name": p.name, "base_url": p.base_url}); await db.commit(); return clean_secret_provider(p)

@app.put("/api/v1/admin/providers/{provider_id}")
async def update_provider(provider_id: int, payload: ProviderIn, user: User = Depends(require_permission("providers.manage")), db: AsyncSession = Depends(db_session)):
    p = await db.get(Provider, provider_id)
    if not p: raise HTTPException(404, "provider not found")
    for k, v in payload.model_dump().items(): setattr(p, k, v)
    await audit(db, user.id, "PROVIDER_UPDATE", "PROVIDER", str(p.id), new={"name": p.name, "base_url": p.base_url, "enabled": p.enabled}); await db.commit(); return clean_secret_provider(p)

@app.post("/api/v1/admin/provider-mappings")
async def create_mapping(payload: MappingIn, user: User = Depends(require_permission("providers.manage")), db: AsyncSession = Depends(db_session)):
    if not await db.get(Service, payload.service_id): raise HTTPException(404, "service not found")
    if not await db.get(Provider, payload.provider_id): raise HTTPException(404, "provider not found")
    exists = await db.execute(select(ProviderMapping).where(ProviderMapping.service_id == payload.service_id, ProviderMapping.provider_id == payload.provider_id))
    if exists.scalar_one_or_none(): raise HTTPException(409, "mapping already exists")
    m = ProviderMapping(**payload.model_dump()); db.add(m); await db.flush(); await audit(db, user.id, "PROVIDER_MAPPING_CREATE", "MAPPING", str(m.id)); await db.commit(); return {"id": m.id, **payload.model_dump()}

@app.get("/api/v1/admin/provider-mappings")
async def list_mappings(user: User = Depends(require_permission("providers.read")), db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(ProviderMapping).order_by(ProviderMapping.service_id, ProviderMapping.priority))).scalars().all()
    return [{"id": x.id, "service_id": x.service_id, "provider_id": x.provider_id, "external_service_id": x.external_service_id, "priority": x.priority, "enabled": x.enabled} for x in rows]

@app.post("/api/v1/admin/providers/{provider_id}/health")
async def provider_health(provider_id: int, user: User = Depends(require_permission("providers.manage")), db: AsyncSession = Depends(db_session)):
    p = await db.get(Provider, provider_id)
    if not p: raise HTTPException(404, "provider not found")
    try:
        response = await ProviderAdapter(p).get_balance()
        if response.status_code >= 400: raise RuntimeError(f"provider status {response.status_code}")
        p.health = "UP"; p.failure_count = 0
    except Exception as exc:
        p.health = "DOWN"; p.failure_count += 1; log.warning("provider health failed: %s", exc)
    await db.commit(); return clean_secret_provider(p)

# ============================================================
# 12 — WALLET / LEDGER / FINANCIAL INTEGRITY
# ============================================================
async def get_wallet(db: AsyncSession, user_id: int, currency: str) -> Wallet:
    currency = safe_currency(currency)
    w = (await db.execute(select(Wallet).where(Wallet.user_id == user_id, Wallet.currency == currency))).scalar_one_or_none()
    if not w:
        w = Wallet(user_id=user_id, currency=currency, balance=Decimal("0")); db.add(w); await db.flush()
    return w

async def post_ledger(db: AsyncSession, wallet: Wallet, amount: Decimal, kind: str, reference: str, idem: str):
    existing = (await db.execute(select(Ledger).where(Ledger.idempotency_key == idem))).scalar_one_or_none()
    if existing: return existing
    amount = money(amount)
    if wallet.balance + amount < 0: raise HTTPException(409, "insufficient wallet balance")
    wallet.balance = money(wallet.balance + amount)
    entry = Ledger(wallet_id=wallet.id, amount=amount, type=kind, reference=reference, idempotency_key=idem); db.add(entry); await db.flush(); return entry

@app.get("/api/v1/wallet")
async def wallet(user: User = Depends(get_current_user), db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(Wallet).where(Wallet.user_id == user.id))).scalars().all()
    return [{"currency": w.currency, "balance": str(w.balance)} for w in rows]

@app.get("/api/v1/wallet/transactions")
async def wallet_transactions(user: User = Depends(get_current_user), currency: Optional[str] = None, db: AsyncSession = Depends(db_session)):
    q = select(Ledger).join(Wallet, Wallet.id == Ledger.wallet_id).where(Wallet.user_id == user.id)
    if currency: q = q.where(Wallet.currency == safe_currency(currency))
    rows = (await db.execute(q.order_by(Ledger.id.desc()).limit(200))).scalars().all()
    return [{"id": x.id, "amount": str(x.amount), "type": x.type, "reference": x.reference, "created_at": x.created_at.isoformat()} for x in rows]

@app.post("/api/v1/admin/wallet/{user_id}/adjust")
async def adjust_wallet(user_id: int, amount: Decimal, currency: str, reason: str = Query(..., min_length=1), user: User = Depends(require_permission("wallet.adjust")), db: AsyncSession = Depends(db_session)):
    target = await db.get(User, user_id)
    if not target: raise HTTPException(404, "user not found")
    w = await get_wallet(db, user_id, currency)
    await post_ledger(db, w, money(amount), "ADJUSTMENT", reason, f"adjust:{user_id}:{secrets.token_hex(8)}")
    await audit(db, user.id, "WALLET_ADJUST", "WALLET", str(w.id), new={"amount": str(amount), "currency": currency, "reason": reason}); await db.commit(); return {"currency": w.currency, "balance": str(w.balance)}

# ============================================================
# 13 — MANUAL DEPOSITS
# ============================================================
@app.post("/api/v1/deposits")
async def create_deposit(payload: DepositIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(db_session)):
    currency = safe_currency(payload.currency)
    d = Deposit(user_id=user.id, amount=money(payload.amount), currency=currency, method=payload.method, reference=payload.reference, proof_url=payload.proof_url)
    db.add(d); await db.flush(); await audit(db, user.id, "DEPOSIT_CREATE", "DEPOSIT", str(d.id)); await db.commit(); return {"id": d.id, "status": d.status, "amount": str(d.amount), "currency": d.currency}

@app.get("/api/v1/admin/deposits")
async def admin_deposits(status: Optional[str] = None, user: User = Depends(require_permission("payments.read")), db: AsyncSession = Depends(db_session)):
    q = select(Deposit).order_by(Deposit.id.desc())
    if status: q = q.where(Deposit.status == status.upper())
    rows = (await db.execute(q.limit(500))).scalars().all()
    return [{"id": d.id, "user_id": d.user_id, "amount": str(d.amount), "currency": d.currency, "method": d.method, "reference": d.reference, "proof_url": d.proof_url, "status": d.status} for d in rows]

@app.post("/api/v1/admin/deposits/{deposit_id}/approve")
async def approve_deposit(deposit_id: int, user: User = Depends(require_permission("payments.manage")), db: AsyncSession = Depends(db_session)):
    d = await db.get(Deposit, deposit_id)
    if not d: raise HTTPException(404, "deposit not found")
    if d.status == "APPROVED": return {"ok": True, "status": "APPROVED", "idempotent": True}
    if d.status != "PENDING": raise HTTPException(409, "deposit is not pending")
    w = await get_wallet(db, d.user_id, d.currency)
    await post_ledger(db, w, d.amount, "DEPOSIT", f"deposit:{d.id}", f"deposit-approval:{d.id}")
    d.status = "APPROVED"
    await audit(db, user.id, "DEPOSIT_APPROVE", "DEPOSIT", str(d.id), new={"status": "APPROVED", "amount": str(d.amount), "currency": d.currency})
    await db.commit(); return {"ok": True, "status": d.status, "wallet_balance": str(w.balance)}

@app.post("/api/v1/admin/deposits/{deposit_id}/reject")
async def reject_deposit(deposit_id: int, reason: str = Query(..., min_length=1), user: User = Depends(require_permission("payments.manage")), db: AsyncSession = Depends(db_session)):
    d = await db.get(Deposit, deposit_id)
    if not d: raise HTTPException(404, "deposit not found")
    if d.status != "PENDING": raise HTTPException(409, "deposit is not pending")
    d.status = "REJECTED"; await audit(db, user.id, "DEPOSIT_REJECT", "DEPOSIT", str(d.id), new={"reason": reason}); await db.commit(); return {"ok": True, "status": d.status}

# ============================================================
# 14 — COUPONS
# ============================================================
@app.post("/api/v1/admin/coupons")
async def create_coupon(payload: CouponIn, user: User = Depends(require_permission("coupons.manage")), db: AsyncSession = Depends(db_session)):
    if payload.kind not in {"percentage", "fixed"}: raise HTTPException(422, "invalid coupon kind")
    if payload.kind == "percentage" and payload.value > 100: raise HTTPException(422, "percentage cannot exceed 100")
    exists = await db.execute(select(Coupon).where(func.upper(Coupon.code) == payload.code.upper()))
    if exists.scalar_one_or_none(): raise HTTPException(409, "coupon exists")
    data = payload.model_dump(); data["code"] = payload.code.upper(); c = Coupon(**data); db.add(c); await db.flush(); await audit(db, user.id, "COUPON_CREATE", "COUPON", str(c.id)); await db.commit(); return {"id": c.id, "code": c.code}

@app.get("/api/v1/admin/coupons")
async def list_coupons(user: User = Depends(require_permission("coupons.read")), db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(Coupon).order_by(Coupon.id.desc()))).scalars().all()
    return [{"id": c.id, "code": c.code, "kind": c.kind, "value": str(c.value), "used_count": c.used_count, "usage_limit": c.usage_limit, "active": c.active, "expires_at": c.expires_at.isoformat() if c.expires_at else None} for c in rows]

# ============================================================
# 15 — ORDER ENGINE / IDEMPOTENCY / UNKNOWN OUTCOME
# ============================================================
async def add_order_event(db: AsyncSession, order: Order, old: str, new: str, actor_id: Optional[int], source: str, metadata: Optional[dict] = None):
    allowed = ORDER_TRANSITIONS.get(old, set())
    if new != old and new not in allowed: raise HTTPException(409, f"invalid order transition {old} -> {new}")
    db.add(OrderEvent(order_id=order.id, old_status=old, new_status=new, actor_id=actor_id, source=source, metadata_json=metadata or {}))
    order.status = new; order.updated_at = now()

@app.post("/api/v1/orders")
async def create_order(payload: OrderIn, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(db_session)):
    idem = request.headers.get("Idempotency-Key")
    if not idem: raise HTTPException(400, "Idempotency-Key header is required")
    existing = (await db.execute(select(Order).where(Order.idempotency_key == idem))).scalar_one_or_none()
    if existing:
        if existing.user_id != user.id: raise HTTPException(409, "idempotency key already belongs to another user")
        return {"id": existing.id, "status": existing.status, "total": str(existing.total), "currency": existing.currency, "idempotent": True}
    service = await db.get(Service, payload.service_id)
    if not service or not service.enabled or service.archived: raise HTTPException(404, "service not found")
    if not service.min_quantity <= payload.quantity <= service.max_quantity: raise HTTPException(422, "quantity outside allowed range")
    unit = money(service.price); subtotal = money(unit * payload.quantity); discount = Decimal("0"); coupon = None
    if payload.coupon:
        coupon = (await db.execute(select(Coupon).where(func.upper(Coupon.code) == payload.coupon.upper()))).scalar_one_or_none()
        if not coupon: raise HTTPException(404, "coupon not found")
        if coupon.usage_limit is not None and coupon.used_count >= coupon.usage_limit: raise HTTPException(409, "coupon exhausted")
        discount = calculate_discount(coupon, subtotal)
        if discount <= 0: raise HTTPException(409, "coupon is not applicable")
    total = money(subtotal - discount)
    wallet = await get_wallet(db, user.id, service.currency)
    if wallet.balance < total: raise HTTPException(409, "insufficient wallet balance")
    order = Order(user_id=user.id, service_id=service.id, quantity=payload.quantity, unit_price=unit, total=total, currency=service.currency, idempotency_key=idem, requirements=payload.requirements)
    db.add(order); await db.flush()
    await post_ledger(db, wallet, -total, "PURCHASE", f"order:{order.id}", f"order-debit:{order.id}")
    await add_order_event(db, order, "PENDING", "PROCESSING", user.id, "customer", {"discount": str(discount)})
    if coupon:
        coupon.used_count += 1
    await audit(db, user.id, "ORDER_CREATE", "ORDER", str(order.id), new={"total": str(total), "currency": service.currency})
    await db.commit()
    return {"id": order.id, "status": order.status, "total": str(order.total), "currency": order.currency, "message": "order accepted; provider submission is handled separately"}

@app.get("/api/v1/orders")
async def my_orders(page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200), user: User = Depends(get_current_user), db: AsyncSession = Depends(db_session)):
    q = select(Order).where(Order.user_id == user.id).order_by(Order.id.desc())
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.offset((page-1)*size).limit(size))).scalars().all()
    return {"items": [{"id": o.id, "service_id": o.service_id, "quantity": o.quantity, "total": str(o.total), "currency": o.currency, "status": o.status, "external_order_id": o.external_order_id} for o in rows], "total": total, "page": page, "size": size}

@app.get("/api/v1/admin/orders")
async def admin_orders(status: Optional[str] = None, user: User = Depends(require_permission("orders.read")), db: AsyncSession = Depends(db_session)):
    q = select(Order).order_by(Order.id.desc())
    if status: q = q.where(Order.status == status.upper())
    rows = (await db.execute(q.limit(500))).scalars().all()
    return [{"id": o.id, "user_id": o.user_id, "service_id": o.service_id, "quantity": o.quantity, "total": str(o.total), "currency": o.currency, "status": o.status, "external_order_id": o.external_order_id, "external_outcome": o.external_outcome} for o in rows]

@app.post("/api/v1/admin/orders/{order_id}/status")
async def change_order_status(order_id: int, status: OrderStatus, user: User = Depends(require_permission("orders.manage")), db: AsyncSession = Depends(db_session)):
    o = await db.get(Order, order_id)
    if not o: raise HTTPException(404, "order not found")
    old = o.status
    await add_order_event(db, o, old, status.value, user.id, "admin")
    await audit(db, user.id, "ORDER_STATUS", "ORDER", str(o.id), old={"status": old}, new={"status": status.value}); await db.commit(); return {"id": o.id, "status": o.status}

@app.post("/api/v1/admin/orders/{order_id}/mark-unknown")
async def mark_unknown(order_id: int, reason: str = Query(..., min_length=1), user: User = Depends(require_permission("orders.manage")), db: AsyncSession = Depends(db_session)):
    o = await db.get(Order, order_id)
    if not o: raise HTTPException(404, "order not found")
    await add_order_event(db, o, o.status, "UNKNOWN", user.id, "reconciliation", {"reason": reason}); o.external_outcome = "UNKNOWN"; await db.commit(); return {"id": o.id, "status": o.status, "external_outcome": o.external_outcome}

# ============================================================
# 16 — SUPPORT
# ============================================================
@app.post("/api/v1/support/tickets")
async def create_ticket(payload: TicketIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(db_session)):
    t = Ticket(user_id=user.id, subject=payload.subject, priority=payload.priority); db.add(t); await db.flush(); db.add(SupportMessage(ticket_id=t.id, sender_id=user.id, body=payload.body)); await db.commit(); return {"id": t.id, "status": t.status}

@app.get("/api/v1/support/tickets")
async def my_tickets(user: User = Depends(get_current_user), db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.id.desc()))).scalars().all(); return [{"id": t.id, "subject": t.subject, "priority": t.priority, "status": t.status, "assigned_to": t.assigned_to} for t in rows]

@app.get("/api/v1/admin/support/tickets")
async def admin_tickets(user: User = Depends(require_permission("support.read")), db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(Ticket).order_by(Ticket.id.desc()))).scalars().all(); return [{"id": t.id, "user_id": t.user_id, "subject": t.subject, "priority": t.priority, "status": t.status, "assigned_to": t.assigned_to} for t in rows]

@app.post("/api/v1/support/tickets/{ticket_id}/messages")
async def add_message(ticket_id: int, payload: MessageIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(db_session)):
    t = await db.get(Ticket, ticket_id)
    if not t or (t.user_id != user.id and user.role not in {Role.OWNER.value, Role.ADMIN.value, Role.SUPPORT.value}): raise HTTPException(404, "ticket not found")
    db.add(SupportMessage(ticket_id=t.id, sender_id=user.id, body=payload.body)); t.status = "IN_PROGRESS" if user.role != Role.CUSTOMER.value else "WAITING_USER"; await db.commit(); return {"ok": True}

# ============================================================
# 17 — USER / ADMIN CONTROL
# ============================================================
@app.get("/api/v1/admin/users")
async def admin_users(search: Optional[str] = None, role: Optional[str] = None, user: User = Depends(require_permission("users.read")), db: AsyncSession = Depends(db_session)):
    q = select(User).order_by(User.id.desc())
    if search:
        q = q.where(or_(User.username.ilike(f"%{search}%"), User.first_name.ilike(f"%{search}%")))
    if role: q = q.where(User.role == role.upper())
    rows = (await db.execute(q.limit(500))).scalars().all(); return [{"id": u.id, "telegram_id": u.telegram_id, "username": u.username, "first_name": u.first_name, "role": u.role, "status": u.status} for u in rows]

@app.put("/api/v1/admin/users/{user_id}/role")
async def set_user_role(user_id: int, payload: UserRoleIn, user: User = Depends(require_permission("admins.manage")), db: AsyncSession = Depends(db_session)):
    target = await db.get(User, user_id)
    if not target: raise HTTPException(404, "user not found")
    old = target.role; target.role = payload.role.value; await audit(db, user.id, "ROLE_CHANGE", "USER", str(target.id), old={"role": old}, new={"role": target.role}); await db.commit(); return {"id": target.id, "role": target.role}

@app.put("/api/v1/admin/users/{user_id}/status")
async def set_user_status(user_id: int, payload: UserStatusIn, user: User = Depends(require_permission("users.suspend")), db: AsyncSession = Depends(db_session)):
    target = await db.get(User, user_id)
    if not target: raise HTTPException(404, "user not found")
    old = target.status; target.status = payload.status.value; await audit(db, user.id, "USER_STATUS", "USER", str(target.id), old={"status": old}, new={"status": target.status}); await db.commit(); return {"id": target.id, "status": target.status}

# ============================================================
# 18 — NOTIFICATION OUTBOX
# ============================================================
async def enqueue_notification(db: AsyncSession, user_id: int, event: str, payload: dict):
    db.add(Notification(user_id=user_id, event=event, payload=payload, status="PENDING"))

@app.get("/api/v1/notifications")
async def notifications(user: User = Depends(get_current_user), db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(100))).scalars().all(); return [{"id": n.id, "event": n.event, "payload": n.payload, "status": n.status, "created_at": n.created_at.isoformat()} for n in rows]

# ============================================================
# 19 — ANALYTICS
# ============================================================
@app.get("/api/v1/admin/analytics")
async def analytics(user: User = Depends(require_permission("analytics.read")), db: AsyncSession = Depends(db_session)):
    users = (await db.execute(select(func.count(User.id)))).scalar_one()
    orders = (await db.execute(select(func.count(Order.id)))).scalar_one()
    completed = (await db.execute(select(func.count(Order.id)).where(Order.status == OrderStatus.COMPLETED.value))).scalar_one()
    revenue = (await db.execute(select(func.coalesce(func.sum(Order.total), 0)).where(Order.status.in_([OrderStatus.COMPLETED.value, OrderStatus.IN_PROGRESS.value, OrderStatus.PROCESSING.value])))).scalar_one()
    deposits = (await db.execute(select(func.coalesce(func.sum(Deposit.amount), 0)).where(Deposit.status == "APPROVED"))).scalar_one()
    return {"users": users, "orders": orders, "completed_orders": completed, "revenue": str(revenue), "approved_deposits": str(deposits)}

# ============================================================
# 20 — AUDIT / SETTINGS
# ============================================================
@app.get("/api/v1/admin/audit")
async def audit_logs(limit: int = Query(100, ge=1, le=500), user: User = Depends(require_permission("audit.read")), db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))).scalars().all(); return [{"id": a.id, "actor_id": a.actor_id, "action": a.action, "target_type": a.target_type, "target_id": a.target_id, "old_value": a.old_value, "new_value": a.new_value, "metadata": a.metadata_json, "created_at": a.created_at.isoformat()} for a in rows]

@app.get("/api/v1/admin/settings")
async def settings(user: User = Depends(require_permission("settings.read")), db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(select(Setting).order_by(Setting.key))).scalars().all(); return [{"key": s.key, "value": "********" if s.is_secret else s.value, "is_secret": s.is_secret} for s in rows]

# ============================================================
# 21 — PAYMENT ABSTRACTION / WEBHOOK SAFETY
# ============================================================
class PaymentProvider:
    async def create_payment(self, amount: Decimal, currency: str, reference: str) -> dict: raise NotImplementedError
    async def verify_payment(self, external_id: str) -> dict: raise NotImplementedError
    async def refund(self, external_id: str) -> dict: raise NotImplementedError

@app.post("/api/v1/admin/payments")
async def create_payment_record(amount: Decimal, currency: str, provider: str, idem: str, user_id: int, user: User = Depends(require_permission("payments.manage")), db: AsyncSession = Depends(db_session)):
    safe_currency(currency)
    existing = (await db.execute(select(Payment).where(Payment.idempotency_key == idem))).scalar_one_or_none()
    if existing: return {"id": existing.id, "status": existing.status, "idempotent": True}
    p = Payment(user_id=user_id, amount=money(amount), currency=currency.upper(), provider=provider, idempotency_key=idem); db.add(p); await db.flush(); await audit(db, user.id, "PAYMENT_CREATE", "PAYMENT", str(p.id)); await db.commit(); return {"id": p.id, "status": p.status}

@app.post("/api/v1/payments/webhook/{provider}")
async def payment_webhook(provider: str, request: Request, db: AsyncSession = Depends(db_session)):
    # Provider-specific signature verification must be configured before enabling real money.
    body = await request.json()
    external_id = str(body.get("external_id", ""))
    status = str(body.get("status", "")).upper()
    if not external_id: raise HTTPException(400, "missing external_id")
    p = (await db.execute(select(Payment).where(Payment.external_id == external_id))).scalar_one_or_none()
    if not p: raise HTTPException(404, "payment not found")
    if p.status in {"SUCCESS", "FAILED"}: return {"ok": True, "idempotent": True}
    if status not in {"SUCCESS", "FAILED"}: raise HTTPException(422, "invalid payment status")
    p.status = status; await db.commit(); return {"ok": True}

# ============================================================
# 22 — PROVIDER ORDER SUBMISSION / UNKNOWN OUTCOME
# ============================================================
@app.post("/api/v1/admin/orders/{order_id}/submit-provider")
async def submit_provider(order_id: int, user: User = Depends(require_permission("orders.manage")), db: AsyncSession = Depends(db_session)):
    o = await db.get(Order, order_id)
    if not o: raise HTTPException(404, "order not found")
    if o.external_order_id: return {"id": o.id, "status": o.status, "external_order_id": o.external_order_id, "idempotent": True}
    provider, mapping = await choose_provider(db, o.service_id, "create_order")
    adapter = ProviderAdapter(provider)
    try:
        response = await adapter.create_order(mapping.external_service_id, o.quantity, o.requirements)
        if response.status_code >= 500:
            o.external_outcome = "UNKNOWN"; await add_order_event(db, o, o.status, "UNKNOWN", user.id, "provider", {"http_status": response.status_code}); await db.commit(); raise HTTPException(503, "provider outcome is unknown; reconciliation required")
        if response.status_code >= 400:
            provider.failure_count += 1; await add_order_event(db, o, o.status, "FAILED", user.id, "provider", {"http_status": response.status_code}); await db.commit(); raise HTTPException(502, "provider rejected order")
        data = response.json()
        external_id = str(data.get("order_id") or data.get("id") or "")
        if not external_id:
            o.external_outcome = "UNKNOWN"; await add_order_event(db, o, o.status, "UNKNOWN", user.id, "provider", {"reason": "missing external id"}); await db.commit(); raise HTTPException(502, "provider response has no external order id")
        o.external_order_id = external_id; o.external_outcome = "CONFIRMED"; provider.health = "UP"; provider.failure_count = 0
        await add_order_event(db, o, o.status, "IN_PROGRESS", user.id, "provider", {"provider_id": provider.id})
        await db.commit(); return {"id": o.id, "status": o.status, "external_order_id": external_id}
    except HTTPException: raise
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        o.external_outcome = "UNKNOWN"; await add_order_event(db, o, o.status, "UNKNOWN", user.id, "provider", {"error": type(exc).__name__}); await db.commit(); raise HTTPException(503, "provider outcome is unknown; do not retry blindly")
    except Exception as exc:
        o.external_outcome = "UNKNOWN"; await add_order_event(db, o, o.status, "UNKNOWN", user.id, "provider", {"error": type(exc).__name__}); await db.commit(); raise HTTPException(503, "provider outcome is unknown")

@app.post("/api/v1/admin/orders/{order_id}/reconcile")
async def reconcile_order(order_id: int, user: User = Depends(require_permission("orders.manage")), db: AsyncSession = Depends(db_session)):
    o = await db.get(Order, order_id)
    if not o: raise HTTPException(404, "order not found")
    if not o.external_order_id: raise HTTPException(409, "no external order id to reconcile")
    provider, _ = await choose_provider(db, o.service_id, "status")
    try:
        response = await ProviderAdapter(provider).get_order_status(o.external_order_id)
        if response.status_code >= 400: raise HTTPException(502, "provider status lookup failed")
        data = response.json(); remote = str(data.get("status", "")).upper()
        mapping = {"PENDING": "PROCESSING", "PROCESSING": "IN_PROGRESS", "IN_PROGRESS": "IN_PROGRESS", "COMPLETED": "COMPLETED", "PARTIAL": "PARTIAL", "CANCELED": "CANCELED", "CANCELLED": "CANCELED", "FAILED": "FAILED"}
        target = mapping.get(remote)
        if not target: return {"id": o.id, "status": o.status, "reconciliation": "UNRESOLVED", "provider_status": remote}
        await add_order_event(db, o, o.status, target, user.id, "reconciliation", {"provider_status": remote}); o.external_outcome = "CONFIRMED"; await db.commit(); return {"id": o.id, "status": o.status, "provider_status": remote}
    except HTTPException: raise
    except Exception as exc:
        raise HTTPException(503, f"reconciliation failed: {type(exc).__name__}") from exc

# ============================================================
# 23 — CUSTOMER / ADMIN DASHBOARD UI (EMBEDDED)
# ============================================================
UI_HTML = """<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>DHĀT STORE — AIMEN</title><style>body{font-family:Arial,sans-serif;background:#0b1020;color:#eee;margin:0}.wrap{max-width:1100px;margin:auto;padding:28px}.card{background:#151d35;border:1px solid #293556;border-radius:16px;padding:20px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}h1{margin-top:0}.muted{color:#9aa6c0}code{background:#0a0f1d;padding:3px 6px;border-radius:6px}</style></head><body><div class='wrap'><h1>DHĀT STORE — AIMEN</h1><p class='muted'>Unified Store Control Center</p><div class='grid'><div class='card'><b>Customer API</b><p>/api/v1/catalog/services</p></div><div class='card'><b>Admin API</b><p>/api/v1/admin/*</p></div><div class='card'><b>Provider API</b><p>Mappings + routing + reconciliation</p></div><div class='card'><b>Finance</b><p>Wallets + deposits + ledger</p></div></div><div class='card'><h2>الحالة</h2><p>النظام يعمل كخدمة FastAPI موحدة. استخدم <code>/docs</code> لإدارة واختبار جميع واجهات API.</p></div></div></body></html>"""

@app.get("/", response_class=HTMLResponse)
async def home(): return UI_HTML

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(): return UI_HTML

@app.get("/store", response_class=HTMLResponse)
async def store_panel(): return UI_HTML

# ============================================================
# 24 — TELEGRAM BOT / WEBHOOK BOUNDARY
# ============================================================
async def telegram_api(method: str, payload: dict):
    if not TELEGRAM_BOT_TOKEN: raise RuntimeError("Telegram bot token not configured")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status(); return response.json()

@app.post("/api/v1/telegram/webhook")
async def telegram_webhook(request: Request):
    update = await request.json()
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = message.get("text", "")
    if chat_id and text == "/start" and TELEGRAM_BOT_TOKEN:
        try: await telegram_api("sendMessage", {"chat_id": chat_id, "text": "أهلاً بك في DHĀT STORE 👋\nافتح المتجر من زر التطبيق أو استخدم لوحة الحساب."})
        except Exception as exc: log.warning("Telegram notification failed: %s", exc)
    return {"ok": True}

# ============================================================
# 25 — STARTUP / SAFE SCHEMA INITIALIZATION
# ============================================================
@app.on_event("startup")
async def startup():
    # Single-file edition intentionally owns its schema. For PostgreSQL production,
    # take a database backup before schema upgrades and pin the application version.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionFactory() as db:
        for role, permissions in ROLE_PERMISSIONS.items():
            for permission in permissions:
                exists = await db.execute(select(RolePermission).where(RolePermission.role == role, RolePermission.permission == permission))
                if not exists.scalar_one_or_none(): db.add(RolePermission(role=role, permission=permission))
        await db.commit()
    log.info("AIMEN STORE started")

@app.on_event("shutdown")
async def shutdown():
    await engine.dispose()

# ============================================================
# 26 — SINGLE FILE ENTRYPOINT
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("aimen:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
