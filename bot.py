import asyncio
import json
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# =====================
# CONFIG
# =====================
# ⚠️ Не храните токен в открытом виде. Вставьте сюда свой токен после /revoke в BotFather.
TOKEN = os.getenv("BOT_TOKEN", "").strip() or "PASTE_YOUR_BOT_TOKEN_HERE"

ADMIN_FILE = "admin.json"
ADMIN_USERNAME = "@BenBell97"
SUPPORT_URL = "https://t.me/BenBell97"

USD_TO_RUB = 77

# Подписки (как на скрине)
SUB_PRICES_USD = {1: 19, 3: 54, 6: 96, 12: 144}

# Пополнение
TOPUP_AMOUNTS_USD = [5, 10, 20, 50, 100]

# СБП реквизиты
SBP_BANK = "Тинькофф"
SBP_TO = "+7 960 234 21 99"
SBP_RECEIVER = "Беллуян Бенуар"

# Crypto адреса
CRYPTO_ADDR = {
    "USDT_TRC20": "TGpr8cPDsQPJj3WYkZcEHyknnpXAuPqo68",
    "BTC": "bc1q5xwqegmn9ncyhyz402l56nlyqgdttg2vjmx2sq",
    "ETH": "0xA873EA0F3872338E02f1131a32862bd714D2fACe",
}

# =====================
# HELPERS
# =====================
def usd_to_rub_rounded(usd: int) -> int:
    rub = usd * USD_TO_RUB
    return int(round(rub / 10.0) * 10)


SUB_PRICES = {m: {"usd": SUB_PRICES_USD[m], "rub": usd_to_rub_rounded(SUB_PRICES_USD[m])} for m in SUB_PRICES_USD}
TOPUP_PRICES = {usd: {"usd": usd, "rub": usd_to_rub_rounded(usd)} for usd in TOPUP_AMOUNTS_USD}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def make_order_id(uid: int) -> str:
    return f"ORD-{uid}-{int(datetime.now().timestamp())}"


def load_admin_id() -> int | None:
    if not os.path.exists(ADMIN_FILE):
        return None
    try:
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        admin_id = data.get("admin_id")
        return int(admin_id) if admin_id else None
    except Exception:
        return None


def save_admin_id(admin_id: int):
    with open(ADMIN_FILE, "w", encoding="utf-8") as f:
        json.dump({"admin_id": int(admin_id)}, f, ensure_ascii=False, indent=2)


def format_user(obj: Message | CallbackQuery) -> str:
    u = obj.from_user
    username = f"@{u.username}" if u.username else "(no username)"
    return f"{username} | id={u.id} | {u.full_name}"


# =====================
# BOT APP
# =====================
if TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE" or not TOKEN or ":" not in TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Put your token into BOT_TOKEN env var or TOKEN constant.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

ADMIN_ID: int | None = load_admin_id()

USER: dict[int, dict] = {}
PENDING: dict[str, dict] = {}


def get_user(uid: int) -> dict:
    if uid not in USER:
        USER[uid] = {
            "lang": "ru",
            "flow": None,          # sub / topup / status
            "step": None,          # wait_topup_email / wait_txid / wait_sbp_receipt / wait_status_creds / choose_coin
            "sub_months": None,
            "topup_usd": None,
            "pay_method": None,    # sbp / crypto
            "coin": None,
            "order_id": None,
            "email": None,
            "license_key": None,
        }
    return USER[uid]


def reset_flow(u: dict):
    u.update({
        "flow": None,
        "step": None,
        "sub_months": None,
        "topup_usd": None,
        "pay_method": None,
        "coin": None,
        "order_id": None,
        "email": None,
        "license_key": None,
    })


async def safe_edit(cb: CallbackQuery, text: str, reply_markup=None):
    """
    Защита от ошибки:
    Bad Request: message is not modified
    """
    try:
        if cb.message:
            await cb.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            # просто игнорируем
            pass
        else:
            raise


# =====================
# KEYBOARDS
# =====================
def kb_language():
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 Русский", callback_data="lang:ru")
    kb.button(text="🇬🇧 English", callback_data="lang:en")
    kb.adjust(1)
    return kb.as_markup()


def kb_main(lang: str):
    kb = InlineKeyboardBuilder()
    if lang == "ru":
        kb.button(text="💳 Купить подписку", callback_data="menu:buy_sub")
        kb.button(text="💰 Пополнить баланс", callback_data="menu:topup")
        kb.button(text="📊 Мой статус", callback_data="menu:status")
        kb.button(text="🆘 Поддержка", callback_data="menu:support")
        kb.button(text="🏠 В начало", callback_data="nav:home")
    else:
        kb.button(text="💳 Buy subscription", callback_data="menu:buy_sub")
        kb.button(text="💰 Top up balance", callback_data="menu:topup")
        kb.button(text="📊 My status", callback_data="menu:status")
        kb.button(text="🆘 Support", callback_data="menu:support")
        kb.button(text="🏠 Home", callback_data="nav:home")
    kb.adjust(1)
    return kb.as_markup()


def kb_support(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Написать в поддержку" if lang == "ru" else "💬 Contact support", url=SUPPORT_URL)
    kb.button(text="🏠 В начало" if lang == "ru" else "🏠 Home", callback_data="nav:home")
    kb.adjust(1)
    return kb.as_markup()


def kb_admin_decision(order_id: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data=f"adm:approve:{order_id}")
    kb.button(text="❌ Отклонить", callback_data=f"adm:reject:{order_id}")
    kb.adjust(2)
    return kb.as_markup()


def kb_cancel_payment(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отменить" if lang == "ru" else "❌ Cancel", callback_data="nav:cancel")
    kb.button(text="🏠 В начало" if lang == "ru" else "🏠 Home", callback_data="nav:home")
    kb.adjust(1)
    return kb.as_markup()


def sub_label(lang: str, months: int) -> str:
    usd = SUB_PRICES[months]["usd"]
    rub = SUB_PRICES[months]["rub"]
    if lang == "ru":
        title = "1 месяц" if months == 1 else ("Годовая" if months == 12 else f"{months} месяца")
        return f"{title} — ${usd} (≈ {rub} ₽)"
    title = "1 month" if months == 1 else ("1 year" if months == 12 else f"{months} months")
    return f"{title} — ${usd} (≈ {rub} RUB)"


def kb_sub_months(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=sub_label(lang, 1), callback_data="sub:1")
    kb.button(text=sub_label(lang, 3), callback_data="sub:3")
    kb.button(text=sub_label(lang, 6), callback_data="sub:6")
    kb.button(text=sub_label(lang, 12), callback_data="sub:12")
    kb.button(text="⚡ Custom", callback_data="sub:custom")
    kb.button(text="⬅️ Назад" if lang == "ru" else "⬅️ Back", callback_data="nav:home")
    kb.button(text="🏠 В начало" if lang == "ru" else "🏠 Home", callback_data="nav:home")
    kb.adjust(1)
    return kb.as_markup()


def kb_topup_amounts(lang: str):
    kb = InlineKeyboardBuilder()
    for usd in TOPUP_AMOUNTS_USD:
        rub = TOPUP_PRICES[usd]["rub"]
        text = f"${usd} (≈ {rub} ₽)" if lang == "ru" else f"${usd} (≈ {rub} RUB)"
        kb.button(text=text, callback_data=f"topup:{usd}")
    kb.button(text="⬅️ Назад" if lang == "ru" else "⬅️ Back", callback_data="nav:home")
    kb.button(text="🏠 В начало" if lang == "ru" else "🏠 Home", callback_data="nav:home")
    kb.adjust(1)
    return kb.as_markup()


def kb_pay_method(lang: str):
    kb = InlineKeyboardBuilder()
    if lang == "ru":
        kb.button(text="🏦 СБП / Карта РФ", callback_data="pay:sbp")
        kb.button(text="₿ Crypto", callback_data="pay:crypto")
        kb.button(text="⬅️ Назад", callback_data="nav:back_prev")
        kb.button(text="❌ Отменить", callback_data="nav:cancel")
        kb.button(text="🏠 В начало", callback_data="nav:home")
    else:
        kb.button(text="🏦 SBP / RU card", callback_data="pay:sbp")
        kb.button(text="₿ Crypto", callback_data="pay:crypto")
        kb.button(text="⬅️ Back", callback_data="nav:back_prev")
        kb.button(text="❌ Cancel", callback_data="nav:cancel")
        kb.button(text="🏠 Home", callback_data="nav:home")
    kb.adjust(1)
    return kb.as_markup()


def kb_crypto_coin(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="USDT TRC20", callback_data="coin:USDT_TRC20")
    kb.button(text="BTC", callback_data="coin:BTC")
    kb.button(text="ETH", callback_data="coin:ETH")
    kb.button(text="⬅️ Назад" if lang == "ru" else "⬅️ Back", callback_data="nav:back_pay")
    kb.button(text="❌ Отменить" if lang == "ru" else "❌ Cancel", callback_data="nav:cancel")
    kb.button(text="🏠 В начало" if lang == "ru" else "🏠 Home", callback_data="nav:home")
    kb.adjust(1)
    return kb.as_markup()


# =====================
# ADMIN BIND
# =====================
@dp.message(Command("admin"))
async def admin_bind(message: Message):
    global ADMIN_ID
    ADMIN_ID = message.from_user.id
    save_admin_id(ADMIN_ID)
    await message.answer("✅ Админ привязан. Теперь заявки будут приходить сюда.")


# =====================
# HOME / CANCEL / NAV
# =====================
@dp.callback_query(F.data == "nav:home")
async def nav_home(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    reset_flow(u)
    await safe_edit(cb, "Главное меню" if u["lang"] == "ru" else "Main menu", reply_markup=kb_main(u["lang"]))
    await cb.answer()


@dp.callback_query(F.data == "nav:cancel")
async def nav_cancel(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    reset_flow(u)
    await safe_edit(cb, "✅ Отменено. Главное меню" if u["lang"] == "ru" else "✅ Cancelled. Main menu",
                    reply_markup=kb_main(u["lang"]))
    await cb.answer()


@dp.callback_query(F.data == "nav:back_prev")
async def back_prev(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    lang = u["lang"]
    if u.get("flow") == "sub":
        await safe_edit(cb, "Выберите вариант подписки" if lang == "ru" else "Choose subscription option",
                        reply_markup=kb_sub_months(lang))
    elif u.get("flow") == "topup":
        await safe_edit(cb, "Выберите сумму пополнения" if lang == "ru" else "Choose top up amount",
                        reply_markup=kb_topup_amounts(lang))
    else:
        await safe_edit(cb, "Главное меню" if lang == "ru" else "Main menu", reply_markup=kb_main(lang))
    await cb.answer()


@dp.callback_query(F.data == "nav:back_pay")
async def back_pay(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    await safe_edit(cb, "Выберите способ оплаты" if u["lang"] == "ru" else "Choose payment method",
                    reply_markup=kb_pay_method(u["lang"]))
    await cb.answer()


# =====================
# START / LANGUAGE
# =====================
@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("Выберите язык / Choose language", reply_markup=kb_language())


@dp.callback_query(F.data.startswith("lang:"))
async def lang_handler(cb: CallbackQuery):
    lang = cb.data.split(":", 1)[1]
    u = get_user(cb.from_user.id)
    u["lang"] = lang
    reset_flow(u)
    await safe_edit(cb, "Главное меню" if lang == "ru" else "Main menu", reply_markup=kb_main(lang))
    await cb.answer()


# =====================
# MENU
# =====================
@dp.callback_query(F.data.startswith("menu:"))
async def menu_handler(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    lang = u["lang"]
    action = cb.data.split(":", 1)[1]

    if action == "buy_sub":
        reset_flow(u)
        u["flow"] = "sub"
        await safe_edit(cb, "Выберите вариант подписки" if lang == "ru" else "Choose subscription option",
                        reply_markup=kb_sub_months(lang))
        await cb.answer()
        return

    if action == "topup":
        reset_flow(u)
        u["flow"] = "topup"
        await safe_edit(cb, "Выберите сумму пополнения" if lang == "ru" else "Choose top up amount",
                        reply_markup=kb_topup_amounts(lang))
        await cb.answer()
        return

    if action == "support":
        await safe_edit(cb, f"Поддержка: {ADMIN_USERNAME}" if lang == "ru" else f"Support: {ADMIN_USERNAME}",
                        reply_markup=kb_support(lang))
        await cb.answer()
        return

    if action == "status":
        reset_flow(u)
        u["flow"] = "status"
        u["step"] = "wait_status_creds"
        txt = (
            "Отправьте email и лицензионный ключ одним сообщением в формате:\nemail | ключ\n\nПример:\n"
            "test@mail.com | ABCD-1234"
            if lang == "ru" else
            "Send email and license key in one message:\nemail | key\n\nExample:\n"
            "test@mail.com | ABCD-1234"
        )
        await safe_edit(cb, txt, reply_markup=kb_cancel_payment(lang))
        await cb.answer()
        return


# =====================
# SUB
# =====================
@dp.callback_query(F.data.startswith("sub:"))
async def sub_handler(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    lang = u["lang"]
    value = cb.data.split(":", 1)[1]

    if value == "custom":
        if not ADMIN_ID:
            await safe_edit(cb, "❗ Админ не привязан. Напишите /admin с аккаунта администратора.",
                            reply_markup=kb_cancel_payment(lang))
            await cb.answer()
            return

        order_id = make_order_id(cb.from_user.id)
        await bot.send_message(
            ADMIN_ID,
            "🟣 CUSTOM REQUEST\n"
            f"Time: {now_str()}\n"
            f"Order: {order_id}\n"
            f"User: {format_user(cb)}\n"
        )
        await safe_edit(cb, "✅ Заявка на Custom отправлена." if lang == "ru" else "✅ Custom request sent.",
                        reply_markup=kb_main(lang))
        await cb.answer()
        return

    u["flow"] = "sub"
    u["sub_months"] = int(value)
    u["order_id"] = make_order_id(cb.from_user.id)

    months = u["sub_months"]
    usd = SUB_PRICES[months]["usd"]
    rub = SUB_PRICES[months]["rub"]

    await safe_edit(
        cb,
        (f"Подписка: {months} мес.\nСумма: {rub} ₽ (≈ ${usd})\n\nВыберите способ оплаты"
         if lang == "ru" else
         f"Subscription: {months} mo.\nAmount: {rub} RUB (≈ ${usd})\n\nChoose payment method"),
        reply_markup=kb_pay_method(lang)
    )
    await cb.answer()


# =====================
# TOPUP
# =====================
@dp.callback_query(F.data.startswith("topup:"))
async def topup_amount_handler(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    lang = u["lang"]

    u["flow"] = "topup"
    u["topup_usd"] = int(cb.data.split(":", 1)[1])
    u["order_id"] = make_order_id(cb.from_user.id)
    u["step"] = "wait_topup_email"

    usd = u["topup_usd"]
    rub = TOPUP_PRICES[usd]["rub"]

    await safe_edit(
        cb,
        (f"Пополнение: ${usd} (≈ {rub} ₽)\n\nТеперь отправьте почту от аккаунта одним сообщением.")
        if lang == "ru" else
        (f"Top up: ${usd} (≈ {rub} RUB)\n\nNow send your account email in one message."),
        reply_markup=kb_cancel_payment(lang)
    )
    await cb.answer()


# =====================
# PAY METHOD
# =====================
@dp.callback_query(F.data.startswith("pay:"))
async def pay_handler(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    lang = u["lang"]
    method = cb.data.split(":", 1)[1]
    u["pay_method"] = method

    # TOPUP needs email
    if u.get("flow") == "topup":
        if not u.get("email"):
            await cb.answer("Сначала укажите email." if lang == "ru" else "Enter email first.")
            return

        usd = u["topup_usd"]
        rub = TOPUP_PRICES[usd]["rub"]

        if method == "sbp":
            u["step"] = "wait_sbp_receipt"
            await safe_edit(
                cb,
                (f"🏦 СБП/перевод\n\n"
                 f"Пополнение: ${usd} (≈ {rub} ₽)\n"
                 f"Email: {u['email']}\n\n"
                 f"Банк: {SBP_BANK}\n"
                 f"Получатель: {SBP_RECEIVER}\n"
                 f"Номер/телефон: {SBP_TO}\n\n"
                 f"После оплаты пришлите сюда ЧЕК/СКРИН (как фото или файл).")
                if lang == "ru" else
                (f"🏦 SBP transfer\n\n"
                 f"Top up: ${usd} (≈ {rub} RUB)\n"
                 f"Email: {u['email']}\n\n"
                 f"Bank: {SBP_BANK}\n"
                 f"Receiver: {SBP_RECEIVER}\n"
                 f"Phone/card: {SBP_TO}\n\n"
                 f"After payment, send RECEIPT/SCREENSHOT here (photo or file)."),
                reply_markup=kb_cancel_payment(lang)
            )
            await cb.answer()
            return

        if method == "crypto":
            u["step"] = "choose_coin"
            await safe_edit(
                cb,
                (f"Пополнение: ${usd} (≈ {rub} ₽)\nEmail: {u['email']}\n\nВыберите монету:")
                if lang == "ru" else
                (f"Top up: ${usd} (≈ {rub} RUB)\nEmail: {u['email']}\n\nChoose coin:"),
                reply_markup=kb_crypto_coin(lang)
            )
            await cb.answer()
            return

    # SUB
    if u.get("flow") == "sub":
        months = u.get("sub_months")
        if not months:
            await cb.answer("Сначала выберите срок подписки." if lang == "ru" else "Choose period first.")
            return

        usd = SUB_PRICES[months]["usd"]
        rub = SUB_PRICES[months]["rub"]

        if method == "sbp":
            u["step"] = "wait_sbp_receipt"
            await safe_edit(
                cb,
                (f"🏦 СБП/перевод\n\n"
                 f"Подписка: {months} мес.\n"
                 f"Сумма: {rub} ₽ (≈ ${usd})\n\n"
                 f"Банк: {SBP_BANK}\n"
                 f"Получатель: {SBP_RECEIVER}\n"
                 f"Номер/телефон: {SBP_TO}\n\n"
                 f"После оплаты пришлите сюда ЧЕК/СКРИН (как фото или файл).")
                if lang == "ru" else
                (f"🏦 SBP transfer\n\n"
                 f"Subscription: {months} mo.\n"
                 f"Amount: {rub} RUB (≈ ${usd})\n\n"
                 f"Bank: {SBP_BANK}\n"
                 f"Receiver: {SBP_RECEIVER}\n"
                 f"Phone/card: {SBP_TO}\n\n"
                 f"After payment, send RECEIPT/SCREENSHOT here (photo or file)."),
                reply_markup=kb_cancel_payment(lang)
            )
            await cb.answer()
            return

        if method == "crypto":
            u["step"] = "choose_coin"
            await safe_edit(
                cb,
                (f"Подписка: {months} мес.\nСумма: {rub} ₽ (≈ ${usd})\n\nВыберите монету:")
                if lang == "ru" else
                (f"Subscription: {months} mo.\nAmount: {rub} RUB (≈ ${usd})\n\nChoose coin:"),
                reply_markup=kb_crypto_coin(lang)
            )
            await cb.answer()
            return

    await cb.answer()


# =====================
# COIN
# =====================
@dp.callback_query(F.data.startswith("coin:"))
async def coin_handler(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    lang = u["lang"]
    u["coin"] = cb.data.split(":", 1)[1]
    u["step"] = "wait_txid"

    address = CRYPTO_ADDR.get(u["coin"], "ADDRESS_NOT_SET")

    if u.get("flow") == "sub":
        months = u["sub_months"]
        usd = SUB_PRICES[months]["usd"]
        rub = SUB_PRICES[months]["rub"]
        head = f"Подписка: {months} мес.\nСумма: {rub} ₽ (≈ ${usd})\nМонета: {u['coin']}"
    else:
        usd = u["topup_usd"]
        rub = TOPUP_PRICES[usd]["rub"]
        head = f"Пополнение: ${usd} (≈ {rub} ₽)\nEmail: {u.get('email')}\nМонета: {u['coin']}"

    await safe_edit(
        cb,
        (f"₿ Crypto оплата\n\n{head}\n\nАдрес для оплаты:\n{address}\n\n"
         f"После оплаты отправьте сюда txid / hash одним сообщением."),
        reply_markup=kb_cancel_payment(lang)
    )
    await cb.answer()


# =====================
# ADMIN APPROVE / REJECT
# =====================
@dp.callback_query(F.data.startswith("adm:"))
async def admin_decision(cb: CallbackQuery):
    if not ADMIN_ID or cb.from_user.id != ADMIN_ID:
        await cb.answer("Not allowed", show_alert=True)
        return

    _, action, order_id = cb.data.split(":", 2)
    req = PENDING.get(order_id)

    if not req:
        await cb.answer("Заявка не найдена/уже обработана", show_alert=True)
        return

    user_id = req["user_id"]

    if action == "approve":
        if req["kind"] == "sub":
            months = req["months"]
            await bot.send_message(user_id, f"✅ Подписка активна на {months} мес.\nСпасибо за оплату!",
                                   reply_markup=kb_main("ru"))
        else:
            usd = req["usd"]
            await bot.send_message(user_id, f"✅ Платёж подтверждён. Баланс пополнен на ${usd}.\nСпасибо!",
                                   reply_markup=kb_main("ru"))

        PENDING.pop(order_id, None)
        await cb.message.reply(f"✅ Подтверждено: {order_id}")
        await cb.answer("OK")
        return

    if action == "reject":
        await bot.send_message(user_id, f"❌ Платёж отклонён. Напишите в поддержку: {ADMIN_USERNAME}",
                               reply_markup=kb_main("ru"))
        PENDING.pop(order_id, None)
        await cb.message.reply(f"❌ Отклонено: {order_id}")
        await cb.answer("OK")
        return


# =====================
# USER MESSAGES
# =====================
@dp.message()
async def message_handler(message: Message):
    u = get_user(message.from_user.id)
    lang = u["lang"]

    # status: email | key
    if u.get("step") == "wait_status_creds":
        text = (message.text or "").strip()
        if "|" not in text:
            await message.answer("Формат: email | ключ" if lang == "ru" else "Format: email | key",
                                 reply_markup=kb_cancel_payment(lang))
            return
        email, key = [x.strip() for x in text.split("|", 1)]
        if "@" not in email or len(key) < 4:
            await message.answer("Проверьте email и ключ." if lang == "ru" else "Please check email and key.",
                                 reply_markup=kb_cancel_payment(lang))
            return

        if ADMIN_ID:
            await bot.send_message(
                ADMIN_ID,
                "🔵 STATUS REQUEST\n"
                f"Time: {now_str()}\n"
                f"User: {format_user(message)}\n"
                f"Email: {email}\n"
                f"Key: {key}\n"
            )

        u["step"] = None
        await message.answer("✅ Принято. В будущем здесь будет подтягиваться баланс/лицензия.",
                             reply_markup=kb_main(lang))
        return

    # topup email
    if u.get("step") == "wait_topup_email":
        email = (message.text or "").strip()
        if "@" not in email or "." not in email:
            await message.answer("Пришлите корректную почту." if lang == "ru" else "Send a valid email.",
                                 reply_markup=kb_cancel_payment(lang))
            return
        u["email"] = email
        u["step"] = None

        usd = u["topup_usd"]
        rub = TOPUP_PRICES[usd]["rub"]
        await message.answer(
            (f"✅ Почта сохранена: {email}\nПополнение: ${usd} (≈ {rub} ₽)\n\nВыберите способ оплаты:")
            if lang == "ru" else
            (f"✅ Email saved: {email}\nTop up: ${usd} (≈ {rub} RUB)\n\nChoose payment method:"),
            reply_markup=kb_pay_method(lang)
        )
        return

    # txid/hash
    if u.get("step") == "wait_txid":
        txid = (message.text or "").strip()
        if not txid or len(txid) < 8:
            await message.answer("Пришлите txid/hash одним сообщением." if lang == "ru" else "Send txid/hash in one message.",
                                 reply_markup=kb_cancel_payment(lang))
            return

        if not ADMIN_ID:
            await message.answer("❗ Админ не привязан. Админ должен написать /admin.",
                                 reply_markup=kb_cancel_payment(lang))
            return

        order_id = u.get("order_id") or make_order_id(message.from_user.id)
        u["order_id"] = order_id

        if u.get("flow") == "sub":
            months = u["sub_months"]
            usd = SUB_PRICES[months]["usd"]
            rub = SUB_PRICES[months]["rub"]
            PENDING[order_id] = {"kind": "sub", "user_id": message.from_user.id, "months": months}
            text = (
                "🟢 PAYMENT (CRYPTO) — SUBSCRIPTION\n"
                f"Time: {now_str()}\n"
                f"Order: {order_id}\n"
                f"User: {format_user(message)}\n"
                f"Subscription: {months} months\n"
                f"Amount: {rub} RUB (≈ ${usd})\n"
                f"Coin: {u.get('coin')}\n"
                f"TXID: {txid}\n"
            )
        else:
            usd = u["topup_usd"]
            rub = TOPUP_PRICES[usd]["rub"]
            PENDING[order_id] = {"kind": "topup", "user_id": message.from_user.id, "usd": usd, "email": u.get("email")}
            text = (
                "🟢 PAYMENT (CRYPTO) — TOPUP\n"
                f"Time: {now_str()}\n"
                f"Order: {order_id}\n"
                f"User: {format_user(message)}\n"
                f"Email: {u.get('email')}\n"
                f"Topup: ${usd} (≈ {rub} RUB)\n"
                f"Coin: {u.get('coin')}\n"
                f"TXID: {txid}\n"
            )

        await bot.send_message(ADMIN_ID, text, reply_markup=kb_admin_decision(order_id))
        u["step"] = None
        await message.answer("✅ Данные получены. Ожидайте подтверждения.", reply_markup=kb_main(lang))
        return

    # SBP receipt
    if u.get("step") == "wait_sbp_receipt":
        if not ADMIN_ID:
            await message.answer("❗ Админ не привязан. Админ должен написать /admin.",
                                 reply_markup=kb_cancel_payment(lang))
            return

        order_id = u.get("order_id") or make_order_id(message.from_user.id)
        u["order_id"] = order_id

        if u.get("flow") == "sub":
            months = u["sub_months"]
            usd = SUB_PRICES[months]["usd"]
            rub = SUB_PRICES[months]["rub"]
            PENDING[order_id] = {"kind": "sub", "user_id": message.from_user.id, "months": months}
            caption = (
                "🟠 PAYMENT (SBP) — SUBSCRIPTION\n"
                f"Time: {now_str()}\n"
                f"Order: {order_id}\n"
                f"User: {format_user(message)}\n"
                f"Subscription: {months} months\n"
                f"Amount: {rub} RUB (≈ ${usd})\n"
            )
        else:
            usd = u["topup_usd"]
            rub = TOPUP_PRICES[usd]["rub"]
            PENDING[order_id] = {"kind": "topup", "user_id": message.from_user.id, "usd": usd, "email": u.get("email")}
            caption = (
                "🟠 PAYMENT (SBP) — TOPUP\n"
                f"Time: {now_str()}\n"
                f"Order: {order_id}\n"
                f"User: {format_user(message)}\n"
                f"Email: {u.get('email')}\n"
                f"Topup: ${usd} (≈ {rub} RUB)\n"
            )

        if message.photo:
            file_id = message.photo[-1].file_id
            await bot.send_photo(ADMIN_ID, file_id, caption=caption, reply_markup=kb_admin_decision(order_id))
            u["step"] = None
            await message.answer("✅ Чек получен. Ожидайте подтверждения.", reply_markup=kb_main(lang))
            return

        if message.document:
            file_id = message.document.file_id
            await bot.send_document(ADMIN_ID, file_id, caption=caption, reply_markup=kb_admin_decision(order_id))
            u["step"] = None
            await message.answer("✅ Чек получен. Ожидайте подтверждения.", reply_markup=kb_main(lang))
            return

        await message.answer("Пришлите чек как ФОТО или ФАЙЛ (document)." if lang == "ru"
                             else "Send receipt as PHOTO or FILE (document).",
                             reply_markup=kb_cancel_payment(lang))
        return

    # fallback
    await message.answer("Откройте меню ниже 👇" if lang == "ru" else "Open the menu below 👇", reply_markup=kb_main(lang))


async def main():
    print("✅ Bot started. Waiting for messages...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
