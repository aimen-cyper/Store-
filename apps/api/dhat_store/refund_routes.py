import hashlib
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,HTTPException,Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_db
from .models import Order,Wallet,Ledger,OrderEvent,Session,User
from .core import transition_allowed
router=APIRouter(prefix='/api/v1/admin/orders',tags=['refunds'])
async def finance_user(authorization:str|None=Header(default=None),db:AsyncSession=Depends(get_db)):
    if not authorization or not authorization.startswith('Bearer '):raise HTTPException(401,'Authentication required')
    s=(await db.execute(select(Session).where(Session.token_hash==hashlib.sha256(authorization[7:].encode()).hexdigest(),Session.revoked_at.is_(None),Session.expires_at>datetime.now(timezone.utc)))).scalar_one_or_none();u=await db.get(User,s.user_id) if s else None
    if not u or u.status!='ACTIVE' or u.role not in {'OWNER','ADMIN','FINANCE'}:raise HTTPException(403,'Permission denied')
    return u
@router.post('/{order_id}/refund')
async def refund(order_id:int,db:AsyncSession=Depends(get_db),u:User=Depends(finance_user)):
    o=(await db.execute(select(Order).where(Order.id==order_id).with_for_update())).scalar_one_or_none()
    if not o:raise HTTPException(404,'Order not found')
    existing=(await db.execute(select(Ledger).where(Ledger.idempotency_key==f'refund:{o.id}'))).scalar_one_or_none()
    if existing:return {'order_id':o.id,'status':'REFUNDED','idempotent':True}
    if o.status not in {'COMPLETED','PARTIAL','FAILED','CANCELED'}:raise HTTPException(409,'Order is not refundable in current state')
    w=(await db.execute(select(Wallet).where(Wallet.user_id==o.user_id,Wallet.currency==o.currency).with_for_update())).scalar_one_or_none()
    if not w:w=Wallet(user_id=o.user_id,currency=o.currency,balance=0);db.add(w);await db.flush()
    w.balance+=o.total;db.add(Ledger(wallet_id=w.id,amount=o.total,type='REFUND',idempotency_key=f'refund:{o.id}',reference=str(o.id)));old=o.status;o.status='REFUNDED';db.add(OrderEvent(order_id=o.id,old_status=old,new_status='REFUNDED',actor_id=u.id,source='FINANCE',metadata_json='{}'));await db.commit();return {'order_id':o.id,'status':'REFUNDED','amount':str(o.total),'currency':o.currency}
