import os
import logging
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

from aiogram import Bot, Dispatcher, executor, types


# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")


# =========================
# ENV
# =========================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in Render Environment")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in Render Environment")


# =========================
# DB helpers
# =========================
def db_conn():
    # sslmode=require обычно нужен на managed Postgres
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def get_user_by_telegram_id(telegram_id: int):
    """
    Ожидается таблица users со столбцами:
    telegram_id (int/bigint), username (text), balance (numeric/int),
    tariff (text), subscription_until (timestamp), is_admin (bool)

    Если у тебя названия другие — скажи, я подгоню под твою схему.
    """
    con = db_conn()
    try:
        with con.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT telegram_id, username, balance, tariff, subscription_until, is_admin
                FROM users
                WHERE telegram_id = %s
                """,
                (telegram_id,),
            )
            return cur.fetchone()
    finally:
        con.close()


def upsert_user_on_start(telegram_id: int, username: str | None):
    """
    На /start создаём пользователя, если его нет.
    Баланс/тариф/подписка пусть админка уже правит.
    """
    con = db_conn()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (telegram_id, username, balance, tariff, subscription_until, is_admin)
                VALUES (%s, %s, 0, NULL, NULL, FALSE)
                ON CONFLICT (telegram_id)
                DO UPDATE SET username = EXCLUDED.username
                """,
                (telegram_id, username),
            )
        con.commit()
    finally:
        con.close()


def fmt_dt(value):
    if not value:
        return "—"
    # psycopg2 обычно вернёт datetime
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


# =========================
# BOT
# =========================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)


def main_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Мой статус"))
    return kb


@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    # сохраняем/обновляем username
    username = message.from_user.username
    try:
        upsert_user_on_start(message.from_user.id, username)
    except Exception as e:
        log.exception("DB error on /start: %s", e)
        await message.answer("❌ Ошибка базы. Напишите позже или в поддержку.")
        return

    await message.answer(
        "✅ Привет! Я подключен.\n\nНажми «Мой статус», чтобы увидеть подписку и баланс.",
        reply_markup=main_kb(),
    )


@dp.message_handler(lambda m: (m.text or "").strip().lower() == "мой статус")
async def my_status(message: types.Message):
    tid = message.from_user.id

    try:
        user = get_user_by_telegram_id(tid)
    except Exception as e:
        log.exception("DB error on status: %s", e)
        await message.answer("❌ Не могу получить данные из базы. Проверь DATABASE_URL.")
        return

    if not user:
        await message.answer("❌ Вас нет в базе. Нажмите /start", reply_markup=main_kb())
        return

    text = (
        "👤 <b>Ваш статус</b>\n\n"
        f"🆔 ID: <code>{user.get('telegram_id')}</code>\n"
        f"👤 Username: @{user.get('username') or '—'}\n"
        f"💳 Тариф: <b>{user.get('tariff') or '—'}</b>\n"
        f"📅 Подписка до: <b>{fmt_dt(user.get('subscription_until'))}</b>\n"
        f"💰 Баланс: <b>{user.get('balance') if user.get('balance') is not None else '—'}</b>\n"
        f"🛡 Админ: <b>{'да' if user.get('is_admin') else 'нет'}</b>"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=main_kb())


if __name__ == "__main__":
    log.info("✅ Bot started. Waiting for messages...")
    executor.start_polling(dp, skip_updates=True)
