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
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, Contact, InputMediaPhoto
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
    logging.error("Missing BOT_TOKEN env var. Set BOT_TOKEN before running.")
    sys.exit(1)

# ------------------------- TIME/UTILS -------------------------
DUBAI_TZ = ZoneInfo("Asia/Dubai")

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _now_uae() -> datetime:
    return datetime.now(DUBAI_TZ)

def _parse_iso(ts: str) -> datetime:
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def dubai_range_to_utc_iso(start_local: datetime, end_local: datetime) -> tuple[str, str]:
    if start_local.tzinfo is None:
        start_local = start_local.replace(tzinfo=DUBAI_TZ)
    if end_local.tzinfo is None:
        end_local = end_local.replace(tzinfo=DUBAI_TZ)
    return _iso_utc(start_local), _iso_utc(end_local)

# ------------------------- FILE IO -------------------------
HISTORY_FILE = Path("customers.jsonl")
TRIALS_FILE  = Path("trials.jsonl")
SUPPORT_FILE = Path("support.jsonl")

def save_jsonl(path: Path, obj: dict) -> int:
    """Append obj to JSONL with an auto ticket id (line number)."""
    path.touch(exist_ok=True)
    tid = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for tid, _ in enumerate(f, start=1):
                pass
    except Exception:
        tid = 0
    tid = (tid or 0) + 1
    rec = {"id": tid, **obj}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return tid

def iter_jsonl(path: Path):
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items

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
        "details_ar": "\n• أكثر من 10,000 قناة مباشرة\n• 70,000+ فيلم (VOD)\n• 12,000+ مسلسل\n• يعمل على جهاز واحد\n",
        "payment_url": "https://buy.stripe.com/6oU6oIf2t8OQa6kejD5kk03",
    },
    "AECyberTV Executive": {
        "code": "executive",
        "price_aed": 200,
        "trial_hours": 10,
        "details_en": "\n• 16,000+ Live Channels\n• 24,000+ Movies (VOD)\n• 14,000+ Series\n• 2 devices • SD/HD/FHD/4K\n",
        "details_ar": "\n• 16,000+ قناة مباشرة\n• 24,000+ فيلم (VOD)\n• 14,000+ مسلسل\n• جهازان • SD/HD/FHD/4K\n",
        "payment_url": "https://buy.stripe.com/8x23cw07zghi4M0ejD5kk05",
    },
    "AECyberTV Premium": {
        "code": "premium",
        "price_aed": 250,
        "trial_hours": 24,
        "details_en": "\n• Full combo package\n• 65,000+ Live Channels\n• 180,000+ Movies (VOD)\n• 10,000+ Series\n• Priority support\n",
        "details_ar": "\n• باقة كاملة شاملة\n• 65,000+ قناة مباشرة\n• 180,000+ فيلم (VOD)\n• 10,000+ مسلسل\n• دعم أولوية\n",
        "payment_url": "https://buy.stripe.com/eVq00k7A15CE92gdfz5kk01",
    },
}

# ------------------------- OFFERS -------------------------
# ------------------------- OFFERS -------------------------
def build_embedded_offers() -> List[Dict[str, Any]]:
    """AECyberTV official offers schedule (2025–2026)"""
    body_en = (
        "🎬 Enjoy thousands of Live Channels, Movies, and Series!\n"
        "Available for all AECyberTV packages."
    )
    body_ar = (
        "🎬 استمتع بآلاف القنوات والأفلام والمسلسلات!\n"
        "العرض متوفر لجميع باقات AECyberTV."
    )

    # Helper to format Dubai-local → UTC ISO timestamps
    def _range(y1, m1, d1, y2, m2, d2):
        return dubai_range_to_utc_iso(
            datetime(y1, m1, d1, 0, 0, 0, tzinfo=DUBAI_TZ),
            datetime(y2, m2, d2, 23, 59, 59, tzinfo=DUBAI_TZ),
        )

    offers = []

    # 1️⃣ Early Offer (from now until Dec 1)
    s, e = _range(2025, 11, 6, 2025, 11, 30)
    offers.append({
        "id": "early_offer_nov2025",
        "title_en": "🕐 Early Bird Offer — Until UAE National Day",
        "title_ar": "🕐 عرض ما قبل اليوم الوطني",
        "body_en": (
            f"{body_en}\n\n"
            "📅 Valid until 30 Nov 2025\n\n"
            "💰 Prices:\n"
            "• Casual – 50 AED/year\n"
            "• Executive – 150 AED/year\n"
            "• Premium – 200 AED/year\n"
            "• Kids – 50 AED/year"
        ),
        "body_ar": (
            f"{body_ar}\n\n"
            "📅 ساري حتى 30 نوفمبر 2025\n\n"
            "💰 الأسعار:\n"
            "• عادي – 50 درهم/سنة\n"
            "• تنفيذي – 150 درهم/سنة\n"
            "• بريميوم – 200 درهم/سنة\n"
            "• أطفال – 50 درهم/سنة"
        ),
        "cta_url": "https://buy.stripe.com/bJedRa6vXe9aa6k1wR5kk06",
        "start_at": s, "end_at": e, "priority": 100
    })

    # 2️⃣ UAE National Day (Dec 1–7)
    s, e = _range(2025, 12, 1, 2025, 12, 7)
    offers.append({
        "id": "uae_national_day_2025",
        "title_en": "🇦🇪 UAE National Day — Eid Al-Etihad 54% OFF",
        "title_ar": "🇦🇪 عرض اليوم الوطني — عيد الاتحاد خصم 54%",
        "body_en": (
            f"{body_en}\n\n"
            "📅 1–7 December 2025\n\n"
            "💰 Discounted Prices:\n"
            "• Casual – 34.6 AED/year\n"
            "• Executive – 95 AED/year\n"
            "• Premium – 115 AED/year\n"
            "• Kids – 32 AED/year"
        ),
        "body_ar": (
            f"{body_ar}\n\n"
            "📅 من 1 إلى 7 ديسمبر 2025\n\n"
            "💰 الأسعار بعد الخصم:\n"
            "• عادي – 34.6 درهم/سنة\n"
            "• تنفيذي – 95 درهم/سنة\n"
            "• بريميوم – 115 درهم/سنة\n"
            "• أطفال – 32 درهم/سنة"
        ),
        "cta_url": "https://buy.stripe.com/bJedRa6vXe9aa6k1wR5kk06",
        "start_at": s, "end_at": e, "priority": 200
    })

    # 3️⃣ Christmas & New Year (Dec 24–Jan 5)
    s, e = _range(2025, 12, 24, 2026, 1, 5)
    offers.append({
        "id": "xmas_newyear_2025_2026",
        "title_en": "🎄 Christmas & New Year Offer",
        "title_ar": "🎄 عرض الكريسماس ورأس السنة",
        "body_en": (
            f"{body_en}\n\n"
            "📅 24 Dec 2025 – 5 Jan 2026\n\n"
            "💰 Prices:\n"
            "• Casual – 50 AED/year\n"
            "• Executive – 150 AED/year\n"
            "• Premium – 200 AED/year\n"
            "• Kids – 50 AED/year"
        ),
        "body_ar": (
            f"{body_ar}\n\n"
            "📅 من 24 ديسمبر 2025 حتى 5 يناير 2026\n\n"
            "💰 الأسعار:\n"
            "• عادي – 50 درهم/سنة\n"
            "• تنفيذي – 150 درهم/سنة\n"
            "• بريميوم – 200 درهم/سنة\n"
            "• أطفال – 50 درهم/سنة"
        ),
        "cta_url": "https://buy.stripe.com/bJedRa6vXe9aa6k1wR5kk06",
        "start_at": s, "end_at": e, "priority": 150
    })

    return sorted(offers, key=lambda x: int(x.get("priority", 0)), reverse=True)

OFFERS_ALL: List[Dict[str, Any]] = []


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

def save_customer(chat_id: int, user, package: Optional[str], phone: Optional[str], extra: Optional[dict]=None) -> None:
    rec = {
        "chat_id": chat_id,
        "user_id": user.id,
        "username": user.username,
        "name": user.full_name,
        "package": package,
        "phone": phone,
        "ts": _now_uae().isoformat(timespec="seconds"),
    }
    if extra:
        rec.update(extra)
    try:
        with HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logging.error("Failed to write customers.jsonl: %s", e)

# ------------------------- I18N -------------------------
BRAND = "AECyberTV"
I18N = {
    "pick_lang": {"ar": "اختر اللغة:", "en": "Choose your language:"},
    "lang_ar": {"ar": "العربية", "en": "Arabic"},
    "lang_en": {"ar": "English", "en": "English"},
    "welcome": {
        "ar": f"مرحباً بك في {BRAND}!\n\nكيف نقدر نساعدك اليوم؟",
        "en": f"Welcome to {BRAND}!\n\nHow can we help you today?",
    },
    "more_info_title": {"ar": "📥 طريقة المشاهدة باستخدام 000 Player", "en": "📥 How to Watch with 000 Player"},
    "more_info_body": {
        "ar": (
            "1) ثبّت تطبيق 000 Player:\n"
            "   • iPhone/iPad: App Store\n"
            "   • Android/TV: Google Play\n"
            "   • Firestick/Android TV (Downloader): http://aftv.news/6913771\n"
            "   • Web (PC, PlayStation, Xbox): https://my.splayer.in\n\n"
            "2) أدخل رقم السيرفر: 7765\n"
            "3) بعد الدفع والتفعيل، نرسل لك بيانات الدخول."
        ),
        "en": (
            "1) Install 000 Player:\n"
            "   • iPhone/iPad: App Store\n"
            "   • Android/TV: Google Play\n"
            "   • Firestick/Android TV (Downloader): http://aftv.news/6913771\n"
            "   • Web (PC, PlayStation, Xbox): https://my.splayer.in\n\n"
            "2) Enter Server Number: 7765\n"
            "3) After payment & activation, we will send your login details."
        ),
    },
    "btn_more_info": {"ar": "📋 معلومات", "en": "📋 More Info"},
    "btn_subscribe": {"ar": "💳 اشتراك", "en": "💳 Subscribe"},
    "btn_renew": {"ar": "♻️ تجديد", "en": "♻️ Renew"},
    "btn_trial": {"ar": "🧪 تجربة مجانية", "en": "🧪 Free Trial"},
    "btn_support": {"ar": "🛟 دعم فني", "en": "🛟 Support"},
    "btn_offers": {"ar": "🎁 العروض", "en": "🎁 Offers"},
    "btn_back": {"ar": "⬅️ رجوع", "en": "⬅️ Back"},
    "subscribe_pick": {"ar": "اختر الباقة:", "en": "Please choose a package:"},
    "terms": {
        "ar": (
            "✅ الشروط والملاحظات\n\n"
            "• التفعيل بعد تأكيد الدفع.\n"
            "• حساب واحد لكل جهاز ما لم تذكر الباقة غير ذلك.\n"
            "• الاستخدام على عدة أجهزة قد يسبب تقطيع أو إيقاف الخدمة.\n"
            "• لا توجد استرجاعات بعد التفعيل.\n\n"
            "هل توافق على المتابعة؟"
        ),
        "en": (
            "✅ Terms & Notes\n\n"
            "• Activation after payment confirmation.\n"
            "• One account per device unless package allows more.\n"
            "• Using multiple devices may cause buffering or stop service.\n"
            "• No refunds after activation.\n\n"
            "Do you agree to proceed?"
        ),
    },
    "btn_agree": {"ar": "✅ أوافق", "en": "✅ I Agree"},
    "payment_instructions": {
        "ar": "💳 الدفع\n\nاضغط (ادفع الآن) لإتمام الدفع. ثم ارجع واضغط (دفعت).",
        "en": "💳 Payment\n\nTap (Pay Now) to complete payment. Then return and press (I Paid).",
    },
    "btn_pay_now": {"ar": "🔗 ادفع الآن", "en": "🔗 Pay Now"},
    "btn_paid": {"ar": "✅ دفعت", "en": "✅ I Paid"},
    "thank_you": {
        "ar": f"🎉 شكراً لاختيارك {BRAND}!",
        "en": f"🎉 Thank you for choosing {BRAND}!",
    },
    "breadcrumb_sel": {"ar": "🧩 تم حفظ اختيارك: {pkg} ({price} درهم)", "en": "🧩 Selection saved: {pkg} ({price} AED)"},
    "breadcrumb_agree": {"ar": "✅ وافق على المتابعة: {pkg}", "en": "✅ Agreed to proceed: {pkg}"},
    "breadcrumb_paid": {
        "ar": "🧾 تم الضغط على (دفعت)\n• الباقة: {pkg}\n• الوقت: {ts}",
        "en": "🧾 Payment confirmation clicked\n• Package: {pkg}\n• Time: {ts}",
    },
    "phone_request": {
        "ar": "📞 شارك رقم هاتفك للتواصل.\nاضغط (مشاركة رقمي) أو اكتب الرقم مع رمز الدولة (مثل +9715xxxxxxx).",
        "en": "📞 Please share your phone number.\nTap (Share my number) or type it including country code (e.g., +9715xxxxxxx).",
    },
    "btn_share_phone": {"ar": "📲 مشاركة رقمي", "en": "📲 Share my number"},
    "phone_saved": {"ar": "✅ تم حفظ رقمك. سنتواصل معك قريباً.", "en": "✅ Number saved. We’ll contact you soon."},

    # Offers
    "offers_title": {"ar": "🎁 العروض الحالية", "en": "🎁 Current Offers"},
    "offers_none": {
        "ar": "لا توجد عروض حالياً. راجعنا لاحقاً 🌟",
        "en": "No offers right now. Check back soon 🌟",
    },

    # Renew / Username
    "ask_username": {
        "ar": "👤 اكتب اسم المستخدم (username) المستخدم في التطبيق للتجديد.",
        "en": "👤 Please type the account username you use in the player for renewal.",
    },
    "username_saved": {
        "ar": "✅ تم حفظ اسم المستخدم.",
        "en": "✅ Username saved.",
    },

    # Trial
    "trial_pick": {
        "ar": "🧪 اختر باقة للتجربة المجانية (مرة كل 30 يومًا لكل رقم ولكل باقة):",
        "en": "🧪 Choose a package for the free trial (once every 30 days per phone per package):",
    },
    "trial_recorded": {
        "ar": "✅ تم تسجيل طلب التجربة. سيتم التواصل معك لإرسال البيانات.",
        "en": "✅ Trial request recorded. We’ll contact you to send credentials.",
    },
    "trial_cooldown": {
        "ar": "❗️ تم استخدام تجربة باقة «{pkg}» مؤخرًا لهذا الرقم. اطلب تجربة جديدة بعد ~{days} يومًا.",
        "en": "❗️ A trial for “{pkg}” was used recently for this number. Please try again in ~{days} days.",
    },

    # Support
    "support_pick": {"ar": "🛟 اختر نوع المشكلة:", "en": "🛟 Choose an issue:"},
    "support_detail_prompt": {
        "ar": "اشرح المشكلة بالتفصيل.\nيمكنك إرسال لقطة شاشة إن وجدت، أو أرسل /done للإرسال.",
        "en": "Describe the issue in detail.\nYou may send a screenshot if available, or send /done to submit.",
    },
    "support_saved": {
        "ar": "✅ تم تسجيل البلاغ وسنتواصل معك قريبًا.",
        "en": "✅ Your support ticket is recorded. We will contact you soon.",
    },
}

def t(chat_id: int, key: str) -> str:
    lang = get_state(chat_id).get("lang", "ar")
    val = I18N.get(key)
    if isinstance(val, dict):
        return val.get(lang, val.get("en", ""))
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

def packages_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(pkg, callback_data=f"pkg|{pkg}")] for pkg in PACKAGES.keys()]
    rows.append([InlineKeyboardButton(I18N["btn_back"]["ar"] + " / " + I18N["btn_back"]["en"], callback_data="back_home")])
    return InlineKeyboardMarkup(rows)

def agree_kb(chat_id: int, pkg_name: str, reason: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_agree"), callback_data=f"agree|{reason}|{pkg_name}")],
        [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="back_home")],
    ])

def pay_kb(chat_id: int, pkg_name: str, reason: str) -> InlineKeyboardMarkup:
    pay_url = PACKAGES[pkg_name]["payment_url"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_pay_now"), url=pay_url)],
        [InlineKeyboardButton(t(chat_id, "btn_paid"), callback_data=f"paid|{reason}|{pkg_name}")],
        [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="back_home")],
    ])

def trial_packages_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{pkg} — {PACKAGES[pkg]['trial_hours']}h", callback_data=f"trial_pkg|{pkg}")]
            for pkg in PACKAGES.keys()]
    rows.append([InlineKeyboardButton(I18N["btn_back"]["ar"] + " / " + I18N["btn_back"]["en"], callback_data="back_home")])
    return InlineKeyboardMarkup(rows)

def support_issues_kb(chat_id: int) -> InlineKeyboardMarkup:
    issues = [
        ("login", "🚪 Login/Activation"),
        ("buffer", "🌐 Buffering / Speed"),
        ("channels", "📺 Missing Channel"),
        ("billing", "💳 Billing / Payment"),
        ("other", "🧩 Other"),
    ]
    rows = [[InlineKeyboardButton(lbl, callback_data=f"support_issue|{code}")] for code, lbl in issues]
    rows.append([InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="back_home")])
    return InlineKeyboardMarkup(rows)

def phone_request_kb(chat_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(t(chat_id, "btn_share_phone"), request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True, input_field_placeholder="Tap to share, or type your number…"
    )

# ------------------------- HELPERS -------------------------
async def safe_edit_or_send(query, context, chat_id: int, text: str,
                            kb, html: bool = False, no_preview: bool = False) -> None:
    """Edits callback message OR sends new message. If kb is ReplyKeyboardMarkup, send only a new message."""
    try:
        if isinstance(kb, ReplyKeyboardMarkup):
            await context.bot.send_message(
                chat_id=chat_id, text=text, reply_markup=kb,
                parse_mode="HTML" if html else None, disable_web_page_preview=no_preview
            )
        else:
            await query.edit_message_text(
                text, reply_markup=kb if isinstance(kb, InlineKeyboardMarkup) else None,
                parse_mode="HTML" if html else None, disable_web_page_preview=no_preview,
            )
    except Exception as e:
        logging.warning("safe_edit_or_send fallback: %s", e)
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=text, reply_markup=kb,
                parse_mode="HTML" if html else None, disable_web_page_preview=no_preview
            )
        except Exception as e2:
            logging.error("send_message failed: %s", e2)

def pkg_details_for_lang(pkg_name: str, lang: str) -> str:
    pkg = PACKAGES.get(pkg_name)
    if not pkg:
        return ""
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

async def _send_phone_prompt(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Single, non-duplicated phone prompt."""
    await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "phone_request"), reply_markup=phone_request_kb(chat_id))

# ------------------------- FLOWS (post-phone continuation) -------------------------
async def _post_phone_continuations(update: Update, context: ContextTypes.DEFAULT_TYPE, phone: str):
    chat_id = update.effective_chat.id
    st = get_state(chat_id)
    reason = st.get("awaiting_phone_reason")

    # SUBSCRIBE
    if reason == "subscribe":
        await update.message.reply_text(t(chat_id, "thank_you"), reply_markup=main_menu_kb(chat_id))
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)
        return

    # OFFER
    if reason == "offer":
        await update.message.reply_text(t(chat_id, "thank_you"), reply_markup=main_menu_kb(chat_id))
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)
        return

    # RENEW (username already captured)
    if reason == "renew":
        await update.message.reply_text(t(chat_id, "thank_you"), reply_markup=main_menu_kb(chat_id))
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None, awaiting_username=False, awaiting_username_reason=None)
        return

    # TRIAL (per phone PER PACKAGE cooldown 30d)
    if reason == "trial":
        pkg = st.get("trial_pkg")
        last_ok = None
        for r in iter_jsonl(TRIALS_FILE):
            if r.get("phone") == phone and r.get("package") == pkg:
                try:
                    when = datetime.fromisoformat(r.get("created_at"))
                except Exception:
                    when = _now_uae()
                if not last_ok or when > last_ok:
                    last_ok = when
        if last_ok and (_now_uae() - last_ok) < timedelta(days=30):
            days_left = 30 - (_now_uae() - last_ok).days
            msg = I18N["trial_cooldown"]["ar" if get_state(chat_id).get("lang", "ar") == "ar" else "en"].format(pkg=pkg, days=days_left)
            await update.message.reply_text(msg, reply_markup=main_menu_kb(chat_id))
            set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None, trial_pkg=None)
            return

        hours = PACKAGES[pkg]["trial_hours"] if pkg in PACKAGES else 0
        tid = save_jsonl(TRIALS_FILE, {
            "tg_chat_id": chat_id,
            "tg_user_id": update.effective_user.id,
            "tg_username": update.effective_user.username,
            "phone": phone,
            "package": pkg,
            "trial_hours": hours,
            "created_at": _now_uae().isoformat(),
            "status": "open"
        })
        await update.message.reply_text(t(chat_id, "trial_recorded"), reply_markup=main_menu_kb(chat_id))
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(f"🧪 NEW TRIAL REQUEST\nTicket #{tid}\n"
                      f"User: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})\n"
                      f"Phone: {phone}\nPackage: {pkg}\nHours: {hours}")
            )
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None, trial_pkg=None)
        return

    # SUPPORT
    if reason == "support":
        await update.message.reply_text(t(chat_id, "support_saved"), reply_markup=main_menu_kb(chat_id))
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)
        return

# ------------------------- HANDLERS -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(t(chat_id, "pick_lang"), reply_markup=lang_kb())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

# Admin/utility commands
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Admin only.")
        return
    mode = "webhook" if WEBHOOK_URL else "polling"
    await update.message.reply_text(
        f"✅ Status\nMode: {mode}\nUTC: {_utcnow().strftime('%Y-%m-%d %H:%M:%S')}\nUAE: {_now_uae().strftime('%Y-%m-%d %H:%M:%S')}\nActive offers: {len(active_offers())}"
    )

async def offers_now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Admin only.")
        return
    acts = active_offers()
    if not acts:
        await update.message.reply_text("No active offers.")
        return
    lines = ["Active offers:"]
    for o in acts:
        lines.append(_fmt_offer(o, get_state(update.effective_chat.id).get("lang","ar")))
    await update.message.reply_text("\n".join(lines))

async def upcoming_offers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Admin only.")
        return
    ups = upcoming_offers()
    if not ups:
        await update.message.reply_text("No upcoming offers.")
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
    await update.message.reply_text("Offers reloaded.")

async def debug_id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Your Telegram user id: {update.effective_user.id}")

# Text / Contact / Photos
async def any_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    st = get_state(chat_id)
    txt = (update.message.text or "").strip()

    # Support details flow
    if context.user_data.get("support_stage") == "await_details":
        context.user_data["support_details"] = txt
        context.user_data["support_stage"] = "await_optional_screenshot"
        await update.message.reply_text(t(chat_id, "support_detail_prompt"))
        return

    # Username flow (renew)
    if st.get("awaiting_username") and st.get("awaiting_username_reason") == "renew":
        set_state(chat_id, awaiting_username=False)
        save_customer(chat_id, update.effective_user, st.get("package"), st.get("phone"), extra={"username_for_renew": txt})
        await update.message.reply_text(t(chat_id, "username_saved"))
        set_state(chat_id, awaiting_phone=True, awaiting_phone_reason="renew")
        await _send_phone_prompt(context, chat_id)
        return

    # Phone capture by text
    if st.get("awaiting_phone") and txt:
        if PHONE_RE.match(txt):
            phone = normalize_phone(txt)
            set_state(chat_id, phone=phone)
            save_customer(chat_id, update.effective_user, st.get("package"), phone)
            if ADMIN_CHAT_ID:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=(f"📞 Phone captured\n"
                              f"User: @{update.effective_user.username or 'N/A'} (id: {update.effective_user.id})\n"
                              f"Name: {update.effective_user.full_name}\n"
                              f"Package: {st.get('package')}\n"
                              f"Phone: {phone}\n"
                              f"Reason: {st.get('awaiting_phone_reason')}")
                    )
                except Exception as e:
                    logging.error("Admin notify (phone) failed: %s", e)
            await update.message.reply_text(t(chat_id, "phone_saved"), reply_markup=ReplyKeyboardRemove())
            await _post_phone_continuations(update, context, phone)
            set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)
            return
        else:
            await update.message.reply_text("❗️Invalid number. Include country code (e.g., +9715xxxxxxx).",
                                            reply_markup=phone_request_kb(chat_id))
            return

    # Default: language or menu
    if "lang" not in st:
        await update.message.reply_text(t(chat_id, "pick_lang"), reply_markup=lang_kb())
    else:
        await update.message.reply_text(t(chat_id, "welcome"), reply_markup=main_menu_kb(chat_id))

async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    contact: Contact = update.message.contact
    phone = normalize_phone(contact.phone_number or "")
    st = get_state(chat_id)
    set_state(chat_id, phone=phone)
    save_customer(chat_id, update.effective_user, st.get("package"), phone)

    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(f"📞 Phone captured via Contact\n"
                      f"User: @{update.effective_user.username or 'N/A'} (id: {update.effective_user.id})\n"
                      f"Name: {update.effective_user.full_name}\n"
                      f"Package: {st.get('package')}\n"
                      f"Phone: {phone}\n"
                      f"Reason: {st.get('awaiting_phone_reason')}")
            )
        except Exception as e:
            logging.error("Admin notify (contact) failed: %s", e)

    await update.message.reply_text(t(chat_id, "phone_saved"), reply_markup=ReplyKeyboardRemove())
    await _post_phone_continuations(update, context, phone)
    set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if context.user_data.get("support_stage") == "await_optional_screenshot":
        photos = update.message.photo or []
        if photos:
            best = photos[-1].file_id
            context.user_data.setdefault("support_photos", []).append(best)
        await update.message.reply_text("✅ Screenshot received. Send more or /done to submit.")
        return

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if context.user_data.get("support_stage") in ("await_details", "await_optional_screenshot"):
        tid = save_jsonl(SUPPORT_FILE, {
            "tg_chat_id": chat_id,
            "tg_user_id": update.effective_user.id,
            "tg_username": update.effective_user.username,
            "details": context.user_data.get("support_details"),
            "photos": context.user_data.get("support_photos", []),
            "created_at": _now_uae().isoformat(),
            "status": "open",
            "issue_code": context.user_data.get("support_issue_code"),
        })
        if ADMIN_CHAT_ID:
            pics = context.user_data.get("support_photos", [])
            text = (f"🛟 NEW SUPPORT TICKET\n"
                    f"Ticket #{tid}\n"
                    f"Issue: {context.user_data.get('support_issue_code')}\n"
                    f"User: @{update.effective_user.username or 'N/A'} ({update.effective_user.id})\n"
                    f"Details: {context.user_data.get('support_details')}\n"
                    f"Photos: {len(pics)}")
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=text)
            if pics:
                media = [InputMediaPhoto(p) for p in pics[:10]]
                try:
                    await context.bot.send_media_group(chat_id=int(ADMIN_CHAT_ID), media=media)
                except Exception:
                    pass
        # clear stages then ask phone
        context.user_data["support_stage"] = None
        context.user_data["support_details"] = None
        context.user_data["support_photos"] = []
        context.user_data["support_issue_code"] = None

        set_state(chat_id, awaiting_phone=True, awaiting_phone_reason="support")
        await _send_phone_prompt(context, chat_id)
    else:
        await update.message.reply_text(t(chat_id, "welcome"), reply_markup=main_menu_kb(chat_id))

# Callback buttons
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

    if "lang" not in st:
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "pick_lang"), lang_kb())
        return

    if data == "back_home":
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None,
                  awaiting_username=False, awaiting_username_reason=None, flow=None)
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "welcome"), main_menu_kb(chat_id))
        return

    if data == "more_info":
        text = t(chat_id, "more_info_title") + "\n\n" + t(chat_id, "more_info_body")
        await safe_edit_or_send(q, context, chat_id, text, main_menu_kb(chat_id), no_preview=True)
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
        # Single prompt (no duplicate)
        await _send_phone_prompt(context, chat_id)
        return

    # Support
    if data == "support":
        set_state(chat_id, awaiting_phone=False, awaiting_phone_reason=None)
        context.user_data["support_stage"] = None
        context.user_data["support_details"] = None
        context.user_data["support_photos"] = []
        context.user_data["support_issue_code"] = None
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "support_pick"), support_issues_kb(chat_id))
        return

    if data.startswith("support_issue|"):
        # FIX: avoid double "describe the issue" prompts
        if context.user_data.get("support_stage") in ("await_details", "await_optional_screenshot"):
            await q.answer("Support ticket already open. Please describe the issue or send /done.")
            return

        _, code = data.split("|", 1)
        tid = save_jsonl(SUPPORT_FILE, {
            "tg_chat_id": chat_id,
            "tg_user_id": user.id,
            "tg_username": user.username,
            "issue_code": code,
            "status": "open",
            "created_at": _now_uae().isoformat(),
        })
        context.user_data["support_ticket_seed"] = tid
        context.user_data["support_issue_code"] = code
        context.user_data["support_stage"] = "await_details"

        # Remove old inline keyboard; then send ONE prompt as a fresh message
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "support_detail_prompt"))

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
        off = acts[idx]
        now = _utcnow()
        if not (_parse_iso(off["start_at"]) <= now <= _parse_iso(off["end_at"])):
            await safe_edit_or_send(q, context, chat_id, t(chat_id, "offers_none"), main_menu_kb(chat_id))
            return
        lang = get_state(chat_id).get("lang", "ar")
        title = off["title_ar"] if lang == "ar" else off["title_en"]
        body  = off["body_ar"]  if lang == "ar" else off["body_en"]
        text = f"🛍️ <b>{title}</b>\n\n{body}\n\n{t(chat_id, 'terms')}"
        await safe_edit_or_send(q, context, chat_id, text,
                                InlineKeyboardMarkup([
                                    [InlineKeyboardButton(t(chat_id, "btn_agree"), callback_data=f"offer_agree|{idx}")],
                                    [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="offers")]
                                ]), html=True)
        return

    if data.startswith("offer_agree|"):
        _, sidx = data.split("|", 1)
        try:
            idx = int(sidx)
        except Exception:
            await safe_edit_or_send(q, context, chat_id, t(chat_id, "offers_none"), main_menu_kb(chat_id))
            return
        acts = active_offers()
        url = (acts[idx].get("cta_url") or "").strip() if 0 <= idx < len(acts) else ""
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "payment_instructions"),
                                InlineKeyboardMarkup([
                                    [InlineKeyboardButton(t(chat_id, "btn_pay_now"), url=url)],
                                    [InlineKeyboardButton(t(chat_id, "btn_paid"), callback_data=f"offer_paid|{idx}")],
                                    [InlineKeyboardButton(t(chat_id, "btn_back"), callback_data="offers")]
                                ]), no_preview=True)
        return

    if data.startswith("offer_paid|"):
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
        ts = _now_uae().strftime("%Y-%m-%d %H:%M:%S")
        await context.bot.send_message(chat_id=chat_id,
                                       text=t(chat_id, "breadcrumb_paid").format(pkg="Offer", ts=ts))
        set_state(chat_id, awaiting_phone=True, awaiting_phone_reason="offer")
        await _send_phone_prompt(context, chat_id)
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID),
                                           text=(f"🆕 Offer I Paid (phone pending)\n"
                                                 f"User: @{user.username or 'N/A'} ({user.id})"))
        return

    # Package selection (subscribe/renew)
    if data.startswith("pkg|"):
        _, pkg_name = data.split("|", 1)
        if pkg_name not in PACKAGES:
            await safe_edit_or_send(q, context, chat_id, "Package not found.", packages_kb())
            return
        set_state(chat_id, package=pkg_name)
        price = PACKAGES[pkg_name]["price_aed"]
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "breadcrumb_sel").format(pkg=pkg_name, price=price))
        lang = get_state(chat_id).get("lang", "ar")
        details = pkg_details_for_lang(pkg_name, lang)
        flow = get_state(chat_id).get("flow", "subscribe")
        text = f"🛍️ <b>{pkg_name}</b>\n💰 <b>{price} AED</b>\n{details}\n{t(chat_id, 'terms')}"
        await safe_edit_or_send(q, context, chat_id, text, agree_kb(chat_id, pkg_name, flow), html=True)
        return

    if data.startswith("agree|"):
        _, reason, pkg_name = data.split("|", 2)
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "breadcrumb_agree").format(pkg=pkg_name))
        await safe_edit_or_send(q, context, chat_id, t(chat_id, "payment_instructions"), pay_kb(chat_id, pkg_name, reason), no_preview=True)
        return

    if data.startswith("paid|"):
        _, reason, pkg_name = data.split("|", 2)
        ts = _now_uae().strftime("%Y-%m-%d %H:%M:%S")
        await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "breadcrumb_paid").format(pkg=pkg_name, ts=ts))

        if reason == "renew":
            set_state(chat_id, awaiting_username=True, awaiting_username_reason="renew")
            await context.bot.send_message(chat_id=chat_id, text=t(chat_id, "ask_username"))
        else:
            set_state(chat_id, awaiting_phone=True, awaiting_phone_reason="subscribe")
            await _send_phone_prompt(context, chat_id)

        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(f"🧾 I Paid clicked\n"
                      f"User: @{user.username or 'N/A'} (id: {user.id})\n"
                      f"Package: {pkg_name}\n"
                      f"Reason: {reason}\n"
                      f"Phone: pending")
            )
        return

    # Fallback
    await safe_edit_or_send(q, context, chat_id, t(chat_id, "welcome"), main_menu_kb(chat_id))

# ------------------------- ERROR HANDLER -------------------------
async def handle_error(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
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

# ------------------------- MAIN -------------------------
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    global OFFERS_ALL
    OFFERS_ALL = build_embedded_offers()

    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
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
