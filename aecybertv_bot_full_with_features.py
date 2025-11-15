# -*- coding: utf-8 -*-
"""
AECyberTV Telegram Sales Bot — Bilingual + Renew + Free Trial + Support + Offers
python-telegram-bot==21.4
"""

import os
import re
import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

from zoneinfo import ZoneInfo

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, Contact, InputMediaPhoto,
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat
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

BOT_TOKEN     = os.getenv("BOT_TOKEN")  # required
ADMIN_CHAT_ID = env_int("ADMIN_CHAT_ID")  # optional
WEBHOOK_URL   = os.getenv("WEBHOOK_URL")   # optional

if not BOT_TOKEN:
    logging.basicConfig(level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.error("BOT_TOKEN is required.")
    sys.exit(1)

DATA_DIR = Path(os.getenv("DATA_DIR", ".")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

CUSTOMERS_FILE = DATA_DIR / "customers.jsonl"
TRIALS_FILE    = DATA_DIR / "trials.jsonl"
SUPPORT_FILE   = DATA_DIR / "support.jsonl"
OFFERS_FILE    = DATA_DIR / "offers.json"
STATE_FILE     = DATA_DIR / "state.json"

TZ_UAE = ZoneInfo("Asia/Dubai")

# ------------------------- UTILITIES -------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _now_uae() -> datetime:
    return _utcnow().astimezone(TZ_UAE)

def save_jsonl(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def load_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out

def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

# ------------------------- STATE -------------------------
USER_STATE: Dict[int, Dict[str, Any]] = load_json(STATE_FILE, {})

def set_state(chat_id: int, **kv):
    st = USER_STATE.setdefault(chat_id, {})
    st.update(kv)

def get_state(chat_id: int) -> Dict[str, Any]:
    return USER_STATE.get(chat_id, {})

def save_customer(chat_id: int, user, package: Optional[str], phone: Optional[str], extra: Optional[dict]=None) -> None:
    rec = {
        "chat_id": chat_id,
        "user_id": user.id,
        "username": user.username,
        "name": user.full_name,
        "package": package,
        "phone": phone,
        "lang": get_state(chat_id).get("lang", "ar"),
        "ts_utc": _utcnow().isoformat(),
        "ts_uae": _now_uae().isoformat(),
    }
    if extra:
        rec.update(extra)
    save_jsonl(CUSTOMERS_FILE, rec)

def save_trial(chat_id: int, user, package: str, phone: str) -> None:
    rec = {
        "chat_id": chat_id,
        "user_id": user.id,
        "username": user.username,
        "name": user.full_name,
        "package": package,
        "phone": phone,
        "lang": get_state(chat_id).get("lang", "ar"),
        "ts_utc": _utcnow().isoformat(),
        "ts_uae": _now_uae().isoformat(),
    }
    save_jsonl(TRIALS_FILE, rec)

def save_support(rec: dict) -> None:
    save_jsonl(SUPPORT_FILE, rec)

def _persist_state() -> None:
    save_json(STATE_FILE, USER_STATE)

# ------------------------- I18N TEXTS -------------------------
I18N: Dict[str, Dict[str, Any]] = {
    "welcome": {
        "ar": "👋 أهلاً بك في AECyberTV!\nاختر ما تريد من القائمة:",
        "en": "👋 Welcome to AECyberTV!\nPlease choose from the menu:",
    },
    "pick_lang": {
        "ar": "🌐 اختر اللغة:",
        "en": "🌐 Please choose your language:",
    },

    # Main menu buttons
    "btn_more_info": {"ar": "📋 معلومات", "en": "📋 More Info"},
    "btn_subscribe": {"ar": "💳 اشتراك", "en": "💳 Subscribe"},
    "btn_renew": {"ar": "♻️ تجديد", "en": "♻️ Renew"},
    "btn_trial": {"ar": "🧪 تجربة مجانية", "en": "🧪 Free Trial"},
    "btn_support": {"ar": "🛟 دعم", "en": "🛟 Support"},
    "btn_offers": {"ar": "🎁 عروض", "en": "🎁 Offers"},
    "btn_back": {"ar": "⬅️ رجوع", "en": "⬅️ Back"},

    # More info
    "more_info_title": {
        "ar": "📋 نبذة عن AECyberTV",
        "en": "📋 About AECyberTV",
    },
    "more_info_body_compact": {
        "ar": (
            "🌐 AECyberTV — خدمة ترفيه متكاملة:\n"
            "• قنوات مباشرة (رياضة، أفلام، مسلسلات، أطفال وأكثر)\n"
            "• مكتبة ضخمة من الأفلام والمسلسلات (VOD)\n"
            "• جودة بث: SD / HD / FHD / 4K حسب الباقة والجهاز\n"
            "• يعمل على أجهزة التلفزيون الذكية، أندرويد، آيفون، الكمبيوتر وغيرها.\n\n"
            "لمعرفة روابط التطبيقات وطريقة التفعيل اضغط 👇"
        ),
        "en": (
            "🌐 AECyberTV — All-in-one entertainment:\n"
            "• Live channels (sports, movies, series, kids & more)\n"
            "• Huge VOD library of movies and series\n"
            "• Streaming quality: SD / HD / FHD / 4K depending on package/device\n"
            "• Works on Smart TVs, Android, iPhone/iPad, and PC.\n\n"
            "Tap below for apps & activation steps 👇"
        ),
    },

    "players_links_title": {
        "ar": "📺 تطبيقات التشغيل والروابط الرسمية",
        "en": "📺 Players & official links",
    },
    "players_links_body": {
        "ar": "اختر نوع جهازك للحصول على روابط التطبيقات:",
        "en": "Choose your device type to get the player links:",
    },

    # Player bodies
    "player_iplay_body": {
        "ar": (
            "🍏 iPlay (iPhone / iPad / Mac):\n"
            "• iPlay – لأجهزة iPhone / iPad / Mac\n\n"
            "🌐 الموقع الرسمي:\n"
            "• aecybertv.xyz\n\n"
            "🔢 رقم الخادم (Host/DNS): 7765"
        ),
        "en": (
            "🍏 iPlay (iPhone / iPad / Mac):\n"
            "• iPlay for iPhone / iPad / Mac\n\n"
            "🌐 Official website:\n"
            "• aecybertv.xyz\n\n"
            "🔢 Server (Host/DNS): 7765"
        ),
    },
    "player_splayer_body": {
        "ar": (
            "📺 SPlayer (Android TV / Fire Stick):\n"
            "• Android / Smart TV: play.google.com/store/apps/details?id=com.player.iptv\n"
            "• Firestick / Android TV (Downloader): aftv.news/6913771\n\n"
            "🌐 الموقع الرسمي: aecybertv.xyz\n🔢 رقم الخادم (Host/DNS): 7765"
        ),
        "en": (
            "📺 SPlayer (Android TV / Fire Stick):\n"
            "• Android / Smart TV: play.google.com/store/apps/details?id=com.player.iptv\n"
            "• Firestick / Android TV (Downloader): aftv.news/6913771\n\n"
            "🌐 Official website: aecybertv.xyz\n🔢 Server (Host/DNS): 7765"
        ),
    },
    "player_000_body": {
        "ar": (
            "📺 000 Player (Android / Smart TV):\n"
            "• Google Play: https://play.google.com/store/apps/details?id=com.player.iptv\n"
            "• Web Player: https://my.splayer.in\n\n"
            "🌐 الموقع الرسمي: aecybertv.xyz\n🔢 رقم الخادم (Host/DNS): 7765"
        ),
        "en": (
            "📺 000 Player (Android / Smart TV):\n"
            "• Google Play: https://play.google.com/store/apps/details?id=com.player.iptv\n"
            "• Web Player: https://my.splayer.in\n\n"
            "🌐 Official website: aecybertv.xyz\n🔢 Server (Host/DNS): 7765"
        ),
    },

    # Subscribe / Renew
    "subscribe_pick": {
        "ar": "💳 اختر الباقة التي تريد الاشتراك أو التجديد لها:",
        "en": "💳 Choose the package you want to subscribe/renew:",
    },
    "ask_phone": {
        "ar": "📱 أرسل رقم هاتفك (أو شارك جهة الاتصال) للتواصل حول التفعيل:",
        "en": "📱 Please send your phone number (or share your contact) so we can help with activation:",
    },
    "phone_saved": {
        "ar": "✅ تم حفظ رقم الهاتف.",
        "en": "✅ Phone number saved.",
    },

    # Offers UI texts
    "offers_title": {"ar": "🎁 العروض المتاحة الآن", "en": "🎁 Available offers now"},
    "offers_none": {"ar": "لا توجد عروض متاحة الآن", "en": "no offer"},

    # Renew / Username
    "ask_username": {
        "ar": "👤 اكتب اسم المستخدم (username) المستخدم في التطبيق للتجديد.",
        "en": "👤 Please type the account username you use in the player for renewal.",
    },
    "username_saved": {"ar": "✅ تم حفظ اسم المستخدم.", "en": "✅ Username saved."},

    # Trial
    "trial_pick": {
        "ar": "🧪 اختر باقة للتجربة المجانية (مرة كل 30 يومًا لكل رقم ولكل باقة):",
        "en": "🧪 Choose a package for the free trial (once every 30 days per phone per package):",
    },
    "trial_recorded": {
        "ar": "✅ تم تسجيل طلب التجربة. سيتم التواصل معك لإرسال بيانات الدخول.",
        "en": "✅ Trial request recorded. We’ll contact you to send credentials.",
    },
    "trial_cooldown": {
        "ar": "❗️ تم استخدام تجربة باقة «{pkg}» مؤخرًا لهذا الرقم. اطلب تجربة جديدة بعد ~{days} يومًا.",
        "en": "❗️ A trial for “{pkg}” was used recently for this number. Please try again in ~{days} days.",
    },

    # Support (Arabic & English labels)
    "support_pick": {"ar": "🛟 اختر نوع المشكلة:", "en": "🛟 Choose an issue:"},
    "support_login": {"ar": "🚪 تسجيل الدخول/التفعيل", "en": "🚪 Login/Activation"},
    "support_channels": {"ar": "📺 مشكلة بالقنوات", "en": "📺 Channels issue"},
    "support_payment": {"ar": "💳 مشكلة بالدفع/الاشتراك", "en": "💳 Payment/Subscription"},
    "support_other": {"ar": "❓ أخرى", "en": "❓ Other"},

    "support_ask_details": {
        "ar": "✏️ اكتب تفاصيل المشكلة (بإمكانك إضافة صور بعد ذلك):",
        "en": "✏️ Please describe the issue (you can add screenshots afterwards):",
    },
    "support_ask_screenshot": {
        "ar": "📷 أرسل لقطة شاشة (اختياري)، أو اكتب /done لإنهاء الطلب.",
        "en": "📷 Send a screenshot (optional), or type /done to submit the ticket.",
    },
    "support_saved": {
        "ar": "✅ تم تسجيل بلاغ الدعم. سيتم التواصل معك قريبًا.",
        "en": "✅ Your support request has been recorded. We’ll contact you soon.",
    },
}

def t(chat_id: int, key: str) -> str:
    st = get_state(chat_id)
    lang = st.get("lang", "ar")
    val = I18N.get(key)
    if val is None:
        return key
    if isinstance(val, dict):
        return val.get(lang, val.get("en", key))
    return str(val)

# ------------------------- KEYBOARDS -------------------------
def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(I18N["lang_ar"]["ar"], callback_data="lang|ar"),
         InlineKeyboardButton(I18N["lang_en"]["en"], callback_data="lang|en")]
    ])

def main_menu_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_more_info"), callback_data="more_info"),
         InlineKeyboardButton(t(chat_id, "btn_subscribe"), callback_data="subscribe")],
        [InlineKeyboardButton(t(chat_id, "btn_renew"), callback_data="renew"),
         InlineKeyboardButton(t(chat_id, "btn_trial"), callback_data="trial")],
        [InlineKeyboardButton(t(chat_id, "btn_support"), callback_data="support"),
         InlineKeyboardButton(t(chat_id, "btn_offers"), callback_data="offers")]
    ])

def more_info_summary_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_players_links"), callback_data="players_links")],
        [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="back_home")]
    ])

def players_links_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍏 iPlay (iPhone / iPad / Mac)", callback_data="player_links|iplay")],
        [InlineKeyboardButton("📺 SPlayer (Android TV / Fire Stick)", callback_data="player_links|splayer")],
        [InlineKeyboardButton("📺 000 Player (Android / Smart TV)", callback_data="player_links|000")],
        [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="back_more_info")]
    ])

def packages_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(pkg, callback_data=f"pkg|{pkg}")] for pkg in PACKAGES.keys()]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back_home")])
    return InlineKeyboardMarkup(rows)

def agree_kb(chat_id: int, pkg_name: str, reason: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ OK", callback_data=f"agree|{reason}|{pkg_name}"),
         InlineKeyboardButton("⬅️ Back", callback_data="back_home")]
    ])

def trial_packages_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(pkg, callback_data=f"trial_pkg|{pkg}")]
        for pkg in PACKAGES.keys()
    ]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back_home")])
    return InlineKeyboardMarkup(rows)

def support_issues_kb(chat_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(t(chat_id, "support_login"), callback_data="support_issue|login")],
            [InlineKeyboardButton(t(chat_id, "support_channels"), callback_data="support_issue|channels")],
            [InlineKeyboardButton(t(chat_id, "support_payment"), callback_data="support_issue|payment")],
            [InlineKeyboardButton(t(chat_id, "support_other"), callback_data="support_issue|other")],
            [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="back_home")]]
    return InlineKeyboardMarkup(rows)

# ------------------------- PACKAGES -------------------------
PACKAGES: Dict[str, Dict[str, Any]] = {
    "AECyberTV Kids": {
        "code": "kids",
        "price_aed": 70,
        "trial_hours": 8,
        "details_en": "\n• Kids-safe channels\n• Cartoons & Educational shows\n• Works on 1 device\n",
        "details_ar": "\n• قنوات للأطفال\n• كرتون وبرامج تعليمية\n• يعمل على جهاز واحد\n",
        "payment_url": "https://buy.stripe.com/3cIbJ29I94yA92g2AV5kk04",
    },
    "AECyberTV Casual": {
        "code": "casual",
        "price_aed": 75,
        "trial_hours": 24,
        "details_en": "\n• 10,000+ Live Channels\n• 70,000+ Movies (VOD)\n• 12,000+ Series\n• Works on 1 device\n",
        "details_ar": "\n• أكثر من 10,000 قناة مباشرة\n• أكثر من 70,000 فيلم (VOD)\n• أكثر من 12,000 مسلسل\n• يعمل على جهاز واحد\n",
        "payment_url": "https://buy.stripe.com/your_casual_link",
    },
    "AECyberTV Executive": {
        "code": "executive",
        "price_aed": 200,
        "trial_hours": 24,
        "details_en": "\n• 16,000+ Live Channels\n• 24,000+ Movies (VOD)\n• 14,000+ Series\n• Works on 2 devices\n",
        "details_ar": "\n• أكثر من 16,000 قناة مباشرة\n• أكثر من 24,000 فيلم (VOD)\n• أكثر من 14,000 مسلسل\n• يعمل على جهازين\n",
        "payment_url": "https://buy.stripe.com/your_executive_link",
    },
    "AECyberTV Premium": {
        "code": "premium",
        "price_aed": 250,
        "trial_hours": 24,
        "details_en": "\n• All Executive content\n• Extra sports & premium channels\n• Works on 3 devices\n",
        "details_ar": "\n• كل محتوى الباقة التنفيذية\n• قنوات رياضية ومميزة إضافية\n• يعمل على 3 أجهزة\n",
        "payment_url": "https://buy.stripe.com/your_premium_link",
    },
}

# ------------------------- OFFERS -------------------------
OFFERS_ALL: List[Dict[str, Any]] = []

def build_embedded_offers() -> List[Dict[str, Any]]:
    if OFFERS_FILE.exists():
        try:
            return json.loads(OFFERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def active_offers(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    if now is None:
        now = _utcnow()  # UTC
    acts: List[Dict[str, Any]] = []
    for o in OFFERS_ALL:
        try:
            if _parse_iso(o["start_at"]) <= now <= _parse_iso(o["end_at"]):
                acts.append(o)
        except Exception:
            continue
    acts.sort(key=lambda x: (-(int(x.get("priority", 0))), x.get("start_at", "")))
    return acts

def upcoming_offers(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    if now is None:
        now = _utcnow()  # UTC
    ups: List[Dict[str, Any]] = []
    for o in OFFERS_ALL:
        try:
            if _parse_iso(o["start_at"]) > now:
                ups.append(o)
        except Exception:
            continue
    ups.sort(key=lambda x: _parse_iso(x["start_at"]))
    return ups

def _fmt_offer(o: Dict[str, Any], lang: str) -> str:
    title = o["title_ar"] if lang == "ar" else o["title_en"]
    desc = o["desc_ar"] if lang == "ar" else o["desc_en"]
    return f"{title}\n{desc}\nFrom: {o['start_at']} To: {o['end_at']}"

# ------------------------- HELPERS -------------------------
def _is_admin(user_id: int) -> bool:
    return ADMIN_CHAT_ID is not None and user_id == ADMIN_CHAT_ID

async def safe_edit_or_send(q, context: ContextTypes.DEFAULT_TYPE, chat_id: int,
                            text: str, kb: Optional[InlineKeyboardMarkup] = None,
                            no_preview: bool = False):
    try:
        if q and q.message:
            await q.message.edit_text(text, reply_markup=kb, disable_web_page_preview=no_preview)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, disable_web_page_preview=no_preview)
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, disable_web_page_preview=no_preview)

async def _send_phone_prompt(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    btn = KeyboardButton(text=t(chat_id, "ask_phone"), request_contact=True)
    kb = ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)
    await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "ask_phone"), reply_markup=kb)

# ------------------------- HANDLERS -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(t(chat_id, "pick_lang"), reply_markup=lang_kb())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

async def packages_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show subscription packages and start subscribe flow (same as Subscribe button)."""
    chat_id = update.effective_chat.id
    # Reset flow and show packages
    set_state(chat_id, flow="subscribe", awaiting_phone=False, awaiting_phone_reason=None)
    await update.message.reply_text(t(chat_id, "subscribe_pick"), reply_markup=packages_kb())

async def renew_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start renewal flow (same as Renew button)."""
    chat_id = update.effective_chat.id
    set_state(chat_id, flow="renew", awaiting_phone=False, awaiting_phone_reason=None)
    await update.message.reply_text(t(chat_id, "subscribe_pick"), reply_markup=packages_kb())

async def trial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start free trial flow (same as Trial button)."""
    chat_id = update.effective_chat.id
    set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)
    await update.message.reply_text(t(chat_id, "trial_pick"), reply_markup=trial_packages_kb())

async def support_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open support ticket flow (same as Support button)."""
    chat_id = update.effective_chat.id
    set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)
    await update.message.reply_text(t(chat_id, "support_pick"), reply_markup=support_issues_kb(chat_id))

async def offers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show active offers (same as Offers button)."""
    chat_id = update.effective_chat.id
    acts = active_offers()
    if not acts:
        await update.message.reply_text(t(chat_id, "offers_none"))
        return
    rows = []
    lang = get_state(chat_id).get("lang", "ar")
    for idx, o in enumerate(acts):
        title = o["title_ar"] if lang == "ar" else o["title_en"]
        rows.append([InlineKeyboardButton(title, callback_data=f"offer_act|{idx}")])
    rows.append([InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="back_home")])
    await update.message.reply_text(t(chat_id, "offers_title"), reply_markup=InlineKeyboardMarkup(rows))

# Admin/utility commands
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Admin only.")
        return
    mode = "webhook" if WEBHOOK_URL else "polling"
    await update.message.reply_text(
        f"✅ Status\nMode: {mode}\nUTC: {_utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"UAE: {_now_uae().strftime('%Y-%m-%d %H:%M:%S')}\nActive offers: {len(active_offers())}"
    )

async def offers_now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Admin only.")
        return
    acts = active_offers()
    if not acts:
        await update.message.reply_text("no offer")
        return
    lines = ["Available offers now:"]
    for o in acts:
        lines.append(_fmt_offer(o, get_state(update.effective_chat.id).get("lang","ar")))
    await update.message.reply_text("\n".join(lines))

async def upcoming_offers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Admin only.")
        return
    ups = upcoming_offers()
    if not ups:
        await update.message.reply_text("no offer")
        return
    lines = ["Upcoming offers:"]
    for o in ups:
        lines.append(_fmt_offer(o, get_state(update.effective_chat.id).get("lang","ar")))
    await update.message.reply_text("\n".join(lines))

async def offer_reload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Admin only.")
        return
    global OFFERS_ALL
    OFFERS_ALL = build_embedded_offers()
    await update.message.reply_text(f"Reloaded offers. Now: {len(OFFERS_ALL)} offers.")

async def debug_id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    await update.message.reply_text(
        f"Chat ID: {chat.id}\n"
        f"User ID: {user.id}\n"
        f"Username: @{user.username or 'N/A'}"
    )

# ------------------------- SUPPORT / DONE -------------------------
async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    st = get_state(chat_id)
    if context.user_data.get("support_stage") in ("await_details", "await_optional_screenshot"):
        context.user_data["support_stage"] = None
        context.user_data["support_details"] = None
        context.user_data["support_photos"] = []
        context.user_data["support_issue_code"] = None
        await update.message.reply_text(t(chat_id, "support_saved"), reply_markup=ReplyKeyboardRemove())
        # notify admin
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=f"🛟 SUPPORT TICKET CLOSED via /done\nUser: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})"
            )
        return
    await update.message.reply_text("No active support ticket.", reply_markup=ReplyKeyboardRemove())

# ------------------------- MESSAGE HANDLERS -------------------------
async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    contact: Contact = update.message.contact
    phone = contact.phone_number
    st = get_state(chat_id)
    flow = st.get("flow")
    if st.get("awaiting_phone_reason") == "trial":
        pkg = st.get("trial_pkg")
        if pkg not in PACKAGES:
            await update.message.reply_text("Package not found.", reply_markup=ReplyKeyboardRemove())
            return
        save_trial(chat_id, update.effective_user, pkg, phone)
        await update.message.reply_text(t(chat_id, "trial_recorded"), reply_markup=ReplyKeyboardRemove())
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(f"🧪 TRIAL (contact share)\nUser: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})\n"
                      f"Phone: {phone}\nPackage: {pkg}")
            )
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None, trial_pkg=None)
        return

    save_customer(chat_id, update.effective_user, flow, phone)
    await update.message.reply_text(t(chat_id, "phone_saved"), reply_markup=ReplyKeyboardRemove())
    if ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=(f"💳 CUSTOMER (contact share)\nUser: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})\n"
                  f"Phone: {phone}\nFlow: {flow or 'N/A'}")
        )
    set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if context.user_data.get("support_stage") == "await_optional_screenshot":
        context.user_data.setdefault("support_photos", []).append(update.message.photo[-1].file_id)
        await update.message.reply_text("✅ Screenshot received. You can send more or type /done to finish.")
        return
    await update.message.reply_text(t(chat_id, "welcome"), reply_markup=main_menu_kb(chat_id))

async def any_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    txt = (update.message.text or "").strip()
    st = get_state(chat_id)

    if st.get("awaiting_username_reason") == "renew":
        set_state(chat_id, awaiting_username=False, awaiting_username_reason=None)
        save_customer(chat_id, update.effective_user, "renew", None, extra={"username": txt})
        await update.message.reply_text(t(chat_id, "username_saved"), reply_markup=ReplyKeyboardRemove())
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(f"♻️ RENEW (username)\nUser: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})\n"
                      f"Username: {txt}")
            )
        return

    if context.user_data.get("support_stage") == "await_details":
        context.user_data["support_details"] = txt
        context.user_data["support_stage"] = "await_optional_screenshot"
        await update.message.reply_text(t(chat_id, "support_ask_screenshot"))
        return

    if txt == "/start":
        await start(update, context)
        return

    await update.message.reply_text(t(chat_id, "welcome"), reply_markup=main_menu_kb(chat_id))

# ------------------------- CALLBACK HANDLER -------------------------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat.id
    user = q.from_user
    data = (q.data or "").strip()
    st = get_state(chat_id)

    if data.startswith("lang|"):
        _, lang = data.split("|", 1)
        if lang not in ("ar", "en"):
            lang = "ar"
        set_state(chat_id, lang=lang, awaiting_phone=False, awaiting_phone_reason=None,
                  awaiting_username=False, awaiting_username_reason=None, flow=None, trial_pkg=None)
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "welcome"), main_menu_kb(chat_id))
        return

    if data == "back_home":
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None,
                  awaiting_username=False, awaiting_username_reason=None, flow=None)
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "welcome"), main_menu_kb(chat_id))
        return

    # ===== More Info (summary + links) =====
    if data == "more_info":
        text = t(chat_id, "more_info_title") + "\n\n" + t(chat_id, "more_info_body_compact")
        await safe_edit_or_send(q, context, chat_id, text, more_info_summary_kb(chat_id), no_preview=True)
        return

    if data == "players_links":
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "players_links_title"), players_links_kb(chat_id))
        return

    if data == "back_more_info":
        text = t(chat_id, "more_info_title") + "\n\n" + t(chat_id, "more_info_body_compact")
        await safe_edit_or_send(q, context, chat_id, text, more_info_summary_kb(chat_id), no_preview=True)
        return

    if data.startswith("player_links|"):
        _, which = data.split("|", 1)
        if which == "iplay":
            await safe_edit_or_send(q, context, chat_id, t(chat_id, "player_iplay_body"), players_links_kb(chat_id))
            return
        if which == "splayer":
            await safe_edit_or_send(q, context, chat_id, t(chat_id, "player_splayer_body"), players_links_kb(chat_id))
            return
        if which == "000":
            await safe_edit_or_send(q, context, chat_id, t(chat_id, "player_000_body"), players_links_kb(chat_id))
            return
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "players_links_title"), players_links_kb(chat_id))
        return

    # Subscribe
    if data == "subscribe":
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "subscribe_pick"), packages_kb())
        set_state(chat_id, flow="subscribe")
        return

    # Renew
    if data == "renew":
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "subscribe_pick"), packages_kb())
        set_state(chat_id, flow="renew")
        return

    # Trial
    if data == "trial":
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "trial_pick"), trial_packages_kb())
        return

    if data.startswith("trial_pkg|"):
        _, pkg_name = data.split("|", 1)
        if pkg_name not in PACKAGES:
            await safe_edit_or_send(q, context, chat_id, "Package not found.", trial_packages_kb())
            return
        set_state(chat_id, trial_pkg=pkg_name, awaiting_phone=True, awaiting_phone_reason="trial")
        await _send_phone_prompt(context, chat_id)
        return

    # Support
    if data == "support":
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "support_pick"), support_issues_kb(chat_id))
        return

    if data.startswith("support_issue|"):
        # Avoid duplicate prompt
        if context.user_data.get("support_stage") in ("await_details", "await_optional_screenshot"):
            await q.answer("Support ticket already open. Please describe the issue or send /done.")
            return

        _, code = data.split("|", 1)
        tid = save_jsonl(SUPPORT_FILE, {
            "chat_id": chat_id,
            "user_id": user.id,
            "username": user.username,
            "name": user.full_name,
            "issue_code": code,
            "ts_utc": _utcnow().isoformat(),
            "ts_uae": _now_uae().isoformat(),
        })
        context.user_data["support_stage"] = "await_details"
        context.user_data["support_issue_code"] = code
        context.user_data["support_details"] = None
        context.user_data["support_photos"] = []

        await safe_edit_or_send(q, context, chat_id, t(chat_id, "support_ask_details"), None)
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(f"🛟 SUPPORT OPENED (seed #{tid})\nIssue: {code}\n"
                      f"User: @{user.username or 'N/A'} ({user.id})")
            )
        return

    # Offers
    if data == "offers":
        acts = active_offers()
        if not acts:
            await safe_edit_or_send(q, context, chat_id, t(chat_id, "offers_none"),
                                    InlineKeyboardMarkup([[InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="back_home")]]))
            return
        rows = []
        for idx, o in enumerate(acts):
            title = o["title_ar"] if get_state(chat_id).get("lang","ar")=="ar" else o["title_en"]
            rows.append([InlineKeyboardButton(title, callback_data=f"offer_act|{idx}")])
        rows.append([InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="back_home")])
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "offers_title"), InlineKeyboardMarkup(rows))
        return

    if data.startswith("offer_act|"):
        _, sidx = data.split("|", 1)
        try:
            idx = int(sidx)
        except Exception:
            await safe_edit_or_send(q, context, chat_id, t(chat_id, "offers_none"), main_menu_kb(chat_id))
            return
        acts = active_offers()
        if idx < 0 or idx >= len(acts):
            await safe_edit_or_send(q, context, chat_id, t(chat_id, "offers_none"), main_menu_kb(chat_id))
            return
        offer = acts[idx]
        lang = get_state(chat_id).get("lang", "ar")
        text = _fmt_offer(offer, lang)
        await safe_edit_or_send(q, context, chat_id, text, InlineKeyboardMarkup([
            [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="offers")]
        ]))
        return

# ------------------------- ERROR HANDLER -------------------------
async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Handler error: %s", context.error)

# ------------------------- STARTUP -------------------------
async def _post_init(application: Application):
    try:
        if WEBHOOK_URL:
            await application.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
        else:
            await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning("Webhook init/cleanup failed: %s", e)
    # Setup bot commands (left-side menu)
    try:
        base_commands = [
            BotCommand("start", "Start / Pick language"),
            BotCommand("packages", "Packages & subscription"),
            BotCommand("offers", "Current offers"),
            BotCommand("renew", "Renew subscription"),
            BotCommand("trial", "Free trial"),
            BotCommand("support", "Support / contact us"),
        ]
        # Default commands for all users
        await application.bot.set_my_commands(base_commands)

        # Extra admin commands (visible only in admin chat)
        if ADMIN_CHAT_ID:
            admin_commands = base_commands + [
                BotCommand("status", "Admin: bot status"),
                BotCommand("offers_now", "Admin: active offers"),
                BotCommand("upcoming_offers", "Admin: upcoming offers"),
                BotCommand("offer_reload", "Admin: reload offers file"),
                BotCommand("debug_id", "Admin: debug chat/user id"),
            ]
            await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))
    except Exception as e:
        logging.warning("Failed to set bot commands: %s", e)

# ------------------------- MAIN -------------------------
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    global OFFERS_ALL
    OFFERS_ALL = build_embedded_offers()

    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("packages", packages_cmd))
    app.add_handler(CommandHandler("renew", renew_cmd))
    app.add_handler(CommandHandler("trial", trial_cmd))
    app.add_handler(CommandHandler("support", support_cmd))
    app.add_handler(CommandHandler("offers", offers_cmd))
    app.add_handler(CommandHandler("done", done_cmd))  # support finalize

    # Admin
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("offers_now", offers_now_cmd))
    app.add_handler(CommandHandler("upcoming_offers", upcoming_offers_cmd))
    app.add_handler(CommandHandler("offer_reload", offer_reload_cmd))
    app.add_handler(CommandHandler("debug_id", debug_id_cmd))

    # Buttons
    app.add_handler(CallbackQueryHandler(on_button))

    # Messages
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_text))

    app.add_error_handler(handle_error)

    if WEBHOOK_URL:
        port = int(os.getenv("PORT", "10000"))
        logging.info("Starting webhook on 0.0.0.0:%s with webhook_url=%s", port, WEBHOOK_URL)
        app.run_webhook(listen="0.0.0.0", port=port, url_path="", webhook_url=WEBHOOK_URL, drop_pending_updates=True)
    else:
        logging.info("Starting polling.")
        app.run_polling(allowed_updates=None, drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
