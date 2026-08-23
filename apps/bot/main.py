import os
from telegram import Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
TOKEN=os.environ.get('TELEGRAM_BOT_TOKEN')
WEB_APP_URL=os.environ.get('WEB_APP_URL','http://localhost:5173')
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('مرحباً بك في DHĀT STORE\nافتح المتجر من الزر في واجهة Telegram.',reply_markup={'inline_keyboard':[[{'text':'فتح المتجر','web_app':{'url':WEB_APP_URL}}]]})
def main():
    if not TOKEN: raise RuntimeError('TELEGRAM_BOT_TOKEN is required')
    Application.builder().token(TOKEN).build().add_handler(CommandHandler('start',start))
if __name__=='__main__': main()
