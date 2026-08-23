import os,httpx
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import Application,CommandHandler,ContextTypes
API=os.getenv('DHAT_API_URL','http://api:8000');TOKEN=os.environ['TELEGRAM_BOT_TOKEN'];STORE_URL=os.getenv('DHAT_STORE_URL','https://t.me')
async def api(path,user_id):
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.get(API+path);r.raise_for_status();return r.json()
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    kb=[[InlineKeyboardButton('🛒 فتح المتجر',url=STORE_URL)],[InlineKeyboardButton('💰 الرصيد',callback_data='balance'),InlineKeyboardButton('📦 طلباتي',callback_data='orders')],[InlineKeyboardButton('💳 إيداع',url=STORE_URL),InlineKeyboardButton('🎧 الدعم',url=STORE_URL)]]
    await update.message.reply_text('مرحباً بك في DHĀT STORE',reply_markup=InlineKeyboardMarkup(kb))
async def balance(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query;await q.answer();
    try:
        await q.message.reply_text('افتح المتجر لعرض محفظتك بعد تسجيل الدخول عبر Telegram.')
    except Exception: pass
async def orders(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query;await q.answer();await q.message.reply_text('طلباتك متاحة داخل المتجر.')
def main():
    app=Application.builder().token(TOKEN).build();app.add_handler(CommandHandler('start',start));app.run_polling(allowed_updates=Update.ALL_TYPES)
if __name__=='__main__':main()
