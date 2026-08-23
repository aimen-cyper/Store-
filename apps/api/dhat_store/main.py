import hashlib, hmac, json, secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .config import settings
from .db import get_db
from .models import User, Session, Category, Service, Wallet, Ledger, Deposit, Order, AuditLog

app=FastAPI(title='DHĀT STORE API',version='1.0.0')
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(',')],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

def auth_user(data: str, bot_token: str):
    pairs=dict(parse_qsl(data,keep_blank_values=True)); given=pairs.pop('hash',None)
    if not given: raise HTTPException(401,'Invalid Telegram initData')
    auth_date=int(pairs.get('auth_date','0'))
    if datetime.now(timezone.utc).timestamp()-auth_date>900: raise HTTPException(401,'Expired Telegram auth')
    check='\n'.join(f'{k}={pairs[k]}' for k in sorted(pairs))
    secret=hmac.new(b'WebAppData',bot_token.encode(),hashlib.sha256).digest()
    expected=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,given): raise HTTPException(401,'Invalid Telegram signature')
    user=json.loads(pairs.get('user','{}'))
    if not user.get('id'): raise HTTPException(401,'Invalid Telegram user')
    return user

async def current_user(authorization: str|None=Header(default=None),db:AsyncSession=Depends(get_db)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Authentication required')
    h=hashlib.sha256(authorization[7:].encode()).hexdigest()
    s=(await db.execute(select(Session).where(Session.token_hash==h,Session.revoked_at.is_(None),Session.expires_at>datetime.now(timezone.utc)))).scalar_one_or_none()
    if not s: raise HTTPException(401,'Invalid session')
    u=await db.get(User,s.user_id)
    if not u or u.status!='ACTIVE': raise HTTPException(403,'Account unavailable')
    return u

def admin(u:User):
    if u.role not in {'OWNER','ADMIN'}: raise HTTPException(403,'Admin permission required')

class TelegramAuth(BaseModel): init_data:str
class CategoryIn(BaseModel): name:str=Field(min_length=1,max_length=160); slug:str=Field(min_length=1,max_length=160)
class ServiceIn(BaseModel): category_id:int; name:str; description:str=''; price:float=Field(ge=0); currency:str=Field(min_length=3,max_length=3); stock:int=Field(ge=0)
class DepositIn(BaseModel): amount:float=Field(gt=0); currency:str=Field(min_length=3,max_length=3); reference:str=Field(min_length=1,max_length=160)
class OrderIn(BaseModel): service_id:int; quantity:int=Field(gt=0); idempotency_key:str=Field(min_length=8,max_length=128)

@app.get('/health')
async def health(): return {'status':'ok'}

@app.post('/api/v1/auth/telegram')
async def telegram_auth(payload:TelegramAuth,db:AsyncSession=Depends(get_db)):
    if not settings.telegram_bot_token: raise HTTPException(503,'Telegram authentication is not configured')
    tg=auth_user(payload.init_data,settings.telegram_bot_token)
    u=(await db.execute(select(User).where(User.telegram_id==tg['id']))).scalar_one_or_none()
    if not u:
        role='OWNER' if settings.owner_telegram_id==tg['id'] else 'CUSTOMER'; u=User(telegram_id=tg['id'],username=tg.get('username'),role=role); db.add(u); await db.flush()
    else: u.username=tg.get('username',u.username)
    token=secrets.token_urlsafe(48); db.add(Session(user_id=u.id,token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=datetime.now(timezone.utc)+timedelta(days=settings.session_days)))
    await db.commit(); return {'access_token':token,'token_type':'bearer','user':{'id':u.id,'telegram_id':u.telegram_id,'role':u.role}}

@app.post('/api/v1/auth/logout')
async def logout(authorization:str|None=Header(default=None),db:AsyncSession=Depends(get_db)):
    if authorization and authorization.startswith('Bearer '):
        h=hashlib.sha256(authorization[7:].encode()).hexdigest(); s=(await db.execute(select(Session).where(Session.token_hash==h))).scalar_one_or_none()
        if s: s.revoked_at=datetime.now(timezone.utc); await db.commit()
    return {'ok':True}

@app.get('/api/v1/auth/me')
async def me(u:User=Depends(current_user)): return {'id':u.id,'telegram_id':u.telegram_id,'username':u.username,'role':u.role,'status':u.status}

@app.get('/api/v1/catalog/categories')
async def categories(db:AsyncSession=Depends(get_db)): return [{'id':x.id,'name':x.name,'slug':x.slug} for x in (await db.execute(select(Category).where(Category.enabled.is_(True)).order_by(Category.id))).scalars()]

@app.get('/api/v1/catalog/services')
async def services(db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(select(Service).where(Service.enabled.is_(True)).order_by(Service.id))).scalars()
    return [{'id':x.id,'category_id':x.category_id,'name':x.name,'description':x.description,'price':str(x.price),'currency':x.currency,'stock':x.stock} for x in rows]

@app.post('/api/v1/admin/categories')
async def create_category(p:CategoryIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    admin(u); x=Category(**p.model_dump()); db.add(x); await db.flush(); db.add(AuditLog(actor_id=u.id,action='category.create',target=str(x.id))); await db.commit(); return {'id':x.id,'name':x.name,'slug':x.slug}

@app.post('/api/v1/admin/services')
async def create_service(p:ServiceIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    admin(u); x=Service(**p.model_dump()); db.add(x); await db.flush(); db.add(AuditLog(actor_id=u.id,action='service.create',target=str(x.id))); await db.commit(); return {'id':x.id}

@app.get('/api/v1/wallets')
async def wallets(db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    return [{'currency':x.currency,'balance':str(x.balance)} for x in (await db.execute(select(Wallet).where(Wallet.user_id==u.id))).scalars()]

@app.post('/api/v1/deposits')
async def deposit(p:DepositIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    d=Deposit(user_id=u.id,**p.model_dump()); db.add(d); await db.commit(); await db.refresh(d); return {'id':d.id,'status':d.status}

@app.post('/api/v1/admin/deposits/{deposit_id}/approve')
async def approve_deposit(deposit_id:int,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    admin(u); d=await db.get(Deposit,deposit_id)
    if not d: raise HTTPException(404,'Deposit not found')
    if d.status=='APPROVED': return {'id':d.id,'status':'APPROVED'}
    if d.status!='PENDING': raise HTTPException(409,'Deposit is not pending')
    w=(await db.execute(select(Wallet).where(Wallet.user_id==d.user_id,Wallet.currency==d.currency).with_for_update())).scalar_one_or_none()
    if not w: w=Wallet(user_id=d.user_id,currency=d.currency,balance=0); db.add(w); await db.flush()
    d.status='APPROVED'; w.balance+=d.amount; db.add(Ledger(wallet_id=w.id,amount=d.amount,type='DEPOSIT',idempotency_key=f'deposit:{d.id}',reference=str(d.id))); db.add(AuditLog(actor_id=u.id,action='deposit.approve',target=str(d.id))); await db.commit(); return {'id':d.id,'status':'APPROVED'}

@app.post('/api/v1/orders')
async def create_order(p:OrderIn,db:AsyncSession=Depends(get_db),u:User=Depends(current_user)):
    old=(await db.execute(select(Order).where(Order.idempotency_key==p.idempotency_key))).scalar_one_or_none()
    if old: return {'id':old.id,'status':old.status,'idempotent':True}
    s=await db.get(Service,p.service_id)
    if not s or not s.enabled: raise HTTPException(404,'Service unavailable')
    total=s.price*p.quantity
    w=(await db.execute(select(Wallet).where(Wallet.user_id==u.id,Wallet.currency==s.currency).with_for_update())).scalar_one_or_none()
    if not w or w.balance<total: raise HTTPException(402,'Insufficient balance')
    if s.stock and s.stock<p.quantity: raise HTTPException(409,'Insufficient stock')
    w.balance-=total
    if s.stock: s.stock-=p.quantity
    o=Order(user_id=u.id,service_id=s.id,quantity=p.quantity,total=total,currency=s.currency,idempotency_key=p.idempotency_key,status='CONFIRMED'); db.add(o); await db.flush(); db.add(Ledger(wallet_id=w.id,amount=-total,type='PURCHASE',idempotency_key=f'order:{o.id}',reference=str(o.id))); await db.commit(); return {'id':o.id,'status':o.status,'total':str(total),'currency':s.currency}
