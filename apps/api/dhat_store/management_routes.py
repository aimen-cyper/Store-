import json
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_db
from .models import *
from .dependencies import current_user, permission, audit, notify, ROLE_PERMISSIONS

router=APIRouter(prefix='/api/v1')

class CategoryPatch(BaseModel):
    name:str|None=Field(default=None,min_length=1,max_length=160); slug:str|None=Field(default=None,min_length=1,max_length=160); enabled:bool|None=None
class ServicePatch(BaseModel):
    name:str|None=Field(default=None,min_length=1,max_length=200); description:str|None=None; price:Decimal|None=Field(default=None,ge=0); currency:str|None=None; stock:int|None=Field(default=None,ge=0); enabled:bool|None=None
class ProductIn(BaseModel):
    category_id:int; name:str=Field(min_length=1,max_length=200); slug:str=Field(min_length=1,max_length=200); description:str=''; sort_order:int=0
class StatusIn(BaseModel): status:str=Field(pattern='^(ACTIVE|BLOCKED|SUSPENDED)$')
class RoleIn(BaseModel): role:str=Field(pattern='^(OWNER|ADMIN|FINANCE|SUPPORT|MODERATOR|CUSTOMER)$')
class TicketPatch(BaseModel):
    status:str|None=Field(default=None,pattern='^(OPEN|IN_PROGRESS|WAITING_USER|RESOLVED|CLOSED)$'); priority:str|None=Field(default=None,pattern='^(LOW|NORMAL|HIGH|URGENT)$'); assigned_to:int|None=None
class MessageIn(BaseModel): body:str=Field(min_length=1,max_length=5000)
class PaymentMethodIn(BaseModel): name:str=Field(min_length=1,max_length=80); currency:str=Field(min_length=3,max_length=3); account:str=Field(min_length=1,max_length=200); enabled:bool=True

@router.get('/admin/categories',dependencies=[Depends(permission('services.read'))])
async def admin_categories(db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(select(Category).order_by(Category.id))).scalars(); return [{'id':x.id,'name':x.name,'slug':x.slug,'enabled':x.enabled} for x in rows]

@router.patch('/admin/categories/{id}',dependencies=[Depends(permission('services.manage'))])
async def patch_category(id:int,p:CategoryPatch,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    x=await db.get(Category,id)
    if not x: raise HTTPException(404,'Category not found')
    old={'name':x.name,'slug':x.slug,'enabled':x.enabled}; data=p.model_dump(exclude_unset=True)
    for k,v in data.items(): setattr(x,k,v)
    await audit(db,u,'category.update',id,{'old':old,'new':data}); await db.commit(); return {'id':id}

@router.delete('/admin/categories/{id}',dependencies=[Depends(permission('services.manage'))])
async def archive_category(id:int,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    x=await db.get(Category,id)
    if not x: raise HTTPException(404,'Category not found')
    x.enabled=False; await audit(db,u,'category.archive',id); await db.commit(); return {'ok':True}

@router.post('/admin/products',dependencies=[Depends(permission('services.manage'))])
async def create_product(p:ProductIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    if not await db.get(Category,p.category_id): raise HTTPException(404,'Category not found')
    x=Product(**p.model_dump(),enabled=True); db.add(x); await db.flush(); await audit(db,u,'product.create',x.id,p.model_dump()); await db.commit(); return {'id':x.id}

@router.patch('/admin/services/{id}',dependencies=[Depends(permission('services.manage'))])
async def patch_service(id:int,p:ServicePatch,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    x=await db.get(Service,id)
    if not x: raise HTTPException(404,'Service not found')
    data=p.model_dump(exclude_unset=True)
    for k,v in data.items(): setattr(x,k,v)
    await audit(db,u,'service.update',id,data); await db.commit(); return {'id':id}

@router.delete('/admin/services/{id}',dependencies=[Depends(permission('services.manage'))])
async def archive_service(id:int,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    x=await db.get(Service,id)
    if not x: raise HTTPException(404,'Service not found')
    x.enabled=False; await audit(db,u,'service.archive',id); await db.commit(); return {'ok':True}

@router.get('/admin/users',dependencies=[Depends(permission('users.read'))])
async def admin_users(limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(select(User).order_by(User.id.desc()).offset(offset).limit(limit))).scalars(); return [{'id':x.id,'telegram_id':x.telegram_id,'username':x.username,'role':x.role,'status':x.status} for x in rows]

@router.patch('/admin/users/{id}/status',dependencies=[Depends(permission('users.suspend'))])
async def user_status(id:int,p:StatusIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    x=await db.get(User,id)
    if not x: raise HTTPException(404,'User not found')
    if x.role=='OWNER' and p.status!='ACTIVE': raise HTTPException(403,'Owner cannot be suspended')
    old=x.status; x.status=p.status; await audit(db,u,'user.status',id,{'old':old,'new':p.status}); await db.commit(); return {'id':id,'status':x.status}

@router.patch('/admin/users/{id}/role',dependencies=[Depends(permission('admins.manage'))])
async def user_role(id:int,p:RoleIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    x=await db.get(User,id)
    if not x: raise HTTPException(404,'User not found')
    if x.id==u.id and p.role!='OWNER': raise HTTPException(400,'Cannot demote yourself')
    old=x.role; x.role=p.role; await audit(db,u,'user.role',id,{'old':old,'new':p.role}); await db.commit(); return {'id':id,'role':x.role}

@router.get('/admin/orders',dependencies=[Depends(permission('orders.read'))])
async def admin_orders(status:str|None=None,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:AsyncSession=Depends(get_db)):
    q=select(Order).order_by(Order.id.desc()).offset(offset).limit(limit)
    if status: q=select(Order).where(Order.status==status).order_by(Order.id.desc()).offset(offset).limit(limit)
    rows=(await db.execute(q)).scalars(); return [{'id':x.id,'user_id':x.user_id,'service_id':x.service_id,'quantity':x.quantity,'total':str(x.total),'currency':x.currency,'status':x.status,'created_at':x.created_at} for x in rows]

@router.get('/admin/audit',dependencies=[Depends(permission('audit.read'))])
async def admin_audit(limit:int=Query(100,ge=1,le=200),db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))).scalars(); return [{'id':x.id,'actor_id':x.actor_id,'action':x.action,'target':x.target,'metadata':json.loads(x.metadata_json or '{}'),'created_at':x.created_at} for x in rows]

@router.get('/admin/analytics',dependencies=[Depends(permission('analytics.read'))])
async def analytics(db:AsyncSession=Depends(get_db)):
    users=await db.scalar(select(func.count(User.id))); orders=await db.scalar(select(func.count(Order.id))); completed=await db.scalar(select(func.count(Order.id)).where(Order.status=='COMPLETED')); revenue=await db.scalar(select(func.coalesce(func.sum(Order.total),0)).where(Order.status.in_(['PROCESSING','IN_PROGRESS','COMPLETED']))); return {'users':users or 0,'orders':orders or 0,'completed_orders':completed or 0,'revenue':str(revenue or 0)}

@router.get('/admin/permissions',dependencies=[Depends(permission('admins.manage'))])
async def permissions(): return [{'role':r,'permissions':sorted(v)} for r,v in ROLE_PERMISSIONS.items()]

@router.get('/support/tickets')
async def tickets(db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    rows=(await db.execute(select(SupportTicket).where(SupportTicket.user_id==u.id).order_by(SupportTicket.id.desc()))).scalars(); return [{'id':x.id,'subject':x.subject,'priority':x.priority,'status':x.status,'updated_at':x.updated_at} for x in rows]

@router.post('/support/tickets')
async def create_ticket(subject:str,body:str,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    if not subject.strip() or not body.strip(): raise HTTPException(422,'Subject and body are required')
    x=SupportTicket(user_id=u.id,subject=subject[:200],priority='NORMAL',status='OPEN'); db.add(x); await db.flush(); db.add(SupportMessage(ticket_id=x.id,sender_id=u.id,body=body[:5000])); await notify(db,u.id,'SUPPORT_TICKET_CREATED',{'ticket_id':x.id}); await db.commit(); return {'id':x.id,'status':'OPEN'}

@router.get('/support/tickets/{id}')
async def ticket(id:int,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    x=await db.get(SupportTicket,id)
    if not x or (x.user_id!=u.id and u.role not in {'OWNER','ADMIN','SUPPORT','MODERATOR'}): raise HTTPException(404,'Ticket not found')
    msgs=(await db.execute(select(SupportMessage).where(SupportMessage.ticket_id==id).order_by(SupportMessage.id))).scalars(); return {'id':x.id,'subject':x.subject,'priority':x.priority,'status':x.status,'messages':[{'id':m.id,'sender_id':m.sender_id,'body':m.body,'created_at':m.created_at} for m in msgs]}

@router.post('/support/tickets/{id}/messages')
async def ticket_message(id:int,p:MessageIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    x=await db.get(SupportTicket,id)
    if not x or (x.user_id!=u.id and u.role not in {'OWNER','ADMIN','SUPPORT','MODERATOR'}): raise HTTPException(404,'Ticket not found')
    db.add(SupportMessage(ticket_id=id,sender_id=u.id,body=p.body)); x.status='IN_PROGRESS' if u.id!=x.user_id else 'WAITING_USER'; await db.commit(); return {'ok':True}

@router.patch('/admin/support/tickets/{id}',dependencies=[Depends(permission('support.manage'))])
async def manage_ticket(id:int,p:TicketPatch,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    x=await db.get(SupportTicket,id)
    if not x: raise HTTPException(404,'Ticket not found')
    for k,v in p.model_dump(exclude_unset=True).items(): setattr(x,k,v)
    await audit(db,u,'support.ticket.update',id,p.model_dump(exclude_unset=True)); await db.commit(); return {'ok':True}

@router.post('/admin/payment-methods',dependencies=[Depends(permission('payments.manage'))])
async def payment_method(p:PaymentMethodIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    key='payment_method:'+p.name.lower(); x=await db.get(Setting,key); payload=p.model_dump(); payload['account']='***'+p.account[-4:]
    if x: x.value_json=json.dumps(payload)
    else: db.add(Setting(key=key,value_json=json.dumps(payload)))
    await audit(db,u,'payment_method.configure',key,{'name':p.name,'currency':p.currency,'enabled':p.enabled}); await db.commit(); return {'name':p.name,'currency':p.currency,'enabled':p.enabled}

@router.get('/payment-methods')
async def payment_methods(db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(select(Setting).where(Setting.key.like('payment_method:%')))).scalars(); return [json.loads(x.value_json) for x in rows]
