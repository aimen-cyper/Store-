from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
@dataclass(frozen=True)
class PaymentIntent: id:str; status:str; amount:Decimal; currency:str
class PaymentProvider(Protocol):
    async def create_payment(self,amount:Decimal,currency:str,idempotency_key:str,metadata:dict)->PaymentIntent:...
    async def verify_payment(self,external_id:str)->PaymentIntent:...
    async def handle_webhook(self,payload:bytes,signature:str)->dict:...
    async def refund(self,external_id:str,amount:Decimal|None=None)->PaymentIntent:...
class DisabledPaymentProvider:
    async def create_payment(self,*a,**k): raise RuntimeError('No payment provider configured')
    async def verify_payment(self,*a,**k): raise RuntimeError('No payment provider configured')
    async def handle_webhook(self,*a,**k): raise RuntimeError('No payment provider configured')
    async def refund(self,*a,**k): raise RuntimeError('No payment provider configured')
