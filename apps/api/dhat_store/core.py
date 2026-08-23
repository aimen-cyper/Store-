from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass
from enum import StrEnum

class OrderStatus(StrEnum):
    PENDING='PENDING'; PROCESSING='PROCESSING'; IN_PROGRESS='IN_PROGRESS'; COMPLETED='COMPLETED'; PARTIAL='PARTIAL'; CANCELED='CANCELED'; FAILED='FAILED'; REFUNDING='REFUNDING'; REFUNDED='REFUNDED'; UNKNOWN='UNKNOWN'

TRANSITIONS={
 'PENDING':{'PROCESSING','CANCELED','FAILED'},'PROCESSING':{'IN_PROGRESS','COMPLETED','PARTIAL','FAILED','UNKNOWN','CANCELED'},'IN_PROGRESS':{'COMPLETED','PARTIAL','FAILED','UNKNOWN'},'COMPLETED':{'REFUNDING'},'PARTIAL':{'REFUNDING'},'FAILED':{'REFUNDING'},'REFUNDING':{'REFUNDED','FAILED'},'UNKNOWN':{'PROCESSING','COMPLETED','PARTIAL','FAILED'}
}

def transition_allowed(old,new): return new in TRANSITIONS.get(old,set())

def money(v): return Decimal(str(v)).quantize(Decimal('0.0001'),rounding=ROUND_HALF_UP)

def calculate_price(cost, rules):
    price=money(cost)
    for rule in sorted(rules,key=lambda r:r.priority):
        if not rule.enabled: continue
        if rule.kind=='OVERRIDE': price=money(rule.value)
        elif rule.kind=='FIXED': price=money(price+rule.value)
        elif rule.kind=='PERCENT': price=money(price+(price*rule.value/Decimal(100)))
        elif rule.kind=='MULTIPLIER': price=money(price*rule.value)
        else: raise ValueError(f'Unsupported pricing rule: {rule.kind}')
    return max(Decimal('0'),price)

def coupon_discount(total,coupon):
    total=money(total)
    if coupon.min_order is not None and total<coupon.min_order: return Decimal('0')
    if coupon.kind=='PERCENT': d=total*coupon.value/Decimal(100)
    elif coupon.kind=='FIXED': d=coupon.value
    else: raise ValueError('Unsupported coupon kind')
    if coupon.max_discount is not None: d=min(d,coupon.max_discount)
    return max(Decimal('0'),min(d,total))

@dataclass(frozen=True)
class ProviderResult:
    status:str
    external_id:str|None=None
    message:str|None=None

class ProviderAdapter:
    async def get_services(self): raise NotImplementedError
    async def get_balance(self): raise NotImplementedError
    async def create_order(self,external_service_id,quantity,parameters): raise NotImplementedError
    async def get_order_status(self,external_id): raise NotImplementedError
    async def cancel_order(self,external_id): raise NotImplementedError
    async def refill_order(self,external_id): raise NotImplementedError

class ProviderError(Exception): pass
class ProviderTimeout(ProviderError): pass
