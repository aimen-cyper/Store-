import hashlib, json
from datetime import datetime, timezone
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .config import settings
from .db import get_db
from .models import User, Session, AuditLog, Notification

ROLE_PERMISSIONS = {
    'OWNER': {'*'},
    'ADMIN': {'users.read','users.update','users.suspend','orders.read','orders.manage','orders.refund','wallet.read','wallet.adjust','payments.read','payments.manage','providers.read','providers.manage','services.read','services.manage','pricing.read','pricing.manage','coupons.read','coupons.manage','support.read','support.manage','analytics.read','audit.read','admins.manage','settings.read','settings.manage'},
    'FINANCE': {'users.read','orders.read','wallet.read','wallet.adjust','payments.read','payments.manage','coupons.read','analytics.read','audit.read'},
    'SUPPORT': {'users.read','orders.read','support.read','support.manage'},
    'MODERATOR': {'users.read','orders.read','services.read','support.read','support.manage'},
    'CUSTOMER': set(),
}

async def current_user(authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Authentication required')
    raw=authorization[7:]
    h=hashlib.sha256(raw.encode()).hexdigest()
    s=(await db.execute(select(Session).where(Session.token_hash==h,Session.revoked_at.is_(None),Session.expires_at>datetime.now(timezone.utc)))).scalar_one_or_none()
    if not s: raise HTTPException(401,'Invalid session')
    u=await db.get(User,s.user_id)
    if not u or u.status!='ACTIVE': raise HTTPException(403,'Account unavailable')
    s.last_used_at=datetime.now(timezone.utc)
    return u

def permission(code: str):
    async def guard(u: User = Depends(current_user)):
        if code not in ROLE_PERMISSIONS.get(u.role,set()) and '*' not in ROLE_PERMISSIONS.get(u.role,set()): raise HTTPException(403,'Permission denied')
        return u
    return guard

def require_roles(*roles):
    async def guard(u: User = Depends(current_user)):
        if u.role not in roles: raise HTTPException(403,'Permission denied')
        return u
    return guard

async def audit(db, actor, action, target, metadata=None):
    db.add(AuditLog(actor_id=actor.id if actor else None,action=action,target=str(target),metadata_json=json.dumps(metadata or {},default=str)))

async def notify(db,user_id,event,payload):
    db.add(Notification(user_id=user_id,event=event,payload_json=json.dumps(payload,default=str),status='PENDING',attempts=0,available_at=datetime.now(timezone.utc)))
