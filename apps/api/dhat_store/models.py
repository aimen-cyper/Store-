from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    telegram_id: Mapped[int|None]=mapped_column(BigInteger,unique=True)
    username: Mapped[str|None]=mapped_column(String(128))
    role: Mapped[str]=mapped_column(String(32),default='CUSTOMER')
    status: Mapped[str]=mapped_column(String(32),default='ACTIVE')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Session(Base):
    __tablename__='sessions'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'))
    token_hash: Mapped[str]=mapped_column(String(64),unique=True,index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Role(Base):
    __tablename__='roles'; id: Mapped[int]=mapped_column(primary_key=True); name: Mapped[str]=mapped_column(String(32),unique=True)
class Permission(Base):
    __tablename__='permissions'; id: Mapped[int]=mapped_column(primary_key=True); code: Mapped[str]=mapped_column(String(100),unique=True)
class UserRole(Base):
    __tablename__='user_roles'; user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),primary_key=True); role_id: Mapped[int]=mapped_column(ForeignKey('roles.id',ondelete='CASCADE'),primary_key=True)
class RolePermission(Base):
    __tablename__='role_permissions'; role_id: Mapped[int]=mapped_column(ForeignKey('roles.id',ondelete='CASCADE'),primary_key=True); permission_id: Mapped[int]=mapped_column(ForeignKey('permissions.id',ondelete='CASCADE'),primary_key=True)

class Category(Base):
    __tablename__='categories'
    id: Mapped[int]=mapped_column(primary_key=True); name: Mapped[str]=mapped_column(String(160),unique=True); slug: Mapped[str]=mapped_column(String(160),unique=True); enabled: Mapped[bool]=mapped_column(Boolean,default=True)
class Product(Base):
    __tablename__='products'
    id: Mapped[int]=mapped_column(primary_key=True); category_id: Mapped[int]=mapped_column(ForeignKey('categories.id')); name: Mapped[str]=mapped_column(String(200)); slug: Mapped[str]=mapped_column(String(200),unique=True); description: Mapped[str]=mapped_column(Text,default=''); enabled: Mapped[bool]=mapped_column(Boolean,default=True); sort_order: Mapped[int]=mapped_column(Integer,default=0)
class Service(Base):
    __tablename__='services'
    id: Mapped[int]=mapped_column(primary_key=True); category_id: Mapped[int]=mapped_column(ForeignKey('categories.id')); name: Mapped[str]=mapped_column(String(200)); description: Mapped[str]=mapped_column(Text,default=''); price: Mapped[Decimal]=mapped_column(Numeric(18,4)); currency: Mapped[str]=mapped_column(String(3)); stock: Mapped[int]=mapped_column(Integer,default=0); enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    __table_args__=(CheckConstraint('price >= 0'),CheckConstraint('stock >= 0'))
class PricingRule(Base):
    __tablename__='pricing_rules'
    id: Mapped[int]=mapped_column(primary_key=True); service_id: Mapped[int|None]=mapped_column(ForeignKey('services.id',ondelete='CASCADE')); category_id: Mapped[int|None]=mapped_column(ForeignKey('categories.id',ondelete='CASCADE')); provider_id: Mapped[int|None]=mapped_column(ForeignKey('providers.id')); kind: Mapped[str]=mapped_column(String(32)); value: Mapped[Decimal]=mapped_column(Numeric(20,8)); currency: Mapped[str|None]=mapped_column(String(3)); priority: Mapped[int]=mapped_column(Integer,default=0); enabled: Mapped[bool]=mapped_column(Boolean,default=True)

class Provider(Base):
    __tablename__='providers'
    id: Mapped[int]=mapped_column(primary_key=True); name: Mapped[str]=mapped_column(String(120),unique=True); enabled: Mapped[bool]=mapped_column(Boolean,default=True); priority: Mapped[int]=mapped_column(Integer,default=100); timeout_seconds: Mapped[int]=mapped_column(Integer,default=15); health_state: Mapped[str]=mapped_column(String(32),default='UNKNOWN'); config_key: Mapped[str|None]=mapped_column(String(200))
class ProviderMapping(Base):
    __tablename__='provider_mappings'
    id: Mapped[int]=mapped_column(primary_key=True); service_id: Mapped[int]=mapped_column(ForeignKey('services.id',ondelete='CASCADE')); provider_id: Mapped[int]=mapped_column(ForeignKey('providers.id',ondelete='CASCADE')); external_service_id: Mapped[str]=mapped_column(String(128)); priority: Mapped[int]=mapped_column(Integer,default=100); enabled: Mapped[bool]=mapped_column(Boolean,default=True)
class ProviderHealth(Base):
    __tablename__='provider_health'
    id: Mapped[int]=mapped_column(primary_key=True); provider_id: Mapped[int]=mapped_column(ForeignKey('providers.id',ondelete='CASCADE')); success_count: Mapped[int]=mapped_column(Integer,default=0); failure_count: Mapped[int]=mapped_column(Integer,default=0); consecutive_failures: Mapped[int]=mapped_column(Integer,default=0); last_error: Mapped[str|None]=mapped_column(Text); checked_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class Wallet(Base):
    __tablename__='wallets'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE')); currency: Mapped[str]=mapped_column(String(3)); balance: Mapped[Decimal]=mapped_column(Numeric(20,4),default=0)
    __table_args__=(UniqueConstraint('user_id','currency'),CheckConstraint('balance >= 0'))
class Ledger(Base):
    __tablename__='wallet_transactions'
    id: Mapped[int]=mapped_column(primary_key=True); wallet_id: Mapped[int]=mapped_column(ForeignKey('wallets.id')); amount: Mapped[Decimal]=mapped_column(Numeric(20,4)); type: Mapped[str]=mapped_column(String(32)); idempotency_key: Mapped[str]=mapped_column(String(128),unique=True); reference: Mapped[str|None]=mapped_column(String(128)); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Deposit(Base):
    __tablename__='deposit_requests'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id')); amount: Mapped[Decimal]=mapped_column(Numeric(20,4)); currency: Mapped[str]=mapped_column(String(3)); reference: Mapped[str]=mapped_column(String(160)); status: Mapped[str]=mapped_column(String(32),default='PENDING'); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Order(Base):
    __tablename__='orders'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id')); service_id: Mapped[int]=mapped_column(ForeignKey('services.id')); quantity: Mapped[int]=mapped_column(Integer); total: Mapped[Decimal]=mapped_column(Numeric(20,4)); currency: Mapped[str]=mapped_column(String(3)); status: Mapped[str]=mapped_column(String(32),default='PENDING'); idempotency_key: Mapped[str]=mapped_column(String(128),unique=True); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(CheckConstraint('quantity > 0'),CheckConstraint('total >= 0'))
class OrderEvent(Base):
    __tablename__='order_events'
    id: Mapped[int]=mapped_column(primary_key=True); order_id: Mapped[int]=mapped_column(ForeignKey('orders.id',ondelete='CASCADE')); old_status: Mapped[str|None]=mapped_column(String(32)); new_status: Mapped[str]=mapped_column(String(32)); actor_id: Mapped[int|None]=mapped_column(ForeignKey('users.id')); source: Mapped[str]=mapped_column(String(32)); metadata_json: Mapped[str]=mapped_column(Text,default='{}'); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class ExternalOrder(Base):
    __tablename__='external_orders'
    id: Mapped[int]=mapped_column(primary_key=True); order_id: Mapped[int]=mapped_column(ForeignKey('orders.id',ondelete='CASCADE'),unique=True); provider_id: Mapped[int]=mapped_column(ForeignKey('providers.id')); external_id: Mapped[str|None]=mapped_column(String(160)); outcome: Mapped[str]=mapped_column(String(32)); request_fingerprint: Mapped[str]=mapped_column(String(128),unique=True); last_checked_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class Payment(Base):
    __tablename__='payments'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id')); provider: Mapped[str]=mapped_column(String(80)); external_id: Mapped[str|None]=mapped_column(String(160),unique=True); amount: Mapped[Decimal]=mapped_column(Numeric(20,4)); currency: Mapped[str]=mapped_column(String(3)); status: Mapped[str]=mapped_column(String(32)); idempotency_key: Mapped[str]=mapped_column(String(128),unique=True); metadata_json: Mapped[str]=mapped_column(Text,default='{}')
class Coupon(Base):
    __tablename__='coupons'
    id: Mapped[int]=mapped_column(primary_key=True); code: Mapped[str]=mapped_column(String(64),unique=True); kind: Mapped[str]=mapped_column(String(16)); value: Mapped[Decimal]=mapped_column(Numeric(20,4)); min_order: Mapped[Decimal|None]=mapped_column(Numeric(20,4)); max_discount: Mapped[Decimal|None]=mapped_column(Numeric(20,4)); expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); usage_limit: Mapped[int|None]=mapped_column(Integer); per_user_limit: Mapped[int]=mapped_column(Integer,default=1); active: Mapped[bool]=mapped_column(Boolean,default=True)
class CouponRedemption(Base):
    __tablename__='coupon_redemptions'
    id: Mapped[int]=mapped_column(primary_key=True); coupon_id: Mapped[int]=mapped_column(ForeignKey('coupons.id',ondelete='CASCADE')); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE')); order_id: Mapped[int|None]=mapped_column(ForeignKey('orders.id')); discount: Mapped[Decimal]=mapped_column(Numeric(20,4)); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Notification(Base):
    __tablename__='notifications'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE')); event: Mapped[str]=mapped_column(String(64)); payload_json: Mapped[str]=mapped_column(Text,default='{}'); status: Mapped[str]=mapped_column(String(32),default='PENDING'); attempts: Mapped[int]=mapped_column(Integer,default=0); available_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now); sent_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class SupportTicket(Base):
    __tablename__='support_tickets'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id')); assigned_to: Mapped[int|None]=mapped_column(ForeignKey('users.id')); subject: Mapped[str]=mapped_column(String(200)); priority: Mapped[str]=mapped_column(String(16),default='NORMAL'); status: Mapped[str]=mapped_column(String(32),default='OPEN'); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
class SupportMessage(Base):
    __tablename__='support_messages'
    id: Mapped[int]=mapped_column(primary_key=True); ticket_id: Mapped[int]=mapped_column(ForeignKey('support_tickets.id',ondelete='CASCADE')); sender_id: Mapped[int]=mapped_column(ForeignKey('users.id')); body: Mapped[str]=mapped_column(Text); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Setting(Base):
    __tablename__='settings'
    key: Mapped[str]=mapped_column(String(120),primary_key=True); value_json: Mapped[str]=mapped_column(Text,default='{}'); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
class AuditLog(Base):
    __tablename__='audit_logs'
    id: Mapped[int]=mapped_column(primary_key=True); actor_id: Mapped[int|None]=mapped_column(ForeignKey('users.id')); action: Mapped[str]=mapped_column(String(128)); target: Mapped[str]=mapped_column(String(128)); metadata_json: Mapped[str]=mapped_column(Text,default='{}'); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
