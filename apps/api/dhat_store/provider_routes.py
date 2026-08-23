import hashlib,json
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_db
from .models import Provider,ProviderMapping,ProviderHealth,Service,ExternalOrder,Order,OrderEvent,User
from .main import current_user,require_roles
from .providers import provider_config,HttpProvider
from .core import ProviderTimeout,transition_allowed
router=APIRouter(prefix='/api/v1/admin/providers',tags=['providers'])
@router.get('')
async def list_providers(db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN'))):
    return [{'id':p.id,'name':p.name,'enabled':p.enabled,'priority':p.priority,'health_state':p.health_state} for p in (await db.execute(select(Provider).order_by(Provider.priority))).scalars()]
@router.post('')
async def create_provider(p:dict,db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN'))):
    x=Provider(name=p['name'],priority=int(p.get('priority',100)),timeout_seconds=int(p.get('timeout_seconds',15)),enabled=bool(p.get('enabled',True)),health_state='UNKNOWN',config_key=p.get('config_key'));db.add(x);await db.flush();db.add(ProviderHealth(provider_id=x.id,success_count=0,failure_count=0,consecutive_failures=0));await db.commit();return {'id':x.id}
@router.post('/mappings')
async def mapping(p:dict,db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN'))):
    if not await db.get(Service,int(p['service_id'])):raise HTTPException(404,'Service not found')
    if not await db.get(Provider,int(p['provider_id'])):raise HTTPException(404,'Provider not found')
    x=ProviderMapping(service_id=int(p['service_id']),provider_id=int(p['provider_id']),external_service_id=str(p['external_service_id']),priority=int(p.get('priority',100)),enabled=bool(p.get('enabled',True)));db.add(x);await db.commit();return {'id':x.id}
@router.post('/orders/{order_id}/reconcile')
async def reconcile(order_id:int,db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN','FINANCE'))):
    o=await db.get(Order,order_id);ex=(await db.execute(select(ExternalOrder).where(ExternalOrder.order_id==order_id))).scalar_one_or_none()
    if not o or not ex:raise HTTPException(404,'External order not found')
    p=await db.get(Provider,ex.provider_id);url,key=provider_config(p.name)
    if not url or not key:raise HTTPException(503,'Provider credentials not configured')
    if not ex.external_id:raise HTTPException(409,'External outcome unresolved: no external id')
    adapter=HttpProvider(url,key,p.timeout_seconds)
    try: data=await adapter.get_order_status(ex.external_id)
    except Exception as e: ex.last_checked_at=datetime.now(timezone.utc);await db.commit();raise HTTPException(502,f'Provider reconciliation failed: {e}')
    status=str(data.get('status','')).upper();mapping={'COMPLETED':'COMPLETED','PARTIAL':'PARTIAL','CANCELED':'CANCELED','CANCELLED':'CANCELED','FAILED':'FAILED','IN_PROGRESS':'IN_PROGRESS','PROCESSING':'PROCESSING'};new=mapping.get(status)
    if not new:return {'status':'UNKNOWN','provider_response':data}
    if not transition_allowed(o.status,new):return {'status':o.status,'provider_status':new,'ignored':True}
    old=o.status;o.status=new;ex.outcome='RESOLVED';ex.last_checked_at=datetime.now(timezone.utc);db.add(OrderEvent(order_id=o.id,old_status=old,new_status=new,actor_id=u.id,source='RECONCILIATION',metadata_json=json.dumps({'provider_status':status})));await db.commit();return {'order_id':o.id,'status':new}
