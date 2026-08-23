import asyncio,json,os
from datetime import datetime,timezone
import httpx
from sqlalchemy import select
from .db import AsyncSessionLocal
from .models import Notification,User

async def deliver(n,u):
    token=os.getenv('TELEGRAM_BOT_TOKEN');
    if not token or not u.telegram_id:return False
    text=f"{n.event}\n"+json.dumps(json.loads(n.payload_json or '{}'),ensure_ascii=False)
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':u.telegram_id,'text':text});return r.is_success
async def run_once():
    async with AsyncSessionLocal() as db:
        rows=(await db.execute(select(Notification).where(Notification.status=='PENDING',Notification.available_at<=datetime.now(timezone.utc)).order_by(Notification.id).limit(25).with_for_update(skip_locked=True))).scalars().all()
        for n in rows:
            u=await db.get(User,n.user_id);n.attempts+=1
            try:ok=await deliver(n,u)
            except Exception:ok=False
            if ok:n.status='SENT';n.sent_at=datetime.now(timezone.utc)
            elif n.attempts>=8:n.status='DEAD'
            else:n.available_at=datetime.now(timezone.utc)
        await db.commit()
async def main():
    while True:
        try:await run_once()
        except Exception:pass
        await asyncio.sleep(3)
if __name__=='__main__':asyncio.run(main())
