import hashlib,hmac,json,os
from decimal import Decimal
from fastapi import APIRouter,Depends,Header,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_db
from .models import Payment

router=APIRouter(prefix='/api/v1/payments',tags=['payments'])

class PaymentWebhook(BaseModel):
    external_id:str=Field(min_length=1,max_length=160)
    user_id:int
    amount:Decimal
    currency:str=Field(min_length=3,max_length=3)
    status:str=Field(pattern='^(PENDING|SUCCEEDED|FAILED|REFUNDED)$')
    metadata:dict={}

def secret_for(provider:str): return os.getenv('DHAT_PAYMENT_'+provider.upper().replace('-','_')+'_WEBHOOK_SECRET')

@router.post('/webhook/{provider}')
async def webhook(provider:str,p:PaymentWebhook,x_signature:str|None=Header(default=None),db:AsyncSession=Depends(get_db)):
    secret=secret_for(provider)
    if not secret: raise HTTPException(503,'Payment webhook is not configured')
    if not x_signature: raise HTTPException(401,'Missing webhook signature')
    canonical=f'{p.external_id}|{p.user_id}|{p.amount}|{p.currency}|{p.status}'
    expected=hmac.new(secret.encode(),canonical.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,x_signature): raise HTTPException(401,'Invalid webhook signature')
    existing=(await db.execute(select(Payment).where(Payment.external_id==p.external_id))).scalar_one_or_none()
    if existing:
        existing.status=p.status; existing.metadata_json=json.dumps(p.metadata,default=str); await db.commit(); return {'ok':True,'idempotent':True,'payment_id':existing.id}
    payment=Payment(user_id=p.user_id,provider=provider,external_id=p.external_id,amount=p.amount,currency=p.currency,status=p.status,idempotency_key='webhook:'+hashlib.sha256(p.external_id.encode()).hexdigest(),metadata_json=json.dumps(p.metadata,default=str))
    db.add(payment); await db.commit(); return {'ok':True,'payment_id':payment.id}
