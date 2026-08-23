import os
import httpx
from .core import ProviderAdapter, ProviderError, ProviderTimeout

class HttpProvider(ProviderAdapter):
    def __init__(self,base_url,api_key,timeout=15):
        self.base_url=base_url.rstrip('/'); self.api_key=api_key; self.timeout=timeout
    async def _request(self,method,path,**kwargs):
        headers={'Authorization':f'Bearer {self.api_key}','Accept':'application/json'}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r=await client.request(method,self.base_url+path,headers=headers,**kwargs)
        except httpx.TimeoutException as e: raise ProviderTimeout(str(e)) from e
        except httpx.HTTPError as e: raise ProviderError(str(e)) from e
        if r.status_code==429: raise ProviderError('provider rate limited')
        if r.status_code>=500: raise ProviderError(f'provider server error {r.status_code}')
        if r.status_code>=400: raise ProviderError(f'provider rejected request {r.status_code}')
        try:return r.json()
        except ValueError as e: raise ProviderError('malformed provider response') from e
    async def get_services(self): return await self._request('GET','/services')
    async def get_balance(self): return await self._request('GET','/balance')
    async def create_order(self,external_service_id,quantity,parameters): return await self._request('POST','/orders',json={'service_id':external_service_id,'quantity':quantity,'parameters':parameters})
    async def get_order_status(self,external_id): return await self._request('GET',f'/orders/{external_id}')
    async def cancel_order(self,external_id): return await self._request('POST',f'/orders/{external_id}/cancel')
    async def refill_order(self,external_id): return await self._request('POST',f'/orders/{external_id}/refill')

def provider_config(name):
    prefix='DHAT_PROVIDER_'+name.upper().replace('-','_')
    return os.getenv(prefix+'_URL'),os.getenv(prefix+'_KEY')
