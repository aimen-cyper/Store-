import os
from telegram import InlineKeyboardButton,InlineKeyboardMarkup,Update,WebAppInfo
from telegram.ext import Application,CommandHandler,ContextTypes
TOKEN=os.environ.get('TELEGRAM_BOT_TOKEN'); WEB_APP_URL=os.environ.get('WEB_APP_URL','http://localhost:5173')
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    markup=InlineKeyboardMarkup([[InlineKeyboardButton('فتح المتجر',web_app=WebAppInfo(WEB_APP_URL))]])
    await update.message.reply_text('مرحباً بك في DHĀT STORE',reply_markup=markup)
def main():
    if not TOKEN: raise RuntimeError('TELEGRAM_BOT_TOKEN is required')
    app=Application.builder().token(TOKEN).build(); app.add_handler(CommandHandler('start',start)); app.run_polling()
if __name__=='__main__': main()
