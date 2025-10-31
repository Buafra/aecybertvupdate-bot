# -*- coding: utf-8 -*-
# ------------------------- MENU OPENERS ------------------
async def open_trial_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
q = update.callback_query
await q.answer()
await context.bot.send_message(chat_id=update.effective_chat.id, text="🎁 Free Trial")
await trial_start(update, context)


async def open_renew_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
q = update.callback_query
await q.answer()
await context.bot.send_message(chat_id=update.effective_chat.id, text="🔁 Renew")
await renew_start(update, context)


async def open_support_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
q = update.callback_query
await q.answer()
await context.bot.send_message(chat_id=update.effective_chat.id, text="🛟 Support")
await support_start(update, context)


# Simple offers placeholder (no-op, avoids broken button)
async def cb_offers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
q = update.callback_query
await q.answer()
await context.bot.send_message(chat_id=update.effective_chat.id, text="لا توجد عروض حالياً / No offers right now.")


# ------------------------- MAIN --------------------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
logging.exception("Unhandled error", exc_info=context.error)




def main() -> None:
logging.basicConfig(level=logging.INFO)
app = Application.builder().token(BOT_TOKEN).build()


# Commands
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(CommandHandler("trial", trial_start))
app.add_handler(CommandHandler("renew", renew_start))
app.add_handler(CommandHandler("support", support_start))
app.add_handler(CommandHandler("done", support_submit_done))


# Callbacks (home/menu/subscribe)
app.add_handler(CallbackQueryHandler(cb_lang, pattern=r"^lang\|"))
app.add_handler(CallbackQueryHandler(cb_more_info, pattern=r"^more_info$"))
app.add_handler(CallbackQueryHandler(cb_back_home, pattern=r"^back_home$"))
app.add_handler(CallbackQueryHandler(cb_subscribe, pattern=r"^subscribe$"))
app.add_handler(CallbackQueryHandler(cb_pick_pkg, pattern=r"^pkg\|"))
app.add_handler(CallbackQueryHandler(cb_agree, pattern=r"^agree\|"))
app.add_handler(CallbackQueryHandler(cb_paid, pattern=r"^paid\|"))
app.add_handler(CallbackQueryHandler(cb_offers, pattern=r"^offers$"))


# Feature menus
app.add_handler(CallbackQueryHandler(open_trial_cb, pattern=r"^open_trial$"))
app.add_handler(CallbackQueryHandler(open_renew_cb, pattern=r"^open_renew$"))
app.add_handler(CallbackQueryHandler(open_support_cb, pattern=r"^open_support$"))


# Renew flow
app.add_handler(CallbackQueryHandler(renew_pick_package, pattern=r"^renew_pkg:"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, renew_collect_username))
app.add_handler(MessageHandler(filters.CONTACT & filters.ChatType.PRIVATE, renew_collect_phone))


# Trial flow
app.add_handler(CallbackQueryHandler(trial_pick_package, pattern=r"^trial_pkg:"))
app.add_handler(MessageHandler(filters.CONTACT & filters.ChatType.PRIVATE, trial_collect_phone))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, trial_collect_username))
app.add_handler(CallbackQueryHandler(trial_admin_action, pattern=r"^trial_admin:"))
app.add_handler(MessageHandler(filters.REPLY & filters.ChatType.PRIVATE, trial_admin_force_reply))


# Support flow
app.add_handler(CallbackQueryHandler(support_pick_issue, pattern=r"^support_issue:"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, support_collect_username))
app.add_handler(MessageHandler(filters.CONTACT & filters.ChatType.PRIVATE, support_collect_phone))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, support_free_text))
app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, support_collect_screenshot))


app.add_error_handler(on_error)


if WEBHOOK_URL:
app.run_webhook(listen="0.0.0.0", port=int(os.getenv("PORT", "10000")), url_path=BOT_TOKEN, webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
else:
app.run_polling()




if __name__ == "__main__":
main()