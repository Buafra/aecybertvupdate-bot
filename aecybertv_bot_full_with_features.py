# -*- coding: utf-8 -*-
"""
AECyberTV Telegram Bot — MENU FIRST + Renew + Manual Free Trial + Support
- Starts with language → main menu (NO phone request until "I Paid").
- Subscribe flow: choose package → agree → pay → THEN phone request.
- Renew: user picks package, gives username + phone; you get an admin alert.
- Trial (manual): package-based duration, once per phone/month, admin sends creds.
- Support: guided ticket (issue → username → phone → details → optional screenshot).
Requirements: python-telegram-bot==21.4
"""

import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from zoneinfo import ZoneInfo
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, ForceReply
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, CallbackQueryHandler, filters
)

# ------------------------- CONFIG -------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
PHONE_HASH_SALT = os.getenv("PHONE_HASH_SALT", "change-this-salt")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise SystemExit("Missing BOT_TOKEN env var")

# ------------------------- TIME ---------------------------
DUBAI_TZ = ZoneInfo("Asia/Dubai")
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

# ------------------------- FILE STORAGE -------------------
DATA_DIR = Path(".")
TRIALS_FILE = DATA_DIR / "trials.jsonl"
RENEWALS_FILE = DATA_DIR / "renewals.jsonl"
SUPPORT_FILE = DATA_DIR / "support_tickets.jsonl"
CUSTOMERS_FILE = DATA_DIR / "customers.jsonl"

def save_jsonl(path: Path, row: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    next_id = 1
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                next_id = sum(1 for _ in f) + 1
        except Exception:
            next_id = 1
    row = {"id": next_id, **row}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return next_id

def iter_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out

# ------------------------- STATE --------------------------
USER_STATE: Dict[int, Dict[str, Any]] = {}
PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{6,}$")

def set_state(chat_id: int, **kv):
    USER_STATE.setdefault(chat_id, {}).update(kv)

def get_state(chat_id: int) -> Dict[str, Any]:
    return USER_STATE.get(chat_id, {})

def normalize_phone(s: str) -> str:
    s = s.strip()
    if s.startswith("00"):
        s = "+" + s[2:]
    return re.sub(r"[^\d+]", "", s)

def phone_hash(e164: str) -> str:
    import hashlib
    return hashlib.sha256((e164 + PHONE_HASH_SALT).encode()).hexdigest()

def this_year_month() -> str:
    return datetime.now(DUBAI_TZ).strftime("%Y-%m")

# ------------------------- PACKAGES -----------------------
PACKAGES: Dict[str, Dict[str, Any]] = {
    "AECyberTV Kids": {
        "code": "KIDS", "price_aed": 70,
        "details_en": "\n• Kids-safe channels\n• Cartoons & Educational shows\n• Works on 1 device\n",
        "details_ar": "\n• قنوات للأطفال\n• كرتون وبرامج تعليمية\n• يعمل على جهاز واحد\n",
        "payment_url": "https://buy.stripe.com/3cIbJ29I94yA92g2AV5kk04",
    },
    "AECyberTV Casual": {
        "code": "CASUAL", "price_aed": 75,
        "details_en": "\n• 10,000+ Live Channels\n• 70,000+ Movies (VOD)\n• 12,000+ Series\n• Works on 1 device\n",
        "details_ar": "\n• أكثر من 10,000 قناة مباشرة\n• 70,000+ فيلم (VOD)\n• 12,000+ مسلسل\n• يعمل على جهاز واحد\n",
        "payment_url": "https://buy.stripe.com/6oU6oIf2t8OQa6kejD5kk03",
    },
    "AECyberTV Executive": {
        "code": "EXEC", "price_aed": 200,
        "details_en": "\n• 16,000+ Live Channels\n• 24,000+ Movies (VOD)\n• 14,000+ Series\n• 2 devices • SD/HD/FHD/4K\n",
        "details_ar": "\n• 16,000+ قناة مباشرة\n• 24,000+ فيلم (VOD)\n• 14,000+ مسلسل\n• جهازان • SD/HD/FHD/4K\n",
        "payment_url": "https://buy.stripe.com/8x23cw07zghi4M0ejD5kk05",
    },
    "AECyberTV Premium": {
        "code": "PREM", "price_aed": 250,
        "details_en": "\n• Full combo package\n• 65,000+ Live Channels\n• 180,000+ Movies (VOD)\n• 10,000+ Series\n• Priority support\n",
        "details_ar": "\n• باقة كاملة شاملة\n• 65,000+ قناة مباشرة\n• 180,000+ فيلم (VOD)\n• 10,000+ مسلسل\n• دعم أولوية\n",
        "payment_url": "https://buy.stripe.com/eVq00k7A15CE92gdfz5kk01",
    },
}
TRIAL_HOURS = {"KIDS": 8, "CASUAL": 24, "EXEC": 10, "PREM": 24}

# ------------------------- I18N ---------------------------
BRAND = "AECyberTV"
I18N = {
    "pick_lang": {"ar": "اختر اللغة:", "en": "Choose your language:"},
    "lang_ar": {"ar": "العربية", "en": "Arabic"},
    "lang_en": {"ar": "English", "en": "English"},
    "welcome": {"ar": f"مرحباً بك في {BRAND}!\n\nكيف نقدر نساعدك اليوم؟",
                "en": f"Welcome to {BRAND}!\n\nHow can we help you today?"},
    "btn_more_info": {"ar": "📋 معلومات", "en": "📋 More Info"},
    "btn_subscribe": {"ar": "💳 اشتراك", "en": "💳 Subscribe"},
    "btn_offers": {"ar": "🎁 العروض", "en": "🎁 Offers"},
    "btn_agree": {"ar": "✅ أوافق", "en": "✅ I Agree"},
    "btn_back": {"ar": "⬅️ رجوع", "en": "⬅️ Back"},
    "subscribe_pick": {"ar": "اختر الباقة:", "en": "Please choose a package:"},
    "payment_instructions": {
        "ar": "💳 الدفع\n\nاضغط (ادفع الآن) لإتمام الدفع. ثم ارجع واضغط (دفعت).",
        "en": "💳 Payment\n\nTap (Pay Now) to complete payment. Then return and press (I Paid).",
    },
    "btn_pay_now": {"ar": "🔗 ادفع الآن", "en": "🔗 Pay Now"},
    "btn_paid": {"ar": "✅ دفعت", "en": "✅ I Paid"},
    "thank_you": {"ar": f"🎉 شكراً لاختيارك {BRAND}!\nسنتواصل معك قريباً لتفعيل الخدمة.",
                  "en": f"🎉 Thank you for choosing {BRAND}!\nWe’ll contact you soon to activate your account."},
    "breadcrumb_sel": {"ar": "🧩 تم حفظ اختيارك: {pkg} ({price} درهم)",
                       "en": "🧩 Selection saved: {pkg} ({price} AED)"},
    "breadcrumb_paid": {"ar": "🧾 تم الضغط على (دفعت)\n• الباقة: {pkg}\n• الوقت: {ts}",
                        "en": "🧾 Payment confirmation clicked\n• Package: {pkg}\n• Time: {ts}"},
    "phone_request": {
        "ar": "📞 فضلاً شارك رقم هاتفك للتواصل والتفعيل.\nاضغط (مشاركة رقمي) أو اكتب الرقم مع رمز الدولة (مثال: +9715xxxxxxx).",
        "en": "📞 Please share your phone number so we can contact you to activate.\nTap (Share my number), or type it including country code (e.g., +9715xxxxxxx).",
    },
    "btn_share_phone": {"ar": "📲 مشاركة رقمي", "en": "📲 Share my number"},
    "phone_saved": {"ar": "✅ تم حفظ رقمك. سنتواصل معك قريباً.",
                    "en": "✅ Thank you! We saved your number. We'll contact you shortly."},
    "phone_invalid": {
        "ar": "❗️الرقم غير صحيح. اكتب الرقم مع رمز الدولة (مثال: +9715xxxxxxx) أو اضغط (مشاركة رقمي).",
        "en": "❗️That doesn’t look valid. Include country code (e.g., +9715xxxxxxx), or tap (Share my number).",
    },
    "more_info_title": {"ar": "📥 طريقة المشاهدة باستخدام 000 Player", "en": "📥 How to Watch with 000 Player"},
    "more_info_body": {
        "ar": ("1) ثبّت تطبيق 000 Player:\n"
               "   • iPhone/iPad: App Store\n"
               "   • Android/TV: Google Play\n"
               "   • Firestick/Android TV (Downloader): http://aftv.news/6913771\n"
               "   • Web (PC, PlayStation, Xbox): https://my.splayer.in\n\n"
               "2) أدخل رقم السيرفر: 7765\n"
               "3) بعد الدفع والتفعيل، نرسل لك بيانات الدخول."),
        "en": ("1) Install 000 Player:\n"
               "   • iPhone/iPad: App Store\n"
               "   • Android/TV: Google Play\n"
               "   • Firestick/Android TV (Downloader): http://aftv.news/6913771\n"
               "   • Web (PC, PlayStation, Xbox): https://my.splayer.in\n\n"
               "2) Enter Server Number: 7765\n"
               "3) After payment & activation, we will send your login details.")
    },
}

def t(chat_id: int, key: str) -> str:
    lang = USER_STATE.get(chat_id, {}).get("lang", "ar")
    val = I18N.get(key)
    return val.get(lang, val.get("en", "")) if isinstance(val, dict) else str(val)

# ------------------------- KEYBOARDS ----------------------
def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(I18N["lang_ar"]["ar"], callback_data="lang|ar"),
         InlineKeyboardButton(I18N["lang_en"]["en"], callback_data="lang|en")]
    ])

def main_menu_kb(chat_id: int) -> InlineKeyboardMarkup:
    lang = USER_STATE.get(chat_id, {}).get("lang", "ar")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(I18N["btn_more_info"][lang], callback_data="more_info"),
         InlineKeyboardButton(I18N["btn_subscribe"][lang], callback_data="subscribe")],
        [InlineKeyboardButton("🔁 Renew", callback_data="open_renew"),
         InlineKeyboardButton("🎁 Free Trial", callback_data="open_trial")],
        [InlineKeyboardButton("🛟 Support", callback_data="open_support"),
         InlineKeyboardButton(I18N["btn_offers"][lang], callback_data="offers")]
    ])

def packages_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(pkg, callback_data=f"pkg|{pkg}")] for pkg in PACKAGES.keys()]
    rows.append([InlineKeyboardButton(I18N["btn_back"]["ar"] + " / " + I18N["btn_back"]["en"], callback_data="back_home")])
    return InlineKeyboardMarkup(rows)

def agree_kb(chat_id: int, pkg_name: str) -> InlineKeyboardMarkup:
    lang = USER_STATE.get(chat_id, {}).get("lang", "ar")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(I18N["btn_agree"][lang], callback_data=f"agree|{pkg_name}")],
        [InlineKeyboardButton(I18N["btn_back"][lang], callback_data="subscribe")],
    ])

def pay_kb(chat_id: int, pkg_name: str) -> InlineKeyboardMarkup:
    lang = USER_STATE.get(chat_id, {}).get("lang", "ar")
    pay_url = PACKAGES[pkg_name]["payment_url"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(I18N["btn_pay_now"][lang], url=pay_url)],
        [InlineKeyboardButton(I18N["btn_paid"][lang], callback_data=f"paid|{pkg_name}")],
        [InlineKeyboardButton(I18N["btn_back"][lang], callback_data="subscribe")],
    ])

def packages_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👶 Kids / أطفال", callback_data=f"{prefix}:KIDS")],
        [InlineKeyboardButton("🙂 Casual / كاجوال", callback_data=f"{prefix}:CASUAL")],
        [InlineKeyboardButton("🧑‍💼 Executive / تنفيذي", callback_data=f"{prefix}:EXEC")],
        [InlineKeyboardButton("⭐ Premium / بريميوم", callback_data=f"{prefix}:PREM")],
    ])

# ------------------------- HELPERS ------------------------
def pkg_details_for_lang(pkg_name: str, lang: str) -> str:
    p = PACKAGES[pkg_name]
    return p["details_ar"] if lang == "ar" else p["details_en"]

def is_admin(user_id: int) -> bool:
    try:
        return ADMIN_CHAT_ID is not None and int(ADMIN_CHAT_ID) == int(user_id)
    except Exception:
        return False

# ------------------------- COMMANDS -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    # Menu-first: ask language only
    if update.message:
        await update.message.reply_text(I18N["pick_lang"]["ar"], reply_markup=lang_kb())
    else:
        await context.bot.send_message(chat_id=chat_id, text=I18N["pick_lang"]["ar"], reply_markup=lang_kb())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Used to submit support ticket after (optional) screenshot
    await support_submit_done(update, context)

# ------------------------- CALLBACKS (HOME) ---------------
async def cb_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    _, lang = q.data.split("|")
    set_state(update.effective_chat.id, lang=lang)
    await context.bot.send_message(chat_id=update.effective_chat.id,
                                   text=I18N["welcome"][lang],
                                   reply_markup=main_menu_kb(update.effective_chat.id))

async def cb_more_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    chat_id = update.effective_chat.id
    lang = get_state(chat_id).get("lang", "ar")
    title = I18N["more_info_title"][lang]
    body = I18N["more_info_body"][lang]
    await context.bot.send_message(chat_id=chat_id, text=f"<b>{title}</b>\n\n{body}", parse_mode="HTML")

async def cb_back_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    chat_id = update.effective_chat.id
    lang = get_state(chat_id).get("lang", "ar")
    await context.bot.send_message(chat_id=chat_id, text=I18N["welcome"][lang], reply_markup=main_menu_kb(chat_id))

async def cb_offers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await context.bot.send_message(chat_id=update.effective_chat.id, text="لا توجد عروض حالياً / No offers right now.")

# ------------------------- SUBSCRIBE FLOW -----------------
async def cb_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    chat_id = update.effective_chat.id
    lang = get_state(chat_id).get("lang", "ar")
    await context.bot.send_message(chat_id=chat_id, text=I18N["subscribe_pick"][lang], reply_markup=packages_kb())

async def cb_pick_pkg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    chat_id = update.effective_chat.id
    _, pkg_name = q.data.split("|")
    set_state(chat_id, chosen_pkg=pkg_name)
    lang = get_state(chat_id).get("lang", "ar")
    details = pkg_details_for_lang(pkg_name, lang)
    price = PACKAGES[pkg_name]["price_aed"]
    notes = (
        "✅ الشروط والملاحظات\n\n• التفعيل بعد تأكيد الدفع.\n• حساب واحد لكل جهاز ما لم تذكر الباقة غير ذلك.\n• الاستخدام على عدة أجهزة قد يسبب تقطيع أو إيقاف الخدمة.\n• لا توجد استرجاعات بعد التفعيل.\n\nهل توافق على المتابعة؟"
        if lang == "ar" else
        "✅ Terms & Notes\n\n• Activation after payment confirmation.\n• One account per device unless package allows more.\n• Using multiple devices may cause buffering or stop service.\n• No refunds after activation.\n\nDo you agree to proceed?"
    )
    await context.bot.send_message(chat_id=chat_id,
                                   text=I18N["breadcrumb_sel"][lang].format(pkg=pkg_name, price=price) +
                                        "\n" + details + "\n\n" + notes,
                                   reply_markup=agree_kb(chat_id, pkg_name))

async def cb_agree(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    chat_id = update.effective_chat.id
    _, pkg_name = q.data.split("|")
    lang = get_state(chat_id).get("lang", "ar")
    await context.bot.send_message(chat_id=chat_id,
                                   text=I18N["payment_instructions"][lang],
                                   reply_markup=pay_kb(chat_id, pkg_name))

async def cb_paid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    chat_id = update.effective_chat.id
    _, pkg_name = q.data.split("|")
    ts = _utcnow().astimezone(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    set_state(chat_id, awaiting_phone=True)  # ask phone ONLY now
    lang = get_state(chat_id).get("lang", "ar")
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton(I18N["btn_share_phone"][lang], request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=I18N["breadcrumb_paid"][lang].format(pkg=pkg_name, ts=ts) + "\n\n" + I18N["phone_request"][lang],
        reply_markup=kb
    )

# ------------------------- FEATURE OPENERS ----------------
async def open_renew_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await renew_start(update, context)

async def open_trial_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await trial_start(update, context)

async def open_support_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await support_start(update, context)

# ------------------------- RENEW --------------------------
async def renew_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await ctx.bot.send_message(chat_id=chat_id, text="🔁 **Renew**\nاختر الباقة للتجديد", reply_markup=packages_keyboard("renew_pkg"))

async def renew_pick_package(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    code = q.data.split(":")[1]
    ctx.user_data["renew_stage"] = "await_username"
    ctx.user_data["renew_pkg"] = code
    await q.message.reply_text("أدخل اسم المستخدم الخاص بك\nEnter your username", reply_markup=ReplyKeyboardRemove())

# ------------------------- TRIAL (manual) -----------------
async def trial_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await ctx.bot.send_message(chat_id=chat_id, text="🎁 **Free Trial**\nاختر باقتك للتجربة / Choose your trial package",
                               reply_markup=packages_keyboard("trial_pkg"))

async def trial_pick_package(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    code = q.data.split(":")[1]
    ctx.user_data["trial_stage"] = "await_phone"
    ctx.user_data["trial_pkg"] = code
    hours = TRIAL_HOURS[code]
    contact_btn = KeyboardButton("📞 مشاركة الهاتف / Share Phone", request_contact=True)
    await q.message.reply_text(
        f"⏱️ Trial duration: {hours} hours\n\nمن فضلك شارك رقم هاتفك للتحقق (مرة واحدة كل شهر)\nPlease share your phone number to verify (once per month)",
        reply_markup=ReplyKeyboardMarkup([[contact_btn]], resize_keyboard=True, one_time_keyboard=True)
    )

async def trial_admin_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not is_admin(update.effective_user.id):
        return await q.answer("Admins only", show_alert=True)
    _, action, tid = q.data.split(":")
    tid = int(tid)
    if action == "send":
        await q.message.reply_text("📩 Paste the trial credentials to send to the user.", reply_markup=ForceReply(selective=True))
        ctx.user_data["awaiting_trial_creds_for"] = tid
    else:
        rows = iter_jsonl(TRIALS_FILE)
        for r in rows:
            if int(r.get("id", 0)) == tid:
                r["status"] = "rejected"
        with TRIALS_FILE.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        await q.message.edit_text(q.message.text + "\n\n❌ Rejected")

async def trial_admin_force_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    tid = ctx.user_data.pop("awaiting_trial_creds_for", None)
    if not tid:
        return
    creds = (update.message.text or "").strip()
    user_chat_id: Optional[int] = None
    pkg = "CASUAL"
    exp_dt = datetime.now(DUBAI_TZ) + timedelta(hours=24)
    rows = iter_jsonl(TRIALS_FILE)
    for r in rows:
        if int(r.get("id", 0)) == int(tid):
            user_chat_id = int(r["tg_user_id"])
            pkg = r["package_code"]
            exp_dt = datetime.fromisoformat(r["expires_at"]).astimezone(DUBAI_TZ)
            r["status"] = "granted"
            r["granted_at"] = datetime.now(DUBAI_TZ).isoformat()
    with TRIALS_FILE.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if user_chat_id:
        await ctx.bot.send_message(
            chat_id=user_chat_id,
            text=(f"✅ تم تفعيل تجربة {pkg}\nبيانات الدخول:\n{creds}\n\n"
                  f"⏳ الصلاحية حتى: {exp_dt:%Y-%m-%d %H:%M} بتوقيت الإمارات\nاستمتع بالمشاهدة 🎬")
        )
        await update.message.reply_text("✅ Sent to user")

# ------------------------- SUPPORT -----------------------
SUPPORT_ISSUES = [
    ("LOGIN", "لا أستطيع تسجيل الدخول / Can’t log in"),
    ("FREEZE", "تقطيع/تجميد / Freezing/Buffering"),
    ("PAY", "مشكلة الدفع / Payment issue"),
    ("EXPIRE", "انتهى الاشتراك / Subscription expired"),
    ("SETUP", "إعداد التطبيق (M3U/IBO) / Player setup"),
    ("OTHER", "أخرى / Other"),
]
def support_issues_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(lbl, callback_data=f"support_issue:{code}") ] for code, lbl in SUPPORT_ISSUES])

async def support_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await ctx.bot.send_message(chat_id=chat_id, text="🛟 اختر المشكلة / Choose an issue", reply_markup=support_issues_keyboard())

async def support_pick_issue(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    code = q.data.split(":")[1]
    ctx.user_data["support_stage"] = "await_username"
    ctx.user_data["support_issue_code"] = code
    await q.message.reply_text("أدخل اسم المستخدم\nEnter your username", reply_markup=ReplyKeyboardRemove())

# ------------------------- ROUTERS (TEXT / CONTACT / PHOTO)
async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Single text router to avoid handler collisions.
    Checks user_data flags to know which step we’re in.
    """
    chat_id = update.effective_chat.id
    txt = (update.message.text or "").strip()

    # SUBSCRIBE phone typed?
    st = get_state(chat_id)
    if st.get("awaiting_phone"):
        lang = st.get("lang", "ar")
        if not PHONE_RE.match(txt):
            kb = ReplyKeyboardMarkup(
                [[KeyboardButton(I18N["btn_share_phone"][lang], request_contact=True)]],
                resize_keyboard=True, one_time_keyboard=True
            )
            return await update.message.reply_text(I18N["phone_invalid"][lang], reply_markup=kb)
        phone = normalize_phone(txt)
        row = {
            "chat_id": chat_id,
            "tg_user_id": update.effective_user.id,
            "tg_username": update.effective_user.username,
            "package": st.get("chosen_pkg"),
            "phone": phone,
            "ts": datetime.now(DUBAI_TZ).isoformat(timespec="seconds"),
        }
        save_jsonl(CUSTOMERS_FILE, row)
        set_state(chat_id, awaiting_phone=False, chosen_pkg=None)
        return await update.message.reply_text(I18N["phone_saved"][lang], reply_markup=ReplyKeyboardRemove())

    # RENEW username collection
    if ctx.user_data.get("renew_stage") == "await_username":
        ctx.user_data["renew_username"] = txt
        ctx.user_data["renew_stage"] = "await_phone"
        contact_btn = KeyboardButton("📞 مشاركة الهاتف / Share Phone", request_contact=True)
        return await update.message.reply_text("شارك رقم هاتفك للتأكيد / Share your phone for confirmation",
                                               reply_markup=ReplyKeyboardMarkup([[contact_btn]], resize_keyboard=True, one_time_keyboard=True))

    # TRIAL username collection (after phone)
    if ctx.user_data.get("trial_stage") == "await_username" and ctx.user_data.get("trial_phone_e164"):
        code = ctx.user_data.get("trial_pkg")
        e164 = ctx.user_data.get("trial_phone_e164")
        hours = TRIAL_HOURS[code]
        expires_at = datetime.now(DUBAI_TZ) + timedelta(hours=hours)
        trial_id = save_jsonl(TRIALS_FILE, {
            "tg_user_id": chat_id,
            "tg_username": update.effective_user.username,
            "package_code": code,
            "phone_e164": e164,
            "phone_hash": phone_hash(e164),
            "username_text": txt,
            "expires_at": expires_at.isoformat(),
            "requested_at": datetime.now(DUBAI_TZ).isoformat(),
            "year_month": this_year_month(),
            "status": "pending",
        })
        await update.message.reply_text("✅ تم تسجيل طلب التجربة — سيتم إرسال بيانات الدخول قريبًا.\n\n✅ Trial request received — credentials will be sent shortly.")
        if ADMIN_CHAT_ID:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Send Trial", callback_data=f"trial_admin:send:{trial_id}"),
                 InlineKeyboardButton("✖️ Reject", callback_data=f"trial_admin:reject:{trial_id}")]
            ])
            await ctx.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=(
                "🎁 NEW TRIAL REQUEST\n"
                f"User: @{update.effective_user.username} ({chat_id})\n"
                f"Pkg: {code}\nPhone: {e164}\nUsername: {txt}\n"
                f"Expires if now: {expires_at:%Y-%m-%d %H:%M} Asia/Dubai"
            ), reply_markup=kb)
        ctx.user_data.pop("trial_stage", None)
        ctx.user_data.pop("trial_pkg", None)
        ctx.user_data.pop("trial_phone_e164", None)
        return

    # SUPPORT username first, then details (after phone we use separate route)
    if ctx.user_data.get("support_stage") == "await_username":
        ctx.user_data["support_username"] = txt
        ctx.user_data["support_stage"] = "await_phone"
        contact_btn = KeyboardButton("📞 مشاركة الهاتف / Share Phone", request_contact=True)
        return await update.message.reply_text("شارك رقم هاتفك\nShare your phone number",
                                               reply_markup=ReplyKeyboardMarkup([[contact_btn]], resize_keyboard=True, one_time_keyboard=True))
    if ctx.user_data.get("support_stage") == "await_details":
        ctx.user_data["support_details"] = txt
        ctx.user_data["support_stage"] = "await_optional_screenshot"
        return await update.message.reply_text("يمكنك الآن إرسال لقطة شاشة (اختياري) أو أرسل /done للإرسال.\nYou can send a screenshot now (optional) or send /done to submit.")

async def contact_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Single contact router for subscribe (awaiting_phone), renew, trial, support.
    """
    chat_id = update.effective_chat.id
    e164 = normalize_phone(update.message.contact.phone_number)

    # SUBSCRIBE phone collection
    st = get_state(chat_id)
    if st.get("awaiting_phone"):
        row = {
            "chat_id": chat_id,
            "tg_user_id": update.effective_user.id,
            "tg_username": update.effective_user.username,
            "package": st.get("chosen_pkg"),
            "phone": e164,
            "ts": datetime.now(DUBAI_TZ).isoformat(timespec="seconds"),
        }
        save_jsonl(CUSTOMERS_FILE, row)
        set_state(chat_id, awaiting_phone=False, chosen_pkg=None)
        lang = st.get("lang", "ar")
        return await update.message.reply_text(I18N["phone_saved"][lang], reply_markup=ReplyKeyboardRemove())

    # RENEW phone
    if ctx.user_data.get("renew_stage") == "await_phone":
        renewal_id = save_jsonl(RENEWALS_FILE, {
            "tg_user_id": update.effective_user.id,
            "tg_username": update.effective_user.username,
            "package_code": ctx.user_data.get("renew_pkg"),
            "username_text": ctx.user_data.get("renew_username", "-"),
            "phone_e164": e164,
            "created_at": datetime.now(DUBAI_TZ).isoformat(),
        })
        await update.message.reply_text("✅ تم تسجيل طلب التجديد — سنتواصل معك قريبًا\n\n✅ Renewal request received — we’ll contact you shortly.",
                                        reply_markup=ReplyKeyboardRemove())
        if ADMIN_CHAT_ID:
            await ctx.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=(
                "🔁 NEW RENEWAL\n"
                f"Pkg: {ctx.user_data.get('renew_pkg')}\n"
                f"User: @{update.effective_user.username} ({update.effective_user.id})\n"
                f"Username: {ctx.user_data.get('renew_username','-')}\n"
                f"Phone: {e164}\nRenewal ID: {renewal_id}"
            ))
        ctx.user_data.pop("renew_stage", None)
        ctx.user_data.pop("renew_pkg", None)
        ctx.user_data.pop("renew_username", None)
        return

    # TRIAL phone (1/month per phone)
    if ctx.user_data.get("trial_stage") == "await_phone":
        ph = phone_hash(e164)
        ym = this_year_month()
        for row in iter_jsonl(TRIALS_FILE):
            if row.get("phone_hash") == ph and row.get("year_month") == ym:
                return await update.message.reply_text("عذرًا، استخدمت التجربة المجانية هذا الشهر. جرّب الشهر القادم.\nSorry, you already used this month’s free trial.",
                                                       reply_markup=ReplyKeyboardRemove())
        ctx.user_data["trial_phone_e164"] = e164
        ctx.user_data["trial_stage"] = "await_username"
        return await update.message.reply_text("أدخل اسم المستخدم الخاص بك (للتطبيق)\nPlease enter your username (for the player)",
                                               reply_markup=ReplyKeyboardRemove())

    # SUPPORT phone
    if ctx.user_data.get("support_stage") == "await_phone":
        ctx.user_data["support_phone_e164"] = e164
        ctx.user_data["support_stage"] = "await_details"
        return await update.message.reply_text("صف المشكلة بالتفصيل (يمكنك إرسال لقطة شاشة بعدها)\nDescribe the issue (you may send a screenshot after).",
                                               reply_markup=ReplyKeyboardRemove())

async def photo_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # SUPPORT optional screenshot
    if ctx.user_data.get("support_stage") == "await_optional_screenshot":
        phs = update.message.photo
        if phs:
            ctx.user_data["support_photo_file_id"] = phs[-1].file_id
            await update.message.reply_text("✅ Screenshot attached. Send /done to submit.")

# ------------------------- SUPPORT SUBMIT -----------------
async def support_submit_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if ctx.user_data.get("support_issue_code") is None:
        return
    ticket_id = save_jsonl(SUPPORT_FILE, {
        "tg_user_id": update.effective_user.id,
        "tg_username": update.effective_user.username,
        "issue_code": ctx.user_data.get("support_issue_code"),
        "username_text": ctx.user_data.get("support_username", "-"),
        "phone_e164": ctx.user_data.get("support_phone_e164", "-"),
        "details": ctx.user_data.get("support_details", "-"),
        "photo_file_id": ctx.user_data.get("support_photo_file_id"),
        "created_at": datetime.now(DUBAI_TZ).isoformat(),
    })
    await update.message.reply_text(f"✅ تم إنشاء تذكرة الدعم #{ticket_id} — سنعاود الاتصال بك قريبًا.\n✅ Support ticket #{ticket_id} created — we’ll follow up shortly.")
    if ADMIN_CHAT_ID:
        text = (
            "🛟 NEW SUPPORT TICKET\n"
            f"Ticket #{ticket_id}\n"
            f"Issue: {ctx.user_data.get('support_issue_code')}\n"
            f"User: @{update.effective_user.username} ({update.effective_user.id})\n"
            f"Username: {ctx.user_data.get('support_username','-')}\n"
            f"Phone: {ctx.user_data.get('support_phone_e164','-')}\n"
            f"Details: {ctx.user_data.get('support_details','-')}"
        )
        if ctx.user_data.get("support_photo_file_id"):
            await update.message.bot.send_photo(chat_id=int(ADMIN_CHAT_ID), photo=ctx.user_data["support_photo_file_id"], caption=text)
        else:
            await update.message.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=text)
    # clear support keys
    for k in list(ctx.user_data.keys()):
        if k.startswith("support_") or k in {"support_stage"}:
            ctx.user_data.pop(k, None)

# ------------------------- ERROR HANDLER ------------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Unhandled error", exc_info=context.error)

# ------------------------- MAIN ---------------------------
def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("done", done_cmd))

    # Home / menu callbacks
    app.add_handler(CallbackQueryHandler(cb_lang, pattern=r"^lang\|"))
    app.add_handler(CallbackQueryHandler(cb_more_info, pattern=r"^more_info$"))
    app.add_handler(CallbackQueryHandler(cb_back_home, pattern=r"^back_home$"))
    app.add_handler(CallbackQueryHandler(cb_offers, pattern=r"^offers$"))

    # Subscribe flow
    app.add_handler(CallbackQueryHandler(cb_subscribe, pattern=r"^subscribe$"))
    app.add_handler(CallbackQueryHandler(cb_pick_pkg, pattern=r"^pkg\|"))
    app.add_handler(CallbackQueryHandler(cb_agree, pattern=r"^agree\|"))
    app.add_handler(CallbackQueryHandler(cb_paid, pattern=r"^paid\|"))

    # Feature openers
    app.add_handler(CallbackQueryHandler(open_renew_cb, pattern=r"^open_renew$"))
    app.add_handler(CallbackQueryHandler(open_trial_cb, pattern=r"^open_trial$"))
    app.add_handler(CallbackQueryHandler(open_support_cb, pattern=r"^open_support$"))

    # Renew flow
    app.add_handler(CallbackQueryHandler(renew_pick_package, pattern=r"^renew_pkg:"))

    # Trial flow
    app.add_handler(CallbackQueryHandler(trial_pick_package, pattern=r"^trial_pkg:"))
    app.add_handler(CallbackQueryHandler(trial_admin_action, pattern=r"^trial_admin:"))
    app.add_handler(MessageHandler(filters.REPLY & filters.ChatType.PRIVATE, trial_admin_force_reply))

    # Support flow
    app.add_handler(CallbackQueryHandler(support_pick_issue, pattern=r"^support_issue:"))

    # Routers (order matters)
    app.add_handler(MessageHandler(filters.CONTACT & filters.ChatType.PRIVATE, contact_router))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, photo_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, text_router))

    app.add_error_handler(on_error)

    if WEBHOOK_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("PORT", "10000")),
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        )
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
