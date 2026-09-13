# -*- coding: utf-8 -*-
"""
Virusgram Bot — aiogram 3.x + SQLite
Guruhlar uchun virus o'yini.
Made by Gubo Studios
"""

import os
import time
import random
import logging
import sqlite3

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.chat_member_updated import (
    ChatMemberUpdatedFilter, JOIN_TRANSITION
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, PreCheckoutQuery, ChatMemberUpdated,
    InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice,
    FSInputFile, BotCommand, BotCommandScopeDefault,
    BotCommandScopeAllGroupChats, Update
)
from aiogram.utils.deep_linking import create_startgroup_link
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont

# ==========================================================
# SOZLAMALAR — .env dan o'qish
# ==========================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID  = int(os.getenv("ADMIN_ID", "0"))
DB_PATH   = os.getenv("DB_PATH", "virusgram.db")
COOLDOWN  = int(os.getenv("COOLDOWN", "0"))   # 0 = o'chirilgan
FOOTER    = "\n\nMade by Gubo Studios"
BASE_DIR  = os.getenv("BASE_DIR", "/root/bot")

if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN .env faylida topilmadi!")
if not ADMIN_ID:
    raise SystemExit("❌ ADMIN_ID .env faylida topilmadi!")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
router = Router()

# ==========================================================
# SQLITE QATLAMI
# ==========================================================
def db_conn():
    return sqlite3.connect(DB_PATH)

def db_init():
    with db_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER NOT NULL,
                chat_id     INTEGER NOT NULL,
                first_name  TEXT,
                viruses     INTEGER DEFAULT 0,
                last_virus  REAL    DEFAULT 0,
                banned      INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        try:
            conn.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
        except Exception:
            pass
        conn.commit()

def db_ensure_user(user_id, chat_id, first_name):
    with db_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users "
            "(user_id, chat_id, first_name, viruses, last_virus, banned) "
            "VALUES (?, ?, ?, 0, 0, 0)",
            (user_id, chat_id, first_name)
        )
        conn.execute(
            "UPDATE users SET first_name = ? WHERE user_id = ? AND chat_id = ?",
            (first_name, user_id, chat_id)
        )
        conn.commit()

def db_get_user(user_id, chat_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT user_id, chat_id, first_name, viruses, last_virus, banned "
            "FROM users WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        ).fetchone()
    if not row:
        return None
    return {"user_id": row[0], "chat_id": row[1], "first_name": row[2],
            "viruses": row[3], "last_virus": row[4], "banned": row[5]}

def db_update_virus(user_id, chat_id, new_total, ts):
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET viruses = ?, last_virus = ? "
            "WHERE user_id = ? AND chat_id = ?",
            (new_total, ts, user_id, chat_id)
        )
        conn.commit()

def db_add_viruses(user_id, chat_id, amount):
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET viruses = MAX(0, viruses + ?) "
            "WHERE user_id = ? AND chat_id = ?",
            (amount, user_id, chat_id)
        )
        conn.commit()

def db_top(chat_id, limit=10):
    with db_conn() as conn:
        return conn.execute(
            "SELECT first_name, viruses FROM users "
            "WHERE chat_id = ? ORDER BY viruses DESC, user_id ASC LIMIT ?",
            (chat_id, limit)
        ).fetchall()

def db_rank(chat_id, viruses):
    with db_conn() as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM users WHERE chat_id = ? AND viruses > ?",
            (chat_id, viruses)
        ).fetchone()[0]
    return cnt + 1

def db_admin_set_balance(user_id, amount):
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET viruses = MAX(0, viruses + ?) WHERE user_id = ?",
            (amount, user_id)
        )
        conn.commit()

def db_admin_reset(user_id):
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET viruses = 0, last_virus = 0 WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()

def db_admin_ban(user_id, ban=1):
    with db_conn() as conn:
        conn.execute("UPDATE users SET banned = ? WHERE user_id = ?",
                     (ban, user_id))
        conn.commit()

def db_admin_stats():
    with db_conn() as conn:
        tu = conn.execute("SELECT COUNT(DISTINCT user_id) FROM users").fetchone()[0]
        tc = conn.execute("SELECT COUNT(DISTINCT chat_id) FROM users").fetchone()[0]
        tv = conn.execute("SELECT COALESCE(SUM(viruses),0) FROM users").fetchone()[0]
        tb = conn.execute("SELECT COUNT(*) FROM users WHERE banned=1").fetchone()[0]
    return tu, tc, tv, tb

def db_all_user_ids():
    with db_conn() as conn:
        rows = conn.execute("SELECT DISTINCT user_id FROM users").fetchall()
    return [r[0] for r in rows]

# ==========================================================
# O'YIN MANTIQI
# ==========================================================
def roll_virus(current_viruses):
    """5 dan kam: +1..+20. 5+ bo'lsa 15% ehtimolda -1..-10."""
    if current_viruses >= 5 and random.random() < 0.15:
        return random.randint(-10, -1)
    return random.randint(1, 20)

# ==========================================================
# SHRIFT
# ==========================================================
def _get_font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

# ==========================================================
# RASM — MARKAZDAN TO'LDIRISH
# ==========================================================
_IMG_CACHE = {}

def _load_image_sorted(img_name, box_size):
    key = f"{img_name}_{box_size[0]}x{box_size[1]}"
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]
    src = os.path.join(BASE_DIR, img_name)
    if not os.path.exists(src):
        logging.warning(f"Rasm topilmadi: {src}")
        _IMG_CACHE[key] = None
        return None
    try:
        base = Image.open(src).convert("RGBA")
    except Exception as e:
        logging.warning(f"Rasm ochilmadi: {e}")
        _IMG_CACHE[key] = None
        return None
    tw, th = box_size
    bw, bh = base.size
    scale = min(tw / bw, th / bh)
    nw, nh = max(1, int(bw * scale)), max(1, int(bh * scale))
    base = base.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    canvas.paste(base, ((tw - nw) // 2, (th - nh) // 2), base)
    base = canvas
    px = base.load()
    pts = []
    for y in range(th):
        for x in range(tw):
            r, g, b, a = px[x, y]
            if a < 50:
                continue
            if r > 240 and g > 240 and b > 240:
                continue
            pts.append((x, y))
    if not pts:
        _IMG_CACHE[key] = None
        return None
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    pts.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    _IMG_CACHE[key] = (base, pts, (cx, cy))
    return base, pts, (cx, cy)

def _draw_image_center_fill(img, d, img_name, box, percent,
                            fill_color, outline_color, W, H):
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    d.rounded_rectangle([x0 - 12, y0 - 12, x1 + 12, y1 + 12],
                        radius=18, fill=(18, 26, 48),
                        outline=(60, 90, 140), width=2)
    cached = _load_image_sorted(img_name, (bw, bh))
    if cached is None:
        d.rounded_rectangle([x0, y0, x1, y1], radius=10,
                            fill=(42, 52, 72), outline=outline_color, width=2)
        if percent > 0:
            y_fill = y1 - (y1 - y0) * percent / 100
            d.rectangle([x0 + 3, y_fill, x1 - 3, y1 - 3], fill=fill_color)
        return
    base, pts, (cx, cy) = cached
    work = base.copy()
    px = work.load()
    total = len(pts)
    n = int(total * percent / 100)
    for i in range(n):
        x, y = pts[i]
        px[x, y] = fill_color
    rnd = random.Random(42 + int(percent * 10))
    start, end = max(0, n - 100), min(total, n + 30)
    dd = ImageDraw.Draw(work)
    for i in range(start, end):
        x, y = pts[i]
        if rnd.random() < 0.3:
            r = rnd.randint(1, 2)
            dd.ellipse([x - r, y - r, x + r, y + r],
                       fill=(220, 255, 230, 230))
    if n > 20:
        for ring in (6, 12, 20):
            dd.ellipse([cx - ring, cy - ring, cx + ring, cy + ring],
                       outline=(200, 255, 220, 120), width=1)
    img.paste(work, (x0, y0), work)

# ==========================================================
# RASM YARATISH
# ==========================================================
def create_virus_image(first_name, viruses, user_id, chat_id):
    W, H = 700, 520
    if viruses <= 100:
        title, img_name = "O'zbekiston xaritasi", "uzbekistan.png"
        current, total = max(0, viruses), 100
        fill_color = (80, 210, 120, 255)
    else:
        title, img_name = "Yer shari", "earth.png"
        current, total = min(viruses, 1000) - 100, 900
        fill_color = (230, 70, 70, 255)
    percent = max(0.0, min(100.0, current * 100.0 / total))
    img = Image.new("RGB", (W, H), (12, 18, 34))
    d = ImageDraw.Draw(img)
    f_title = _get_font(30); f_name = _get_font(26); f_small = _get_font(20)
    f_big = _get_font(52); f_tiny = _get_font(14)
    d.text((30, 20), title, font=f_title, fill=(255, 255, 255))
    _draw_image_center_fill(img, d, img_name, (60, 90, W - 60, 340),
                            percent, fill_color, (130, 170, 220), W, H)
    pct = f"{percent:.0f}%"
    bb = d.textbbox((0, 0), pct, font=f_big)
    d.text((W // 2 - (bb[2] - bb[0]) // 2, 380), pct,
           font=f_big, fill=(255, 255, 255))
    d.text((30, H - 135), f"Ism: {first_name}",
           font=f_name, fill=(255, 255, 255))
    d.text((30, H - 95), f"Jami virus: {viruses}",
           font=f_small, fill=(255, 220, 100))
    d.text((30, H - 60), f"To'lgan: {percent:.1f}%",
           font=f_small, fill=(150, 220, 255))
    d.text((W - 230, H - 30), "Made by Gubo Studios",
           font=f_tiny, fill=(160, 160, 160))
    out = os.path.join(BASE_DIR, f"virus_{chat_id}_{user_id}.png")
    try:
        img.save(out)
    except Exception:
        out = f"virus_{chat_id}_{user_id}.png"
        img.save(out)
    return out

# ==========================================================
# /start — salom + guruhga qo'shish tugmasi
# ==========================================================
@router.message(CommandStart())
async def cmd_start(message):
    name = message.from_user.first_name if message.from_user else "Do'stim"
    text = (
        f"Salom, {name}! 🦠\n\n"
        "Virusgram Bot — guruhda virus to'plash o'yini.\n\n"
        "QOIDALAR:\n"
        "1. /virus — +1 dan +20 gacha virus yuqtirasiz\n"
        "2. 5 virusdan ko'p bo'lsa, 15% ehtimolda -1 dan -10 gacha tushadi\n"
        "3. /top — guruhdagi eng virusli 10 kishi\n"
        "4. /pic — virus kartangiz (rasm)\n"
        "5. /shop — Telegram Stars orqali virus sotib olish\n"
        "6. /profile — shaxsiy statistika\n\n"
        "Omad! 🎯"
    )

    # Guruhga qo'shish havolasi
    try:
        group_link = await create_startgroup_link(bot=message.bot)
    except Exception:
        me = await message.bot.get_me()
        group_link = f"https://t.me/{me.username}?startgroup=true"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Botni guruhga qo'shish", url=group_link)],
        [InlineKeyboardButton(text="🛒 Virus do'koni", callback_data="open_shop")],
    ])
    await message.answer(text, reply_markup=kb)

# ==========================================================
# /help
# ==========================================================
@router.message(Command("help"))
async def cmd_help(message):
    text = (
        "📖 Mavjud komandalar:\n\n"
        "/start   — qoidalar va salomlashuv\n"
        "/help    — shu ro'yxat\n"
        "/virus   — tasodifiy virus yuqtirish\n"
        "/top     — guruh bo'yicha TOP-10\n"
        "/pic     — virus kartangiz (rasm)\n"
        "/profile — shaxsiy statistika\n"
        "/shop    — Telegram Stars orqali virus sotib olish"
    )
    if message.from_user and message.from_user.id == ADMIN_ID:
        text += "\n\n👑 Admin:\n/admin — admin panel"
    await message.answer(text)

# ==========================================================
# /virus
# ==========================================================
@router.message(Command("virus"))
async def cmd_virus(message):
    try:
        if not message.from_user:
            return
        uid, cid = message.from_user.id, message.chat.id
        name = message.from_user.first_name or "Do'stim"
        db_ensure_user(uid, cid, name)
        user = db_get_user(uid, cid)

        if user.get("banned"):
            await message.reply(f"{name}, siz banlangansiz 🚫")
            return

        now, last = time.time(), user["last_virus"] or 0
        if COOLDOWN > 0 and last and (now - last) < COOLDOWN:
            rem = COOLDOWN - (now - last)
            h, m = int(rem // 3600), int((rem % 3600) // 60)
            if rem % 60 > 0:
                m += 1
            await message.reply(
                f"{name}, yana {h} soat {m} daqiqa kuting" if h > 0
                else f"{name}, yana {m} daqiqa kuting"
            )
            return

        delta = roll_virus(user["viruses"])
        new_total = max(0, user["viruses"] + delta)
        db_update_virus(uid, cid, new_total, now)

        if delta > 0:
            text = f"{name}, sizga +{delta} virus yuqdi. Hozir {new_total} 🦠"
        else:
            text = (f"{name}, sizga {delta} virus yuqdi. "
                    f"Hozir {new_total} 🦠 Omad keyingi safar!")
        await message.reply(text)
    except Exception as e:
        logging.exception(e)
        await message.reply("Xatolik yuz berdi.")

# ==========================================================
# /top
# ==========================================================
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

@router.message(Command("top"))
async def cmd_top(message):
    try:
        rows = db_top(message.chat.id, 10)
        if not rows:
            await message.answer("Hozircha hech kim virus yig'magan 🦠")
            return
        lines = ["🏆 TOP 10 — Virusgram", ""]
        for i, (n, v) in enumerate(rows, start=1):
            lines.append(f"{MEDALS.get(i, f'{i}.')} {n} — {v} 🦠")
        await message.answer("\n".join(lines))
    except Exception as e:
        logging.exception(e)

# ==========================================================
# /profile
# ==========================================================
@router.message(Command("profile"))
async def cmd_profile(message):
    try:
        if not message.from_user:
            return
        uid, cid = message.from_user.id, message.chat.id
        name = message.from_user.first_name or "Do'stim"
        db_ensure_user(uid, cid, name)
        u = db_get_user(uid, cid)
        rank = db_rank(cid, u["viruses"])
        last = u["last_virus"] or 0
        rem = max(0, COOLDOWN - (time.time() - last)) if last else 0
        if COOLDOWN == 0 or rem <= 0:
            cd = "Tayyor! /virus yuborishingiz mumkin ✅"
        else:
            h, m = int(rem // 3600), int((rem % 3600) // 60)
            if rem % 60 > 0:
                m += 1
            cd = f"Yana {h} soat {m} daqiqa ⏳" if h > 0 else f"Yana {m} daqiqa ⏳"
        ban = " 🚫 BANLANGAN" if u.get("banned") else ""
        text = (f"👤 {name} profili{ban}\n\n"
                f"🦠 Jami virus: {u['viruses']}\n"
                f"🏅 O'rni: #{rank}\n"
                f"⏰ Keyingi /virus: {cd}")
        await message.answer(text + FOOTER)
    except Exception as e:
        logging.exception(e)

# ==========================================================
# /pic
# ==========================================================
@router.message(Command("pic"))
async def cmd_pic(message):
    try:
        if not message.from_user:
            return
        uid, cid = message.from_user.id, message.chat.id
        name = message.from_user.first_name or "Do'stim"
        db_ensure_user(uid, cid, name)
        u = db_get_user(uid, cid)
        path = create_virus_image(name, u["viruses"], uid, cid)
        await message.reply_photo(
            FSInputFile(path),
            caption=f"🦠 {name} — {u['viruses']} virus" + FOOTER
        )
        try:
            os.remove(path)
        except Exception:
            pass
    except Exception as e:
        logging.exception(e)
        await message.reply("Rasm chizishda xatolik.")

# ==========================================================
# /shop
# ==========================================================
SHOP_ITEMS = {
    "v10": {"stars": 20,  "viruses": 10, "label": "10 🦠"},
    "v30": {"stars": 50,  "viruses": 30, "label": "30 🦠"},
    "v70": {"stars": 100, "viruses": 70, "label": "70 🦠"},
}

def _shop_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10 🦠 — 20 ⭐", callback_data="buy:v10")],
        [InlineKeyboardButton(text="30 🦠 — 50 ⭐", callback_data="buy:v30")],
        [InlineKeyboardButton(text="70 🦠 — 100 ⭐", callback_data="buy:v70")],
    ])

@router.message(Command("shop"))
async def cmd_shop(message):
    await message.answer(
        "🛒 Virus Do'koni\n\n"
        "• 10 🦠 — 20 ⭐\n"
        "• 30 🦠 — 50 ⭐\n"
        "• 70 🦠 — 100 ⭐\n\n"
        "Kerakli paketni tanlang:",
        reply_markup=_shop_kb()
    )

@router.callback_query(F.data == "open_shop")
async def cb_open_shop(callback: CallbackQuery):
    await callback.message.answer(
        "🛒 Virus Do'koni\n\n"
        "• 10 🦠 — 20 ⭐\n"
        "• 30 🦠 — 50 ⭐\n"
        "• 70 🦠 — 100 ⭐\n\n"
        "Kerakli paketni tanlang:",
        reply_markup=_shop_kb()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery, bot: Bot):
    try:
        key = callback.data.split(":", 1)[1]
        item = SHOP_ITEMS.get(key)
        if not item:
            await callback.answer("Noma'lum paket", show_alert=True)
            return
        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=f"{item['viruses']} virus paketi",
            description=(f"Virusgram Bot — {item['viruses']} ta virus\n\n"
                         f"Made by Gubo Studios"),
            payload=f"shop:{key}:{callback.from_user.id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=item["label"], amount=item["stars"])],
        )
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Xatolik", show_alert=True)

@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    try:
        await q.answer(ok=True)
    except Exception as e:
        logging.exception(e)
        await q.answer(ok=False, error_message="Xatolik")

@router.message(F.successful_payment)
async def pay_ok(message: Message, bot: Bot):
    try:
        parts = (message.successful_payment.invoice_payload or "").split(":")
        if len(parts) < 3:
            return
        item = SHOP_ITEMS.get(parts[1])
        if not item:
            return
        uid, cid = int(parts[2]), message.chat.id
        name = message.from_user.first_name if message.from_user else "Do'stim"
        db_ensure_user(uid, cid, name)
        db_add_viruses(uid, cid, item["viruses"])
        u = db_get_user(uid, cid)
        await message.answer(
            f"✅ To'lov muvaffaqiyatli!\n\n"
            f"➕ {item['viruses']} virus qo'shildi.\n"
            f"🦠 Jami: {u['viruses']}"
        )
    except Exception as e:
        logging.exception(e)

# ==========================================================
# Yangi a'zo
# ==========================================================
@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_join(event: ChatMemberUpdated, bot: Bot):
    try:
        name = event.new_chat_member.user.first_name or "Do'stim"
        await bot.send_message(
            event.chat.id,
            f"👋 Xush kelibsiz, {name}!\n\n"
            "Bu guruhda virus yig'ib do'stlaringizni ortda qoldiring.\n\n"
            "/virus — virus yuqtirish\n"
            "/top   — guruh reytingi\n"
            "/pic   — virus kartangiz\n"
            "/shop  — virus sotib olish"
        )
    except Exception as e:
        logging.exception(e)

# ==========================================================
# ADMIN PANEL
# ==========================================================
class AdminState(StatesGroup):
    add_uid = State(); add_amt = State()
    rem_uid = State(); rem_amt = State()
    reset_uid = State()
    ban_uid = State(); unban_uid = State()
    bcast = State()

def is_admin(uid):
    return uid == ADMIN_ID

def _admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="adm:stats")],
        [InlineKeyboardButton(text="➕ Ball qo'shish", callback_data="adm:add"),
         InlineKeyboardButton(text="➖ Ball ayirish", callback_data="adm:rem")],
        [InlineKeyboardButton(text="🔄 Reset", callback_data="adm:reset"),
         InlineKeyboardButton(text="🚫 Ban", callback_data="adm:ban")],
        [InlineKeyboardButton(text="✅ Unban", callback_data="adm:unban")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="adm:bcast")],
    ])

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ Ruxsat yo'q")
        return
    await message.answer("🛠 <b>Admin panel</b>\n\nAmalni tanlang:",
                         reply_markup=_admin_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("adm:"))
async def adm_cb(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    act = cb.data.split(":")[1]

    if act == "stats":
        tu, tc, tv, tb = db_admin_stats()
        await cb.message.edit_text(
            f"📊 <b>Statistika</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{tu}</b>\n"
            f"💬 Guruhlar: <b>{tc}</b>\n"
            f"🦠 Jami viruslar: <b>{tv}</b>\n"
            f"🚫 Banlanganlar: <b>{tb}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:back")]
            ]))
    elif act in ("add", "rem", "reset", "ban", "unban", "bcast"):
        prompts = {
            "add":   ("➕ Ball qo'shish\n\nFoydalanuvchi ID raqamini yuboring:",
                      AdminState.add_uid),
            "rem":   ("➖ Ball ayirish\n\nFoydalanuvchi ID raqamini yuboring:",
                      AdminState.rem_uid),
            "reset": ("🔄 Reset\n\nFoydalanuvchi ID raqamini yuboring:",
                      AdminState.reset_uid),
            "ban":   ("🚫 Ban\n\nFoydalanuvchi ID raqamini yuboring:",
                      AdminState.ban_uid),
            "unban": ("✅ Unban\n\nFoydalanuvchi ID raqamini yuboring:",
                      AdminState.unban_uid),
            "bcast": ("📢 Broadcast\n\nYubormoqchi bo'lgan xabaringizni yozing:",
                      AdminState.bcast),
        }
        text, st = prompts[act]
        await state.set_state(st)
        await cb.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Bekor", callback_data="adm:back")]
            ]))
    elif act == "back":
        await state.clear()
        await cb.message.edit_text("🛠 <b>Admin panel</b>\n\nAmalni tanlang:",
                                   reply_markup=_admin_kb(),
                                   parse_mode="HTML")
    await cb.answer()

def _parse_uid(text):
    try:
        return int(text.strip())
    except Exception:
        return None

@router.message(AdminState.add_uid)
async def adm_add_uid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    uid = _parse_uid(message.text)
    if not uid:
        await message.answer("❌ ID raqam bo'lishi kerak")
        return
    await state.update_data(uid=uid)
    await state.set_state(AdminState.add_amt)
    await message.answer(f"➕ ID {uid} uchun nechta ball qo'shamiz? (1-10000)")

@router.message(AdminState.add_amt)
async def adm_add_amt(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amt = int(message.text.strip())
        if not (1 <= amt <= 10000):
            await message.answer("❌ 1 dan 10000 gacha kiriting")
            return
    except Exception:
        await message.answer("❌ Raqam kiriting")
        return
    data = await state.get_data()
    db_admin_set_balance(data["uid"], amt)
    await state.clear()
    await message.answer(
        f"✅ ID {data['uid']} ga +{amt} ball qo'shildi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]
        ]))

@router.message(AdminState.rem_uid)
async def adm_rem_uid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    uid = _parse_uid(message.text)
    if not uid:
        await message.answer("❌ ID raqam")
        return
    await state.update_data(uid=uid)
    await state.set_state(AdminState.rem_amt)
    await message.answer(f"➖ ID {uid} dan nechta ball ayiramiz? (1-10000)")

@router.message(AdminState.rem_amt)
async def adm_rem_amt(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amt = int(message.text.strip())
        if not (1 <= amt <= 10000):
            await message.answer("❌ 1 dan 10000 gacha")
            return
    except Exception:
        await message.answer("❌ Raqam kiriting")
        return
    data = await state.get_data()
    db_admin_set_balance(data["uid"], -amt)
    await state.clear()
    await message.answer(
        f"✅ ID {data['uid']} dan -{amt} ball ayirildi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]
        ]))

@router.message(AdminState.reset_uid)
async def adm_reset_uid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    uid = _parse_uid(message.text)
    if not uid:
        await message.answer("❌ ID raqam")
        return
    db_admin_reset(uid)
    await state.clear()
    await message.answer(
        f"🔄 ID {uid} reset qilindi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]
        ]))

@router.message(AdminState.ban_uid)
async def adm_ban_uid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    uid = _parse_uid(message.text)
    if not uid:
        await message.answer("❌ ID raqam")
        return
    db_admin_ban(uid, 1)
    await state.clear()
    await message.answer(
        f"🚫 ID {uid} banlandi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]
        ]))

@router.message(AdminState.unban_uid)
async def adm_unban_uid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    uid = _parse_uid(message.text)
    if not uid:
        await message.answer("❌ ID raqam")
        return
    db_admin_ban(uid, 0)
    await state.clear()
    await message.answer(
        f"✅ ID {uid} unban qilindi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]
        ]))

@router.message(AdminState.bcast)
async def adm_bcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Xabar bo'sh")
        return
    await state.clear()
    ids = db_all_user_ids()
    sent, fail = 0, 0
    for uid in ids:
        try:
            await message.bot.send_message(
                uid, f"📢 <b>Xabar</b>\n\n{text}", parse_mode="HTML"
            )
            sent += 1
        except Exception:
            fail += 1
    await message.answer(
        f"📢 Yuborildi: {sent}\n❌ Muvaffaqiyatsiz: {fail}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]
        ]))

# ==========================================================
# MENYU VA ISHGA TUSHIRISH
# ==========================================================
async def setup_commands(bot: Bot):
    private_commands = [
        BotCommand(command="start",   description="🚀 Boshlash"),
        BotCommand(command="help",    description="📖 Yordam"),
        BotCommand(command="virus",   description="🦠 Virus yuqtirish"),
        BotCommand(command="top",     description="🏆 TOP 10"),
        BotCommand(command="pic",     description="🖼️ Virus kartangiz"),
        BotCommand(command="profile", description="👤 Profil"),
        BotCommand(command="shop",    description="🛒 Virus do'koni"),
    ]
    group_commands = [
        BotCommand(command="virus",   description="🦠 Virus yuqtirish"),
        BotCommand(command="top",     description="🏆 TOP 10"),
        BotCommand(command="pic",     description="🖼️ Virus kartangiz"),
        BotCommand(command="profile", description="👤 Profil"),
        BotCommand(command="shop",    description="🛒 Virus do'koni"),
    ]
    try:
        await bot.set_my_commands(private_commands,
                                  scope=BotCommandScopeDefault())
        await bot.set_my_commands(group_commands,
                                  scope=BotCommandScopeAllGroupChats())
        logging.info("✅ Buyruqlar menyusi o'rnatildi")
    except Exception as e:
        logging.warning(f"Menyu o'rnatishda xatolik: {e}")

# Global references (webhook uchun kerak)
bot = None
dp = None

async def handle_webhook(request):
    """Telegram'dan kelgan so'rovni qabul qilish."""
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.exception(e)
    return web.Response(text="OK")

async def handle_health(request):
    """Render health check uchun."""
    return web.Response(text="OK")

async def main():
    global bot, dp
    db_init()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    logging.info("Virusgram Bot ishga tushdi ✅")

    PORT = int(os.getenv("PORT", 10000))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

    if WEBHOOK_URL:
        # ===== WEBHOOK REJIMI (Render uchun) =====
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logging.warning(f"Webhook o'chirishda xatolik: {e}")

        await setup_commands(bot)

        full_url = f"{WEBHOOK_URL}/webhook"
        await bot.set_webhook(url=full_url, drop_pending_updates=True)
        logging.info(f"✅ Webhook o'rnatildi: {full_url}")

        app = web.Application()
        app.router.add_post("/webhook", handle_webhook)
        app.router.add_get("/", handle_health)
        app.router.add_get("/health", handle_health)

        logging.info(f"🚀 Server 0.0.0.0:{PORT} da ishga tushdi")
        await web._run_app(app, host="0.0.0.0", port=PORT)
    else:
        # ===== POLLING REJIMI (mahalliy test) =====
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logging.warning(f"Webhook: {e}")
        await setup_commands(bot)
        logging.info("🔄 Polling rejimida ishga tushdi")
        await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi.")
