from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def now(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    telegram_id: Mapped[int|None]=mapped_column(unique=True)
    username: Mapped[str|None]=mapped_column(String(128))
    role: Mapped[str]=mapped_column(String(32), default='CUSTOMER')
    status: Mapped[str]=mapped_column(String(32), default='ACTIVE')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Session(Base):
    __tablename__='sessions'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'))
    token_hash: Mapped[str]=mapped_column(String(64),unique=True,index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Category(Base):
    __tablename__='categories'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(160),unique=True)
    slug: Mapped[str]=mapped_column(String(160),unique=True)
    enabled: Mapped[bool]=mapped_column(Boolean,default=True)

class Service(Base):
    __tablename__='services'
    id: Mapped[int]=mapped_column(primary_key=True)
    category_id: Mapped[int]=mapped_column(ForeignKey('categories.id'))
    name: Mapped[str]=mapped_column(String(200))
    description: Mapped[str]=mapped_column(Text,default='')
    price: Mapped[Decimal]=mapped_column(Numeric(18,4))
    currency: Mapped[str]=mapped_column(String(3))
    stock: Mapped[int]=mapped_column(Integer,default=0)
    enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    __table_args__=(CheckConstraint('price >= 0'),CheckConstraint('stock >= 0'))

class Wallet(Base):
    __tablename__='wallets'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'))
    currency: Mapped[str]=mapped_column(String(3))
    balance: Mapped[Decimal]=mapped_column(Numeric(20,4),default=0)
    __table_args__=(UniqueConstraint('user_id','currency'),CheckConstraint('balance >= 0'))

class Ledger(Base):
    __tablename__='wallet_transactions'
    id: Mapped[int]=mapped_column(primary_key=True)
    wallet_id: Mapped[int]=mapped_column(ForeignKey('wallets.id'))
    amount: Mapped[Decimal]=mapped_column(Numeric(20,4))
    type: Mapped[str]=mapped_column(String(32))
    idempotency_key: Mapped[str]=mapped_column(String(128),unique=True)
    reference: Mapped[str|None]=mapped_column(String(128))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Deposit(Base):
    __tablename__='deposit_requests'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    amount: Mapped[Decimal]=mapped_column(Numeric(20,4))
    currency: Mapped[str]=mapped_column(String(3))
    reference: Mapped[str]=mapped_column(String(160))
    status: Mapped[str]=mapped_column(String(32),default='PENDING')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Order(Base):
    __tablename__='orders'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    service_id: Mapped[int]=mapped_column(ForeignKey('services.id'))
    quantity: Mapped[int]=mapped_column(Integer)
    total: Mapped[Decimal]=mapped_column(Numeric(20,4))
    currency: Mapped[str]=mapped_column(String(3))
    status: Mapped[str]=mapped_column(String(32),default='PENDING')
    idempotency_key: Mapped[str]=mapped_column(String(128),unique=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(CheckConstraint('quantity > 0'),CheckConstraint('total >= 0'))

class AuditLog(Base):
    __tablename__='audit_logs'
    id: Mapped[int]=mapped_column(primary_key=True)
    actor_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'))
    action: Mapped[str]=mapped_column(String(128))
    target: Mapped[str]=mapped_column(String(128))
    metadata_json: Mapped[str]=mapped_column(Text,default='{}')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
