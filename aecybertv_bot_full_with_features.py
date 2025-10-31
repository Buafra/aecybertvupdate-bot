# -*- coding: utf-8 -*-
"""
AECyberTV Telegram Sales Bot — Menu-first, edit-in-place
Updates per request:
  • Free Trial: no username; package -> phone -> logged + admin notified (monthly limit by phone)
  • Renew: same as Subscribe (Terms -> Agree -> Pay -> then Username -> Phone -> thank you + admin)
  • Support: issue -> Username -> Details -> (optional screenshot) -> thank you + ask for phone -> admin
Requires:
    python-telegram-bot==21.4
"""

import os
import re
import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple

from zoneinfo import ZoneInfo  # Python 3.9+

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, Contact, ForceReply
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, CallbackQueryHandler, filters
)

# ------------------------- CONFIG -------------------------
def env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        raise ValueError(f"Environment variable {name} must be an integer, got: {v!r}")

BOT_TOKEN = os.getenv("BOT_TOKEN")  # required
ADMIN_CHAT_ID = env_int("ADMIN_CHAT_ID")  # optional
WEBHOOK_URL = os.getenv("WEBHOOK_URL")    # optional
PHONE_HASH_SALT = os.getenv("PHONE_HASH_SALT", "change-this-salt")

if not BOT_TOKEN:
    logging.basicConfig(level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.error("Missing BOT_TOKEN env var. Set BOT_TOKEN before running.")
    sys.exit(1)

# ------------------------- TIME -------------------------
DUBAI_TZ = ZoneInfo("Asia/Dubai")

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _parse_iso(ts: str) -> datetime:
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def dubai_range_to_utc_iso(start_local: datetime, end_local: datetime) -> Tuple[str, str]:
    if start_local.tzinfo is None:
        start_local = start_local.replace(tzinfo=DUBAI_TZ)
    if end_local.tzinfo is None:
        end_local = end_local.replace(tzinfo=DUBAI_TZ)
    return _iso_utc(start_local), _iso_utc(end_local)

# ------------------------- PACKAGES -------------------------
PACKAGES: Dict[str, Dict[str, Any]] = {
    "AECyberTV Kids": {
        "code": "kids",
        "price_aed": 70,
        "details_en": "\n• Kids-safe channels\n• Cartoons & Educational shows\n• Works on 1 device\n",
        "details_ar": "\n• قنوات للأطفال\n• كرتون وبرامج تعليمية\n• يعمل على جهاز واحد\n",
        "payment_url": "https://buy.stripe.com/3cIbJ29I94yA92g2AV5kk04",
    },
    "AECyberTV Casual": {
        "code": "casual",
        "price_aed": 75,
        "details_en": "\n• 10,000+ Live Channels\n• 70,000+ Movies (VOD)\n• 12,000+ Series\n• Works on 1 device\n",
        "details_ar": "\n• أكثر من 10,000 قناة مباشرة\n• 70,000+ فيلم (VOD)\n• 12,000+ مسلسل\n• يعمل على جهاز واحد\n",
        "payment_url": "https://buy.stripe.com/6oU6oIf2t8OQa6kejD5kk03",
    },
    "AECyberTV Executive": {
        "code": "executive",
        "price_aed": 200,
        "details_en": "\n• 16,000+ Live Channels\n• 24,000+ Movies (VOD)\n• 14,000+ Series\n• 2 devices • SD/HD/FHD/4K\n",
        "details_ar": "\n• 16,000+ قناة مباشرة\n• 24,000+ فيلم (VOD)\n• 14,000+ مسلسل\n• جهازان • SD/HD/FHD/4K\n",
        "payment_url": "https://buy.stripe.com/8x23cw07zghi4M0ejD5kk05",
    },
    "AECyberTV Premium": {
        "code": "premium",
        "price_aed": 250,
        "details_en": "\n• Full combo package\n• 65,000+ Live Channels\n• 180,000+ Movies (VOD)\n• 10,000+ Series\n• Priority support\n",
        "details_ar": "\n• باقة كاملة شاملة\n• 65,000+ قناة مباشرة\n• 180,000+ فيلم (VOD)\n• 10,000+ مسلسل\n• دعم أولوية\n",
        "payment_url": "https://buy.stripe.com/eVq00k7A15CE92gdfz5kk01",
    },
}
TRIAL_HOURS = {"kids": 8, "casual": 24, "executive": 10, "premium": 24}

def code_to_pkgname(code: str) -> Optional[str]:
    for name, meta in PACKAGES.items():
        if meta["code"] == code:
            return name
    return None

# ------------------------- EMBEDDED OFFERS -------------------------
def build_embedded_offers() -> List[Dict[str, Any]]:
    shared_cta = "https://buy.stripe.com/bJedRa6vXe9aa6k1wR5kk06"
    body_en = ("📺 Over 52,300 Live Channels\n🎬 Over 209,700 Movies (VOD)\n📂 Over 11,500 Series\n🌍 Total: ≈ 273,500+")
    body_ar = ("📺 أكثر من 52,300 قناة مباشرة\n🎬 أكثر من 209,700 فيلم (VOD)\n📂 أكثر من 11,500 مسلسل\n🌍 الإجمالي: ≈ 273,500+")

    h_start_utc, h_end_utc = dubai_range_to_utc_iso(datetime(2025,10,24,0,0,tzinfo=DUBAI_TZ), datetime(2025,11,7,23,59,59,tzinfo=DUBAI_TZ))
    halloween = {"id":"halloween2025","title_en":"🎃 Halloween Offer — Limited Time","title_ar":"🎃 عرض الهالوين — لفترة محدودة",
                 "body_en":"Valid until first week of Nov 2025.\n\n"+body_en,"body_ar":"ساري حتى الأسبوع الأول من نوفمبر 2025.\n\n"+body_ar,
                 "cta_url":shared_cta,"start_at":h_start_utc,"end_at":h_end_utc,"priority":50}

    n_start_utc, n_end_utc = dubai_range_to_utc_iso(datetime(2025,11,27,0,0,tzinfo=DUBAI_TZ), datetime(2025,12,10,23,59,59,tzinfo=DUBAI_TZ))
    national_day = {"id":"uae_national_day_2025","title_en":"🇦🇪 UAE National Day — Special Offer","title_ar":"🇦🇪 عرض اليوم الوطني — عرض خاص",
                    "body_en":body_en,"body_ar":body_ar,"cta_url":shared_cta,"start_at":n_start_utc,"end_at":n_end_utc,"priority":100}

    y_start_utc, y_end_utc = dubai_range_to_utc_iso(datetime(2025,12,25,0,0,tzinfo=DUBAI_TZ), datetime(2026,1,10,23,59,59,tzinfo=DUBAI_TZ))
    new_year = {"id":"new_year_2026","title_en":"🎉 New Year Offer — Limited Time","title_ar":"🎉 عرض رأس السنة — لفترة محدودة",
                "body_en":body_en,"body_ar":body_ar,"cta_url":shared_cta,"start_at":y_start_utc,"end_at":y_end_utc,"priority":90}
    return sorted([national_day, new_year, halloween], key=lambda x: int(x.get("priority", 0)), reverse=True)

OFFERS_ALL: List[Dict[str, Any]] = []

def active_offers(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    if now is None: now = _utcnow()
    acts = []
    for o in OFFERS_ALL:
        try:
            if _parse_iso(o["start_at"]) <= now <= _parse_iso(o["end_at"]):
                acts.append(o)
        except Exception:
            continue
    acts.sort(key=lambda x: (int(x.get("priority", 0))*-1, x.get("start_at","")))
    return acts

# ------------------------- FILES -------------------------
DATA_DIR = Path(".")
TRIALS_FILE = DATA_DIR / "trials.jsonl"
RENEWALS_FILE = DATA_DIR / "renewals.jsonl"
SUPPORT_FILE = DATA_DIR / "support_tickets.jsonl"
HISTORY_FILE = Path("customers.jsonl")

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

# ------------------------- STATE -------------------------
USER_STATE: Dict[int, Dict[str, Any]] = {}

PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{6,}$")

def normalize_phone(s: str) -> str:
    s = s.strip()
    if s.startswith("00"):
        s = "+" + s[2:]
    return re.sub(r"[^\d+]", "", s)

def set_state(chat_id: int, **kv):
    st = USER_STATE.setdefault(chat_id, {})
    st.update(kv)

def get_state(chat_id: int) -> Dict[str, Any]:
    return USER_STATE.get(chat_id, {})

def get_lang(chat_id: int) -> str:
    return USER_STATE.get(chat_id, {}).get("lang", "ar")  # default Arabic

def phone_hash(e164: str) -> str:
    import hashlib
    return hashlib.sha256((e164 + PHONE_HASH_SALT).encode()).hexdigest()

# ------------------------- I18N -------------------------
BRAND = "AECyberTV"
I18N = {
    "pick_lang": {"ar": "اختر اللغة:", "en": "Choose your language:"},
    "lang_ar": {"ar": "العربية", "en": "Arabic"},
    "lang_en": {"ar": "English", "en": "English"},
    "welcome": {"ar": f"مرحباً بك في {BRAND}!\n\nكيف نقدر نساعدك اليوم؟", "en": f"Welcome to {BRAND}!\n\nHow can we help you today?"},
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
    "btn_more_info": {"ar": "📋 معلومات", "en": "📋 More Info"},
    "btn_subscribe": {"ar": "💳 اشتراك", "en": "💳 Subscribe"},
    "btn_offers": {"ar": "🎁 العروض", "en": "🎁 Offers"},
    "btn_agree": {"ar": "✅ أوافق", "en": "✅ I Agree"},
    "btn_back": {"ar": "⬅️ رجوع", "en": "⬅️ Back"},
    "subscribe_pick": {"ar": "اختر الباقة:", "en": "Please choose a package:"},
    "terms": {
        "ar": ("✅ الشروط والملاحظات\n\n"
               "• التفعيل بعد تأكيد الدفع.\n"
               "• حساب واحد لكل جهاز ما لم تذكر الباقة غير ذلك.\n"
               "• الاستخدام على عدة أجهزة قد يسبب تقطيع أو إيقاف الخدمة.\n"
               "• لا توجد استرجاعات بعد التفعيل.\n\n"
               "هل توافق على المتابعة؟"),
        "en": ("✅ Terms & Notes\n\n"
               "• Activation after payment confirmation.\n"
               "• One account per device unless package allows more.\n"
               "• Using multiple devices may cause buffering or stop service.\n"
               "• No refunds after activation.\n\n"
               "Do you agree to proceed?")
    },
    "payment_instructions": {
        "ar": "💳 الدفع\n\nاضغط (ادفع الآن) لإتمام الدفع. ثم ارجع واضغط (دفعت).",
        "en": "💳 Payment\n\nTap (Pay Now) to complete payment. Then return and press (I Paid).",
    },
    "btn_pay_now": {"ar": "🔗 ادفع الآن", "en": "🔗 Pay Now"},
    "btn_paid": {"ar": "✅ دفعت", "en": "✅ I Paid"},
    "thank_you": {"ar": f"🎉 شكراً لاختيارك {BRAND}!\nسنتواصل معك قريباً لتفعيل الخدمة.", "en": f"🎉 Thank you for choosing {BRAND}!\nWe’ll contact you soon to activate your account."},
    "breadcrumb_sel": {"ar": "🧩 تم حفظ اختيارك: {pkg} ({price} درهم)", "en": "🧩 Selection saved: {pkg} ({price} AED)"},
    "breadcrumb_agree": {"ar": "✅ وافق على المتابعة: {pkg}", "en": "✅ Agreed to proceed: {pkg}"},
    "breadcrumb_paid": {"ar": "🧾 تم الضغط على (دفعت)\n• الباقة: {pkg}\n• الوقت: {ts}", "en": "🧾 Payment confirmation clicked\n• Package: {pkg}\n• Time: {ts}"},
    "phone_request": {
        "ar": "📞 فضلاً شارك رقم هاتفك للتواصل والتفعيل.\nاضغط (مشاركة رقمي) أو اكتب الرقم مع رمز الدولة (مثال: +9715xxxxxxx).",
        "en": "📞 Please share your phone number so we can contact you to activate.\nTap (Share my number) below, or type it including country code (e.g., +9715xxxxxxx).",
    },
    "btn_share_phone": {"ar": "📲 مشاركة رقمي", "en": "📲 Share my number"},
    "phone_saved": {"ar": "✅ تم حفظ رقمك. سنتواصل معك قريباً.", "en": "✅ Thank you! We saved your number. We'll contact you shortly."},
    "phone_invalid": {"ar": "❗️الرقم غير صحيح. اكتب الرقم مع رمز الدولة (مثال: +9715xxxxxxx) أو اضغط (مشاركة رقمي).", "en": "❗️That doesn’t look valid. Include country code (e.g., +9715xxxxxxx), or tap (Share my number)."},
}

def t(chat_id: int, key: str) -> str:
    lang = get_lang(chat_id)
    val = I18N.get(key)
    if isinstance(val, dict): return val.get(lang, val.get("en", ""))
    return str(val)

# ------------------------- KEYBOARDS -------------------------
def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(I18N["lang_ar"]["ar"], callback_data="lang|ar"),
                                  InlineKeyboardButton(I18N["lang_en"]["en"], callback_data="lang|en")]])

def main_menu_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_more_info"), callback_data="more_info"),
         InlineKeyboardButton(t(chat_id, "btn_subscribe"), callback_data="subscribe")],
        [InlineKeyboardButton("🔁 Renew", callback_data="open_renew"),
         InlineKeyboardButton("🎁 Free Trial", callback_data="open_trial")],
        [InlineKeyboardButton("🛟 Support", callback_data="open_support"),
         InlineKeyboardButton(t(chat_id, "btn_offers"), callback_data="offers")]
    ])

def packages_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(pkg, callback_data=f"pkg|{pkg}")] for pkg in PACKAGES.keys()]
    rows.append([InlineKeyboardButton(I18N["btn_back"]["ar"] + " / " + I18N["btn_back"]["en"], callback_data="back_home")])
    return InlineKeyboardMarkup(rows)

def agree_kb(chat_id: int, key: str, flow: str) -> InlineKeyboardMarkup:
    # flow: "sub" uses pkg name; "renew" uses code
    cb = f"{'agree' if flow=='sub' else 'renew_agree'}|{key}"
    back_cb = "subscribe" if flow=="sub" else "open_renew"
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(chat_id, "btn_agree"), callback_data=cb)],
                                 [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data=back_cb)]])

def pay_kb_sub(chat_id: int, pkg_name: str) -> InlineKeyboardMarkup:
    pay_url = PACKAGES[pkg_name]["payment_url"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_pay_now"), url=pay_url)],
        [InlineKeyboardButton(t(chat_id, "btn_paid"), callback_data=f"paid|{pkg_name}")],
        [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="subscribe")],
    ])

def pay_kb_renew(chat_id: int, code: str) -> InlineKeyboardMarkup:
    pkg_name = code_to_pkgname(code) or ""
    pay_url = PACKAGES[pkg_name]["payment_url"] if pkg_name else ""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_pay_now"), url=pay_url)],
        [InlineKeyboardButton(t(chat_id, "btn_paid"), callback_data=f"renew_paid|{code}")],
        [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="open_renew")],
    ])

def phone_request_kb(chat_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(t(chat_id, "btn_share_phone"), request_contact=True)]],
                               resize_keyboard=True, one_time_keyboard=True,
                               input_field_placeholder="Tap to share, or type your number…")

def renew_trial_packages_kb(prefix: str) -> InlineKeyboardMarkup:
    code_to_label = [("kids","👶 Kids / أطفال"),("casual","🙂 Casual / كاجوال"),
                     ("executive","🧑‍💼 Executive / تنفيذي"),("premium","⭐ Premium / بريميوم")]
    return InlineKeyboardMarkup([[InlineKeyboardButton(lbl, callback_data=f"{prefix}|{code}")]
                                 for code, lbl in code_to_label] + [
                                 [InlineKeyboardButton(I18N["btn_back"]["ar"] + " / " + I18N["btn_back"]["en"], callback_data="back_home")]])

# ------------------------- HELPERS -------------------------
async def safe_edit_or_send(query, context, chat_id: int, text: str, kb, html: bool=False, no_preview: bool=False) -> None:
    try:
        await query.edit_message_text(text, reply_markup=kb if isinstance(kb, InlineKeyboardMarkup) else None,
                                      parse_mode="HTML" if html else None,
                                      disable_web_page_preview=no_preview)
        if isinstance(kb, ReplyKeyboardMarkup):
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb,
                                           parse_mode="HTML" if html else None, disable_web_page_preview=no_preview)
    except Exception as e:
        logging.warning("edit_message_text failed (%s); sending new.", e)
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb,
                                           parse_mode="HTML" if html else None, disable_web_page_preview=no_preview)
        except Exception as e2:
            logging.error("send_message failed: %s", e2)

def pkg_details_for_lang(pkg_name: str, lang: str) -> str:
    pkg = PACKAGES.get(pkg_name)
    if not pkg: return ""
    return pkg["details_ar"] if lang == "ar" else pkg["details_en"]

def _is_admin(user_id: int) -> bool:
    try:
        return ADMIN_CHAT_ID is not None and int(ADMIN_CHAT_ID) == int(user_id)
    except Exception:
        return False

def _fmt_offer(o: dict, lang: str) -> str:
    title = o["title_ar"] if lang == "ar" else o["title_en"]
    s_uae = _parse_iso(o["start_at"]).astimezone(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    e_uae = _parse_iso(o["end_at"]).astimezone(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    return f"• {title}\n  🕒 {s_uae} → {e_uae} (UAE)\n  🔗 {o.get('cta_url','')}"

# ------------------------- HANDLERS -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(t(chat_id, "pick_lang"), reply_markup=lang_kb())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

# Admin commands
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Admin only.")
        return
    mode = "webhook" if WEBHOOK_URL else "polling"
    now_utc = _utcnow().strftime("%Y-%m-%d %H:%M:%S")
    now_uae = _utcnow().astimezone(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    await update.message.reply_text(f"✅ Status\nMode: {mode}\nUTC: {now_utc}\nUAE: {now_uae}")

async def debug_id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Your Telegram user id is: {update.effective_user.id}")

# ------------------------- TEXT / CONTACT / PHOTO -------------------------
async def any_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    st = get_state(chat_id)
    txt = (update.message.text or "").strip()

    # Subscribe — phone via typed text
    if st.get("awaiting_phone") and txt:
        if PHONE_RE.match(txt):
            phone = normalize_phone(txt)
            set_state(chat_id, phone=phone, awaiting_phone=False)
            save_customer(chat_id, update.effective_user, st.get("package"), phone)
            if ADMIN_CHAT_ID:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=(
                    f"📞 Phone captured\nUser: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})\n"
                    f"Name: {update.effective_user.full_name}\nPackage: {st.get('package')}\nPhone: {phone}"))
            await update.message.reply_text(t(chat_id, "phone_saved"), reply_markup=ReplyKeyboardRemove())
            await update.message.reply_text(t(chat_id, "thank_you"), reply_markup=main_menu_kb(chat_id))
            return
        else:
            await update.message.reply_text(t(chat_id, "phone_invalid"), reply_markup=phone_request_kb(chat_id))
            return

    # RENEW — after paid: ask username, then phone
    if context.user_data.get("renew_stage") == "await_username_after_paid":
        context.user_data["renew_username"] = txt
        context.user_data["renew_stage"] = "await_phone"
        contact_btn = KeyboardButton("📞 مشاركة الهاتف / Share Phone", request_contact=True)
        await update.message.reply_text("شارك رقم هاتفك للتأكيد / Share your phone for confirmation",
                                        reply_markup=ReplyKeyboardMarkup([[contact_btn]], resize_keyboard=True, one_time_keyboard=True))
        return

    # SUPPORT — flow: username -> details -> optional screenshot -> /done then ask phone
    if context.user_data.get("support_stage") == "await_details":
        context.user_data["support_details"] = txt
        context.user_data["support_stage"] = "await_optional_screenshot"
        await update.message.reply_text("أرسل لقطة شاشة (اختياري) أو أرسل /done للإرسال.\nSend a screenshot (optional) or send /done to submit.")
        return

    # No state → menu
    if "lang" not in st:
        await update.message.reply_text(t(chat_id, "pick_lang"), reply_markup=lang_kb())
    else:
        await update.message.reply_text(t(chat_id, "welcome"), reply_markup=main_menu_kb(chat_id))

async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    contact: Contact = update.message.contact
    phone = normalize_phone(contact.phone_number or "")

    # Subscribe phone via contact
    st = get_state(chat_id)
    if st.get("awaiting_phone"):
        set_state(chat_id, phone=phone, awaiting_phone=False)
        save_customer(chat_id, update.effective_user, st.get("package"), phone)
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=(
                f"📞 Phone captured via Contact\nUser: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})\n"
                f"Name: {update.effective_user.full_name}\nPackage: {st.get('package')}\nPhone: {phone}"))
        await update.message.reply_text(t(chat_id, "phone_saved"), reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text(t(chat_id, "thank_you"), reply_markup=main_menu_kb(chat_id))
        return

    # RENEW — after username
    if context.user_data.get("renew_stage") == "await_phone":
        renewal_id = save_jsonl(RENEWALS_FILE, {
            "tg_chat_id": chat_id, "tg_user_id": update.effective_user.id, "tg_username": update.effective_user.username,
            "package_code": context.user_data.get("renew_pkg_code"),
            "username_text": context.user_data.get("renew_username","-"),
            "phone_e164": phone, "created_at": datetime.now(DUBAI_TZ).isoformat(),
        })
        await update.message.reply_text("✅ تم تسجيل طلب التجديد — شكراً للدفع. سنتواصل معك قريبًا.\n\n✅ Renewal received — thanks for payment. We’ll contact you shortly.",
                                        reply_markup=ReplyKeyboardRemove())
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=(
                "🔁 NEW RENEWAL\n"
                f"Pkg: {context.user_data.get('renew_pkg_code')}\n"
                f"User: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})\n"
                f"Username: {context.user_data.get('renew_username','-')}\n"
                f"Phone: {phone}\nRenewal ID: {renewal_id}"
            ))
        for k in ("renew_stage","renew_pkg_code","renew_username"):
            context.user_data.pop(k, None)
        await update.message.reply_text(t(chat_id, "welcome"), reply_markup=main_menu_kb(chat_id))
        return

    # TRIAL — phone only (no username), with monthly limit
    if context.user_data.get("trial_stage") == "await_phone":
        ph = phone_hash(phone)
        ym = datetime.now(DUBAI_TZ).strftime("%Y-%m")
        for row in iter_jsonl(TRIALS_FILE):
            if row.get("phone_hash") == ph and row.get("year_month") == ym:
                await update.message.reply_text("عذرًا، استخدمت التجربة المجانية هذا الشهر. جرّب الشهر القادم.\nSorry, you already used this month’s free trial.",
                                                reply_markup=ReplyKeyboardRemove())
                context.user_data.pop("trial_stage", None)
                context.user_data.pop("trial_pkg_code", None)
                return
        code = context.user_data.get("trial_pkg_code")
        hours = TRIAL_HOURS.get(code, 24)
        expires_at = datetime.now(DUBAI_TZ) + timedelta(hours=hours)
        trial_id = save_jsonl(TRIALS_FILE, {
            "tg_chat_id": chat_id, "tg_user_id": update.effective_user.id, "tg_username": update.effective_user.username,
            "package_code": code, "phone_e164": phone, "phone_hash": ph,
            "expires_at": expires_at.isoformat(), "requested_at": datetime.now(DUBAI_TZ).isoformat(),
            "year_month": ym, "status": "pending",
        })
        await update.message.reply_text("✅ تم تسجيل طلب التجربة — سيتم إرسال بيانات الدخول قريبًا.\n\n✅ Trial request received — credentials will be sent shortly.",
                                        reply_markup=ReplyKeyboardRemove())
        if ADMIN_CHAT_ID:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Send Trial", callback_data=f"trial_send|{trial_id}"),
                 InlineKeyboardButton("✖️ Reject", callback_data=f"trial_reject|{trial_id}")]
            ])
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=(
                "🎁 NEW TRIAL REQUEST\n"
                f"User: @{update.effective_user.username or 'N/A'} (chat {chat_id})\n"
                f"Pkg: {code}  |  Phone: {phone}\n"
                f"Expires (if activated now): {expires_at:%Y-%m-%d %H:%M} Asia/Dubai"
            ), reply_markup=kb)
        context.user_data.pop("trial_stage", None)
        context.user_data.pop("trial_pkg_code", None)
        await update.message.reply_text(t(chat_id, "welcome"), reply_markup=main_menu_kb(chat_id))
        return

    # SUPPORT — collect phone after /done
    if context.user_data.get("support_stage") == "await_phone":
        context.user_data["support_phone_e164"] = phone
        await update.message.reply_text("✅ تم استلام رقمك. سنعاود الاتصال بك قريبًا.\n✅ Phone received. We’ll contact you shortly.",
                                        reply_markup=ReplyKeyboardRemove())
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=(
                "🛟 SUPPORT PHONE\n"
                f"User: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})\n"
                f"Phone: {phone}"
            ))
        # clear support state (keep ticket in file already created at /done)
        for k in list(context.user_data.keys()):
            if k.startswith("support_"):
                context.user_data.pop(k, None)
        await update.message.reply_text(t(chat_id, "welcome"), reply_markup=main_menu_kb(chat_id))

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("support_stage") == "await_optional_screenshot":
        phs = update.message.photo
        if phs:
            context.user_data["support_photo_file_id"] = phs[-1].file_id
            await update.message.reply_text("✅ Screenshot attached. Send /done to submit.")

# ------------------------- COMMANDS -------------------------
async def support_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Create support ticket and then ask for phone
    if context.user_data.get("support_issue_code") is None:
        return
    ticket_id = save_jsonl(SUPPORT_FILE, {
        "tg_chat_id": update.effective_chat.id,
        "tg_user_id": update.effective_user.id,
        "tg_username": update.effective_user.username,
        "issue_code": context.user_data.get("support_issue_code"),
        "username_text": context.user_data.get("support_username", "-"),
        "details": context.user_data.get("support_details", "-"),
        "photo_file_id": context.user_data.get("support_photo_file_id"),
        "created_at": datetime.now(DUBAI_TZ).isoformat(),
    })
    # Thank-you then ask for phone
    await update.message.reply_text(f"✅ تم إنشاء تذكرة الدعم #{ticket_id} — سنعاود الاتصال بك قريبًا.\n✅ Support ticket #{ticket_id} created — we’ll follow up shortly.")
    contact_btn = KeyboardButton("📞 مشاركة الهاتف / Share Phone", request_contact=True)
    context.user_data["support_stage"] = "await_phone"
    await update.message.reply_text("فضلاً شارك رقم هاتفك\nPlease share your phone number",
                                    reply_markup=ReplyKeyboardMarkup([[contact_btn]], resize_keyboard=True, one_time_keyboard=True))
    if ADMIN_CHAT_ID:
        text = (
            "🛟 NEW SUPPORT TICKET\n"
            f"Ticket #{ticket_id}\n"
            f"Issue: {context.user_data.get('support_issue_code')}\n"
            f"User: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})\n"
            f"Username: {context.user_data.get('support_username','-')}\n"
            f"Details: {context.user_data.get('support_details','-')}"
        )
        if context.user_data.get("support_photo_file_id"):
            await update.message.bot.send_photo(chat_id=int(ADMIN_CHAT_ID), photo=context.user_data["support_photo_file_id"], caption=text)
        else:
            await update.message.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=text)
    # clear non-phone support keys
    for k in ("support_issue_code","support_username","support_details","support_photo_file_id"):
        context.user_data.pop(k, None)

# ------------------------- BUTTON ROUTER -------------------------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat.id
    user = q.from_user
    data = (q.data or "").strip()

    if data.startswith("lang|"):
        _, lang = data.split("|", 1)
        if lang not in ("ar","en"): lang = "ar"
        set_state(chat_id, lang=lang)
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "welcome"), main_menu_kb(chat_id))
        return

    if "lang" not in get_state(chat_id):
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "pick_lang"), lang_kb())
        return

    if data == "more_info":
        text = I18N["more_info_title"][get_lang(chat_id)] + "\n\n" + I18N["more_info_body"][get_lang(chat_id)]
        await safe_edit_or_send(q, context, chat_id, text, main_menu_kb(chat_id), no_preview=True)
        return

    # Subscribe
    if data == "subscribe":
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "subscribe_pick"), packages_kb()); return
    if data.startswith("pkg|"):
        _, pkg_name = data.split("|", 1)
        if pkg_name not in PACKAGES:
            await safe_edit_or_send(q, context, chat_id, "Package not found.", packages_kb()); return
        set_state(chat_id, package=pkg_name)
        price = PACKAGES[pkg_name]["price_aed"]
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "breadcrumb_sel").format(pkg=pkg_name, price=price))
        lang = get_lang(chat_id); details = pkg_details_for_lang(pkg_name, lang)
        text = f"🛍️ <b>{pkg_name}</b>\n💰 <b>{price} AED</b>\n{details}\n{t(chat_id, 'terms')}"
        await safe_edit_or_send(q, context, chat_id, text, agree_kb(chat_id, pkg_name, "sub"), html=True); return
    if data.startswith("agree|"):
        _, pkg_name = data.split("|", 1)
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "breadcrumb_agree").format(pkg=pkg_name))
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "payment_instructions"), pay_kb_sub(chat_id, pkg_name), no_preview=True); return
    if data.startswith("paid|"):
        _, pkg_name = data.split("|", 1)
        sel = get_state(chat_id).get("package", pkg_name)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "breadcrumb_paid").format(pkg=sel, ts=ts))
        set_state(chat_id, awaiting_phone=True)
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "phone_request"), reply_markup=phone_request_kb(chat_id))
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=(f"🆕 I Paid clicked (phone pending)\nUser: @{user.username or 'N/A'} ({user.id})\nPackage: {sel}\nPhone: pending"))
        return

    # Offers (unchanged core)
    if data == "offers":
        acts = active_offers()
        if not acts:
            await safe_edit_or_send(q, context, chat_id, "No offers right now. Check back soon 🌟",
                                    InlineKeyboardMarkup([[InlineKeyboardButton(t(chat_id,"btn_back"), callback_data="back_home")]])); return
        rows = []
        for idx, o in enumerate(acts):
            title = o["title_ar"] if get_lang(chat_id) == "ar" else o["title_en"]
            rows.append([InlineKeyboardButton(title, callback_data=f"offer_act|{idx}")])
        rows.append([InlineKeyboardButton(t(chat_id,"btn_back"), callback_data="back_home")])
        await safe_edit_or_send(q, context, chat_id, I18N["btn_offers"][get_lang(chat_id)] + " — Active", InlineKeyboardMarkup(rows)); return
    if data.startswith("offer_act|"):
        _, sidx = data.split("|", 1)
        try: idx = int(sidx)
        except: await safe_edit_or_send(q, context, chat_id, "No offers.", main_menu_kb(chat_id)); return
        acts = active_offers()
        if not (0 <= idx < len(acts)): await safe_edit_or_send(q, context, chat_id, "No offers.", main_menu_kb(chat_id)); return
        off = acts[idx]; now = _utcnow()
        if not (_parse_iso(off["start_at"]) <= now <= _parse_iso(off["end_at"])):
            await safe_edit_or_send(q, context, chat_id, "No offers.", main_menu_kb(chat_id)); return
        lang = get_lang(chat_id)
        title = off["title_ar"] if lang=="ar" else off["title_en"]
        body  = off["body_ar"]  if lang=="ar" else off["body_en"]
        txt = f"🛍️ <b>{title}</b>\n\n{body}\n\n{t(chat_id,'terms')}"
        await safe_edit_or_send(q, context, chat_id, txt,
                                InlineKeyboardMarkup([[InlineKeyboardButton(t(chat_id,"btn_agree"), callback_data=f"offer_agree|{idx}")],
                                                      [InlineKeyboardButton(t(chat_id,"btn_back"), callback_data="offers")]]),
                                html=True); return
    if data.startswith("offer_agree|"):
        _, sidx = data.split("|", 1)
        try: idx = int(sidx)
        except: await safe_edit_or_send(q, context, chat_id, "No offers.", main_menu_kb(chat_id)); return
        acts = active_offers()
        url = (acts[idx].get("cta_url") or "").strip() if 0 <= idx < len(acts) else ""
        await safe_edit_or_send(q, context, chat_id, t(chat_id,"payment_instructions"),
                                InlineKeyboardMarkup([[InlineKeyboardButton(t(chat_id,"btn_pay_now"), url=url)],
                                                      [InlineKeyboardButton(t(chat_id,"btn_paid"), callback_data=f"offer_paid|{idx}")],
                                                      [InlineKeyboardButton(t(chat_id,"btn_back"), callback_data="offers")]]),
                                no_preview=True); return
    if data.startswith("offer_paid|"):
        _, sidx = data.split("|", 1)
        try: idx = int(sidx)
        except: await safe_edit_or_send(q, context, chat_id, "No offers.", main_menu_kb(chat_id)); return
        acts = active_offers()
        if not (0 <= idx < len(acts)): await safe_edit_or_send(q, context, chat_id, "No offers.", main_menu_kb(chat_id)); return
        off = acts[idx]
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id,"breadcrumb_paid").format(pkg=(off.get('title_en') or 'Offer'), ts=ts))
        set_state(chat_id, awaiting_phone=True)
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id,"phone_request"), reply_markup=phone_request_kb(chat_id))
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=(f"🆕 Offer I Paid (phone pending)\nUser: @{user.username or 'N/A'} ({user.id})\nOffer: {off.get('title_en')}\nPhone: pending"))
        return

    # Renew (now like Subscribe)
    if data == "open_renew":
        await safe_edit_or_send(q, context, chat_id, "🔁 **Renew**\nاختر الباقة للتجديد / Choose a package to renew",
                                renew_trial_packages_kb("renew_pkg")); return

    if data.startswith("renew_pkg|"):
        _, code = data.split("|", 1)
        pkg_name = code_to_pkgname(code)
        if not pkg_name:
            await safe_edit_or_send(q, context, chat_id, "Package not found.", renew_trial_packages_kb("renew_pkg")); return
        context.user_data["renew_pkg_code"] = code
        price = PACKAGES[pkg_name]["price_aed"]
        lang = get_lang(chat_id); details = pkg_details_for_lang(pkg_name, lang)
        text = f"🔁 <b>{pkg_name} — Renew</b>\n💰 <b>{price} AED</b>\n{details}\n{t(chat_id,'terms')}"
        await safe_edit_or_send(q, context, chat_id, text, agree_kb(chat_id, code, "renew"), html=True); return

    if data.startswith("renew_agree|"):
        _, code = data.split("|", 1)
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "breadcrumb_agree").format(pkg=code))
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "payment_instructions"), pay_kb_renew(chat_id, code), no_preview=True); return

    if data.startswith("renew_paid|"):
        _, code = data.split("|", 1)
        pkg_name = code_to_pkgname(code) or code
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id,"breadcrumb_paid").format(pkg=pkg_name, ts=ts))
        context.user_data["renew_stage"] = "await_username_after_paid"
        await context.bot.send_message(chat_id=chat_id, text="أدخل اسم المستخدم (للتطبيق)\nEnter your username (for the player)")
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=(f"🔁 Renew I Paid (username + phone pending)\nUser: @{user.username or 'N/A'} ({user.id})\nPackage: {pkg_name}"))
        return

    # Trial (no username)
    if data == "open_trial":
        await safe_edit_or_send(q, context, chat_id, "🎁 **Free Trial**\nاختر باقتك للتجربة / Choose your trial package",
                                renew_trial_packages_kb("trial_pkg")); return
    if data.startswith("trial_pkg|"):
        _, code = data.split("|", 1)
        context.user_data["trial_stage"] = "await_phone"
        context.user_data["trial_pkg_code"] = code
        hours = TRIAL_HOURS.get(code, 24)
        contact_btn = KeyboardButton("📞 مشاركة الهاتف / Share Phone", request_contact=True)
        await safe_edit_or_send(q, context, chat_id,
                                f"⏱️ Trial duration: {hours} hours\n\n"
                                "فضلاً شارك رقم هاتفك للتحقق (مرّة واحدة كل شهر)\n"
                                "Please share your phone number to verify (once per month)",
                                ReplyKeyboardMarkup([[contact_btn]], resize_keyboard=True, one_time_keyboard=True))
        return

    # Support
    if data == "open_support":
        issues = [("LOGIN","لا أستطيع تسجيل الدخول / Can’t log in"),("FREEZE","تقطيع/تجميد / Freezing/Buffering"),
                  ("PAY","مشكلة الدفع / Payment issue"),("EXPIRE","انتهى الاشتراك / Subscription expired"),
                  ("SETUP","إعداد التطبيق (M3U/IBO) / Player setup"),("OTHER","أخرى / Other")]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(lbl, callback_data=f"support_issue|{code}") ] for code,lbl in issues] +
                                  [[InlineKeyboardButton(t(chat_id,"btn_back"), callback_data="back_home")]])
        await safe_edit_or_send(q, context, chat_id, "🛟 اختر المشكلة / Choose an issue", kb); return
    if data.startswith("support_issue|"):
        _, code = data.split("|", 1)
        context.user_data["support_issue_code"] = code
        context.user_data["support_stage"] = "await_username"
        await safe_edit_or_send(q, context, chat_id, "أدخل اسم المستخدم\nEnter your username",
                                InlineKeyboardMarkup([[InlineKeyboardButton(t(chat_id,"btn_back"), callback_data="back_home")]])); return

    if data == "back_home":
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "welcome"), main_menu_kb(chat_id)); return

# ------------------------- ADMIN FORCE REPLY (TRIAL CREDS) -------------------------
async def admin_force_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    tid = context.user_data.pop("awaiting_trial_creds_for", None)
    if not tid:
        return
    creds = (update.message.text or "").strip()
    user_chat_id = None
    pkg = "casual"
    exp_dt = datetime.now(DUBAI_TZ) + timedelta(hours=24)
    rows = iter_jsonl(TRIALS_FILE)
    for r in rows:
        if int(r.get("id", 0)) == int(tid):
            user_chat_id = int(r["tg_chat_id"])
            pkg = r["package_code"]
            exp_dt = datetime.fromisoformat(r["expires_at"]).astimezone(DUBAI_TZ)
            r["status"] = "granted"
            r["granted_at"] = datetime.now(DUBAI_TZ).isoformat()
    with TRIALS_FILE.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if user_chat_id:
        await context.bot.send_message(chat_id=user_chat_id,
            text=(f"✅ تم تفعيل تجربة {pkg}\nبيانات الدخول:\n{creds}\n\n"
                  f"⏳ الصلاحية حتى: {exp_dt:%Y-%m-%d %H:%M} بتوقيت الإمارات\nاستمتع بالمشاهدة 🎬"))
        await update.message.reply_text("✅ Trial credentials sent to user")

# ------------------------- ERROR & INIT -------------------------
async def handle_error(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Handler error: %s", context.error)

async def _post_init(application: Application):
    try:
        if WEBHOOK_URL:
            await application.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
        else:
            await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning("Webhook init/cleanup failed: %s", e)

# ------------------------- MAIN -------------------------
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    global OFFERS_ALL
    OFFERS_ALL = build_embedded_offers()

    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("done", support_done))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("debug_id", debug_id_cmd))

    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_photo))
    app.add_handler(MessageHandler(filters.REPLY & filters.ChatType.PRIVATE, admin_force_reply))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_text))

    app.add_error_handler(handle_error)

    if WEBHOOK_URL:
        port = int(os.getenv("PORT", "10000"))
        logging.info("Starting webhook on 0.0.0.0:%s", port)
        app.run_webhook(listen="0.0.0.0", port=port, url_path="", webhook_url=WEBHOOK_URL, drop_pending_updates=True)
    else:
        logging.info("Starting polling.")
        app.run_polling(allowed_updates=None, drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
