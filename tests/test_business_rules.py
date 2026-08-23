from decimal import Decimal
from types import SimpleNamespace
from apps.api.dhat_store.core import calculate_price,coupon_discount,transition_allowed

def test_pricing_rules_are_deterministic():
    rules=[SimpleNamespace(enabled=True,priority=20,kind='FIXED',value=Decimal('2')),SimpleNamespace(enabled=True,priority=10,kind='PERCENT',value=Decimal('10'))]
    assert calculate_price(Decimal('10'),rules)==Decimal('13.0000')

def test_coupon_limits_discount():
    c=SimpleNamespace(min_order=Decimal('10'),max_discount=Decimal('3'),kind='PERCENT',value=Decimal('50'))
    assert coupon_discount(Decimal('20'),c)==Decimal('3.0000')

def test_order_transition_guard():
    assert transition_allowed('PROCESSING','IN_PROGRESS')
    assert not transition_allowed('COMPLETED','FAILED')
    assert transition_allowed('UNKNOWN','COMPLETED')
