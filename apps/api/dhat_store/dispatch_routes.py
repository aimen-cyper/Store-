import hashlib,json
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,HTTPException,Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_db
from .models import Order,ProviderMapping,Provider,ExternalOrder,OrderEvent,Session,User
from .providers import provider_config,HttpProvider
from .core import ProviderTimeout,transition_allowed
router=APIRouter(prefix='/api/v1/orders',tags=['orders'])
async def user_dep(authorization:str|None=Header(default=None),db:AsyncSession=Depends(get_db)):
    if not authorization or not authorization.startswith('Bearer '):raise HTTPException(401,'Authentication required')
    s=(await db.execute(select(Session).where(Session.token_hash==hashlib.sha256(authorization[7:].encode()).hexdigest(),Session.revoked_at.is_(None),Session.expires_at>datetime.now(timezone.utc)))).scalar_one_or_none();u=await db.get(User,s.user_id) if s else None
    if not u or u.status!='ACTIVE':raise HTTPException(403,'Account unavailable')
    return u
@router.post('/{order_id}/dispatch')
async def dispatch(order_id:int,db:AsyncSession=Depends(get_db),u:User=Depends(user_dep)):
    o=(await db.execute(select(Order).where(Order.id==order_id).with_for_update())).scalar_one_or_none()
    if not o or o.user_id!=u.id:raise HTTPException(404,'Order not found')
    existing=(await db.execute(select(ExternalOrder).where(ExternalOrder.order_id==o.id))).scalar_one_or_none()
    if existing:
        return {'order_id':o.id,'status':o.status,'external_id':existing.external_id,'outcome':existing.outcome}
    mappings=(await db.execute(select(ProviderMapping).where(ProviderMapping.service_id==o.service_id,ProviderMapping.enabled.is_(True)).order_by(ProviderMapping.priority))).scalars().all()
    if not mappings:raise HTTPException(409,'No provider mapping configured')
    for m in mappings:
        p=await db.get(Provider,m.provider_id)
        if not p or not p.enabled or p.health_state=='DOWN':continue
        url,key=provider_config(p.name)
        if not url or not key:continue
        fp=hashlib.sha256(f'{o.id}:{p.id}:{m.external_service_id}:{o.quantity}'.encode()).hexdigest()
        ex=ExternalOrder(order_id=o.id,provider_id=p.id,outcome='PENDING',request_fingerprint=fp);db.add(ex);await db.flush()
        try:
            data=await HttpProvider(url,key,p.timeout_seconds).create_order(m.external_service_id,o.quantity,{})
        except ProviderTimeout:
            ex.outcome='UNKNOWN';o.status='UNKNOWN';db.add(OrderEvent(order_id=o.id,old_status='PROCESSING',new_status='UNKNOWN',actor_id=u.id,source='PROVIDER',metadata_json='{"reason":"timeout"}'));await db.commit();return {'order_id':o.id,'status':'UNKNOWN','outcome':'UNKNOWN','requires_reconciliation':True}
        except Exception as e:
            await db.rollback();continue
        ext=str(data.get('id') or data.get('order_id') or '') or None
        if not ext:
            await db.rollback();continue
        ex.external_id=ext;ex.outcome='CONFIRMED';o.status='IN_PROGRESS';db.add(OrderEvent(order_id=o.id,old_status='PROCESSING',new_status='IN_PROGRESS',actor_id=u.id,source='PROVIDER',metadata_json=json.dumps({'provider_id':p.id})));await db.commit();return {'order_id':o.id,'status':o.status,'external_id':ext}
    raise HTTPException(503,'No healthy configured provider available')
