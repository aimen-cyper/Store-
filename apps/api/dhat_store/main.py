import hashlib,hmac,json,secrets
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from urllib.parse import parse_qsl
from fastapi import Depends,FastAPI,Header,HTTPException,Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from sqlalchemy import select,func,or_
from sqlalchemy.ext.asyncio import AsyncSession
from .config import settings
from .db import get_db
from .models import *
from .core import calculate_price,coupon_discount,transition_allowed
from .provider_routes import router as provider_router
from .dispatch_routes import router as dispatch_router
from .refund_routes import router as refund_router
app=FastAPI(title='DHĀT STORE API',version='2.0.0');app.include_router(provider_router);app.include_router(dispatch_router);app.include_router(refund_router)
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(',')],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
def tg_verify(data,token):
    pairs=dict(parse_qsl(data,keep_blank_values=True));given=pairs.pop('hash',None)
    if not given:raise HTTPException(401,'Invalid Telegram initData')
    try:auth_date=int(pairs.get('auth_date','0'))
    except ValueError:raise HTTPException(401,'Invalid auth_date')
    if datetime.now(timezone.utc).timestamp()-auth_date>900:raise HTTPException(401,'Expired Telegram auth')
    check='\n'.join(f'{k}={pairs[k]}' for k in sorted(pairs));secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest();expected=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,given):raise HTTPException(401,'Invalid Telegram signature')
    try:user=json.loads(pairs.get('user','{}'))
    except json.JSONDecodeError:raise HTTPException(401,'Malformed Telegram user')
    if not user.get('id'):raise HTTPException(401,'Invalid Telegram user')
    return user
async def current_user(authorization:str|None=Header(default=None),db:AsyncSession=Depends(get_db)):
    if not authorization or not authorization.startswith('Bearer '):raise HTTPException(401,'Authentication required')
    raw=authorization[7:];h=hashlib.sha256(raw.encode()).hexdigest();s=(await db.execute(select(Session).where(Session.token_hash==h,Session.revoked_at.is_(None),Session.expires_at>datetime.now(timezone.utc)))).scalar_one_or_none()
    if not s:raise HTTPException(401,'Invalid session')
    u=await db.get(User,s.user_id)
    if not u or u.status!='ACTIVE':raise HTTPException(403,'Account unavailable')
    s.last_used_at=datetime.now(timezone.utc);return u
def require_roles(*roles):
    async def guard(u:User=Depends(current_user)):
        if u.role not in roles:raise HTTPException(403,'Permission denied')
        return u
    return guard
async def audit(db,actor,action,target,metadata=None):db.add(AuditLog(actor_id=actor.id if actor else None,action=action,target=str(target),metadata_json=json.dumps(metadata or {},default=str)))
async def notify(db,user_id,event,payload):db.add(Notification(user_id=user_id,event=event,payload_json=json.dumps(payload,default=str),status='PENDING',attempts=0,available_at=datetime.now(timezone.utc)))
class TelegramAuth(BaseModel):init_data:str
class CategoryIn(BaseModel):name:str=Field(min_length=1,max_length=160);slug:str=Field(min_length=1,max_length=160)
class ServiceIn(BaseModel):category_id:int;name:str=Field(min_length=1,max_length=200);description:str='';price:Decimal=Field(ge=0);currency:str=Field(min_length=3,max_length=3);stock:int=Field(ge=0)
class DepositIn(BaseModel):amount:Decimal=Field(gt=0);currency:str=Field(min_length=3,max_length=3);reference:str=Field(min_length=1,max_length=160)
class OrderIn(BaseModel):service_id:int;quantity:int=Field(gt=0);idempotency_key:str=Field(min_length=8,max_length=128);coupon_code:str|None=None;parameters:dict[str,str]={}
class CouponIn(BaseModel):code:str;kind:str;value:Decimal=Field(gt=0);min_order:Decimal|None=None;max_discount:Decimal|None=None;expires_at:datetime|None=None;usage_limit:int|None=None;per_user_limit:int=1
class TicketIn(BaseModel):subject:str=Field(min_length=1,max_length=200);body:str=Field(min_length=1,max_length=5000);priority:str='NORMAL'
class MessageIn(BaseModel):body:str=Field(min_length=1,max_length=5000)
@app.get('/health')
async def health():return {'status':'ok','service':'dhat-store'}
@app.get('/api/v1/health/ready')
async def ready(db:AsyncSession=Depends(get_db)):await db.execute(select(func.count()).select_from(User));return {'status':'ready'}
@app.post('/api/v1/auth/telegram')
async def telegram_auth(p:TelegramAuth,db:AsyncSession=Depends(get_db)):
    if not settings.telegram_bot_token:raise HTTPException(503,'Telegram authentication is not configured')
    tg=tg_verify(p.init_data,settings.telegram_bot_token);u=(await db.execute(select(User).where(User.telegram_id==tg['id']))).scalar_one_or_none()
    if not u:role='OWNER' if settings.owner_telegram_id==tg['id'] else 'CUSTOMER';u=User(telegram_id=tg['id'],username=tg.get('username'),role=role);db.add(u);await db.flush()
    else:u.username=tg.get('username',u.username)
    token=secrets.token_urlsafe(48);db.add(Session(user_id=u.id,token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=datetime.now(timezone.utc)+timedelta(days=settings.session_days)));await db.commit();return {'access_token':token,'token_type':'bearer','user':{'id':u.id,'telegram_id':u.telegram_id,'username':u.username,'role':u.role}}
@app.post('/api/v1/auth/logout')
async def logout(authorization:str|None=Header(default=None),db:AsyncSession=Depends(get_db)):
    if authorization and authorization.startswith('Bearer '):
        s=(await db.execute(select(Session).where(Session.token_hash==hashlib.sha256(authorization[7:].encode()).hexdigest()))).scalar_one_or_none()
        if s:s.revoked_at=datetime.now(timezone.utc);await db.commit()
    return {'ok':True}
@app.get('/api/v1/auth/me')
async def me(u:User=Depends(current_user)):return {'id':u.id,'telegram_id':u.telegram_id,'username':u.username,'role':u.role,'status':u.status}
@app.get('/api/v1/catalog/categories')
async def categories(db:AsyncSession=Depends(get_db)):return [{'id':x.id,'name':x.name,'slug':x.slug} for x in (await db.execute(select(Category).where(Category.enabled.is_(True)).order_by(Category.id))).scalars()]
@app.get('/api/v1/catalog/services')
async def services(search:str|None=None,category_id:int|None=None,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:AsyncSession=Depends(get_db)):
    q=select(Service).where(Service.enabled.is_(True));
    if search:q=q.where(or_(Service.name.ilike(f'%{search}%'),Service.description.ilike(f'%{search}%')))
    if category_id:q=q.where(Service.category_id==category_id)
    rows=(await db.execute(q.order_by(Service.id).offset(offset).limit(limit))).scalars();return [{'id':x.id,'category_id':x.category_id,'name':x.name,'description':x.description,'price':str(x.price),'currency':x.currency,'stock':x.stock} for x in rows]
@app.post('/api/v1/admin/categories')
async def create_category(p:CategoryIn,db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN'))):x=Category(**p.model_dump());db.add(x);await db.flush();await audit(db,u,'category.create',x.id,p.model_dump());await db.commit();return {'id':x.id}
@app.post('/api/v1/admin/services')
async def create_service(p:ServiceIn,db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN'))):
    if not await db.get(Category,p.category_id):raise HTTPException(404,'Category not found')
    x=Service(**p.model_dump());db.add(x);await db.flush();await audit(db,u,'service.create',x.id,p.model_dump());await db.commit();return {'id':x.id}
@app.get('/api/v1/wallets')
async def wallets(db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):return [{'currency':x.currency,'balance':str(x.balance)} for x in (await db.execute(select(Wallet).where(Wallet.user_id==u.id))).scalars()]
@app.get('/api/v1/wallets/transactions')
async def wallet_transactions(limit:int=Query(50,ge=1,le=100),db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):return [{'id':x.id,'amount':str(x.amount),'type':x.type,'reference':x.reference,'created_at':x.created_at} for x in (await db.execute(select(Ledger).join(Wallet).where(Wallet.user_id==u.id).order_by(Ledger.id.desc()).limit(limit))).scalars()]
@app.post('/api/v1/deposits')
async def deposit(p:DepositIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    if p.currency not in {'YER','USD'}:raise HTTPException(400,'Unsupported currency')
    d=Deposit(user_id=u.id,**p.model_dump());db.add(d);await db.flush();await notify(db,u.id,'DEPOSIT_PENDING',{'deposit_id':d.id});await db.commit();return {'id':d.id,'status':d.status}
@app.get('/api/v1/deposits')
async def deposits(db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):return [{'id':d.id,'amount':str(d.amount),'currency':d.currency,'reference':d.reference,'status':d.status,'created_at':d.created_at} for d in (await db.execute(select(Deposit).where(Deposit.user_id==u.id).order_by(Deposit.id.desc()))).scalars()]
@app.post('/api/v1/admin/deposits/{deposit_id}/approve')
async def approve_deposit(deposit_id:int,db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN','FINANCE'))):
    d=(await db.execute(select(Deposit).where(Deposit.id==deposit_id).with_for_update())).scalar_one_or_none()
    if not d:raise HTTPException(404,'Deposit not found')
    if d.status=='APPROVED':return {'id':d.id,'status':'APPROVED'}
    if d.status!='PENDING':raise HTTPException(409,'Deposit is not pending')
    w=(await db.execute(select(Wallet).where(Wallet.user_id==d.user_id,Wallet.currency==d.currency).with_for_update())).scalar_one_or_none()
    if not w:w=Wallet(user_id=d.user_id,currency=d.currency,balance=0);db.add(w);await db.flush()
    d.status='APPROVED';w.balance+=d.amount;db.add(Ledger(wallet_id=w.id,amount=d.amount,type='DEPOSIT',idempotency_key=f'deposit:{d.id}',reference=str(d.id)));await audit(db,u,'deposit.approve',d.id);await notify(db,d.user_id,'DEPOSIT_APPROVED',{'deposit_id':d.id,'amount':str(d.amount),'currency':d.currency});await db.commit();return {'id':d.id,'status':'APPROVED'}
@app.post('/api/v1/admin/deposits/{deposit_id}/reject')
async def reject_deposit(deposit_id:int,db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN','FINANCE'))):
    d=(await db.execute(select(Deposit).where(Deposit.id==deposit_id).with_for_update())).scalar_one_or_none()
    if not d:raise HTTPException(404,'Deposit not found')
    if d.status!='PENDING':return {'id':d.id,'status':d.status}
    d.status='REJECTED';await audit(db,u,'deposit.reject',d.id);await notify(db,d.user_id,'DEPOSIT_REJECTED',{'deposit_id':d.id});await db.commit();return {'id':d.id,'status':'REJECTED'}
@app.post('/api/v1/admin/coupons')
async def create_coupon(p:CouponIn,db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN'))):
    if p.kind not in {'PERCENT','FIXED'}:raise HTTPException(400,'Invalid coupon kind')
    x=Coupon(**p.model_dump());x.code=x.code.upper();db.add(x);await db.flush();await audit(db,u,'coupon.create',x.id,{'code':x.code});await db.commit();return {'id':x.id,'code':x.code}
@app.post('/api/v1/orders/quote')
async def quote(p:OrderIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    s=await db.get(Service,p.service_id)
    if not s or not s.enabled:raise HTTPException(404,'Service unavailable')
    rules=(await db.execute(select(PricingRule).where(PricingRule.enabled.is_(True),or_(PricingRule.service_id==s.id,PricingRule.category_id==s.category_id)))).scalars().all();unit=calculate_price(s.price,rules);total=unit*p.quantity;discount=Decimal('0')
    if p.coupon_code:
        c=(await db.execute(select(Coupon).where(Coupon.code==p.coupon_code.upper(),Coupon.active.is_(True)))).scalar_one_or_none()
        if not c:raise HTTPException(400,'Invalid coupon')
        if c.expires_at and c.expires_at<=datetime.now(timezone.utc):raise HTTPException(400,'Coupon expired')
        discount=coupon_discount(total,c)
    return {'unit_price':str(unit),'subtotal':str(total),'discount':str(discount),'total':str(max(Decimal('0'),total-discount)),'currency':s.currency}
@app.post('/api/v1/orders')
async def create_order(p:OrderIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    old=(await db.execute(select(Order).where(Order.idempotency_key==p.idempotency_key))).scalar_one_or_none()
    if old:return {'id':old.id,'status':old.status,'idempotent':True}
    s=(await db.execute(select(Service).where(Service.id==p.service_id,Service.enabled.is_(True)).with_for_update())).scalar_one_or_none()
    if not s:raise HTTPException(404,'Service unavailable')
    rules=(await db.execute(select(PricingRule).where(PricingRule.enabled.is_(True),or_(PricingRule.service_id==s.id,PricingRule.category_id==s.category_id)))).scalars().all();unit=calculate_price(s.price,rules);subtotal=unit*p.quantity;discount=Decimal('0');coupon=None
    if p.coupon_code:
        coupon=(await db.execute(select(Coupon).where(Coupon.code==p.coupon_code.upper(),Coupon.active.is_(True)).with_for_update())).scalar_one_or_none()
        if not coupon:raise HTTPException(400,'Invalid coupon')
        if coupon.expires_at and coupon.expires_at<=datetime.now(timezone.utc):raise HTTPException(400,'Coupon expired')
        discount=coupon_discount(subtotal,coupon)
    total=max(Decimal('0'),subtotal-discount);w=(await db.execute(select(Wallet).where(Wallet.user_id==u.id,Wallet.currency==s.currency).with_for_update())).scalar_one_or_none()
    if not w or w.balance<total:raise HTTPException(402,'Insufficient balance')
    if s.stock and s.stock<p.quantity:raise HTTPException(409,'Insufficient stock')
    w.balance-=total
    if s.stock:s.stock-=p.quantity
    o=Order(user_id=u.id,service_id=s.id,quantity=p.quantity,total=total,currency=s.currency,idempotency_key=p.idempotency_key,status='PROCESSING');db.add(o);await db.flush();db.add(Ledger(wallet_id=w.id,amount=-total,type='PURCHASE',idempotency_key=f'order:{o.id}',reference=str(o.id)));db.add(OrderEvent(order_id=o.id,new_status='PROCESSING',old_status='PENDING',actor_id=u.id,source='CUSTOMER',metadata_json='{}'))
    if coupon:db.add(CouponRedemption(coupon_id=coupon.id,user_id=u.id,order_id=o.id,discount=discount))
    await notify(db,u.id,'ORDER_CREATED',{'order_id':o.id,'total':str(total),'currency':s.currency});await db.commit();return {'id':o.id,'status':o.status,'total':str(total),'currency':s.currency}
@app.get('/api/v1/orders')
async def orders(limit:int=Query(50,ge=1,le=100),db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):return [{'id':o.id,'service_id':o.service_id,'quantity':o.quantity,'total':str(o.total),'currency':o.currency,'status':o.status,'created_at':o.created_at} for o in (await db.execute(select(Order).where(Order.user_id==u.id).order_by(Order.id.desc()).limit(limit))).scalars()]
@app.post('/api/v1/admin/orders/{order_id}/status')
async def change_order(order_id:int,status:str,db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN','SUPPORT'))):
    o=(await db.execute(select(Order).where(Order.id==order_id).with_for_update())).scalar_one_or_none()
    if not o:raise HTTPException(404,'Order not found')
    status=status.upper()
    if not transition_allowed(o.status,status):raise HTTPException(409,f'Invalid transition {o.status}->{status}')
    old=o.status;o.status=status;db.add(OrderEvent(order_id=o.id,old_status=old,new_status=status,actor_id=u.id,source='ADMIN',metadata_json='{}'));await notify(db,o.user_id,'ORDER_'+status,{'order_id':o.id});await audit(db,u,'order.status',o.id,{'old':old,'new':status});await db.commit();return {'id':o.id,'status':status}
@app.post('/api/v1/support/tickets')
async def create_ticket(p:TicketIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    if p.priority not in {'LOW','NORMAL','HIGH','URGENT'}:raise HTTPException(400,'Invalid priority')
    t=SupportTicket(user_id=u.id,subject=p.subject,priority=p.priority,status='OPEN');db.add(t);await db.flush();db.add(SupportMessage(ticket_id=t.id,sender_id=u.id,body=p.body));await db.commit();return {'id':t.id,'status':t.status}
@app.get('/api/v1/support/tickets')
async def list_tickets(db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    q=select(SupportTicket).where(SupportTicket.user_id==u.id) if u.role=='CUSTOMER' else select(SupportTicket);return [{'id':t.id,'subject':t.subject,'priority':t.priority,'status':t.status,'created_at':t.created_at,'updated_at':t.updated_at} for t in (await db.execute(q.order_by(SupportTicket.id.desc()))).scalars()]
@app.post('/api/v1/support/tickets/{ticket_id}/messages')
async def message_ticket(ticket_id:int,p:MessageIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    t=await db.get(SupportTicket,ticket_id)
    if not t:raise HTTPException(404,'Ticket not found')
    if u.role=='CUSTOMER' and t.user_id!=u.id:raise HTTPException(403,'Permission denied')
    db.add(SupportMessage(ticket_id=t.id,sender_id=u.id,body=p.body));t.updated_at=datetime.now(timezone.utc);await db.commit();return {'ok':True}
@app.get('/api/v1/admin/analytics')
async def analytics(db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN'))):
    users=await db.scalar(select(func.count(User.id)));orders=await db.scalar(select(func.count(Order.id)));completed=await db.scalar(select(func.count(Order.id)).where(Order.status=='COMPLETED'));revenue=await db.scalar(select(func.coalesce(func.sum(Order.total),0)).where(Order.status.in_(['COMPLETED','PROCESSING','IN_PROGRESS'])));refunds=await db.scalar(select(func.coalesce(func.sum(Ledger.amount),0)).where(Ledger.type=='REFUND'));return {'users':users or 0,'orders':orders or 0,'completed_orders':completed or 0,'revenue':str(revenue or 0),'refunds':str(refunds or 0)}
@app.get('/api/v1/admin/audit')
async def audit_logs(limit:int=Query(100,ge=1,le=500),db:AsyncSession=Depends(get_db),u:User=Depends(require_roles('OWNER','ADMIN'))):return [{'id':x.id,'actor_id':x.actor_id,'action':x.action,'target':x.target,'metadata':json.loads(x.metadata_json or '{}'),'created_at':x.created_at} for x in (await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))).scalars()]
