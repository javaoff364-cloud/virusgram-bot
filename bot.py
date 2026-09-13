# -*- coding: utf-8 -*-
"""Virusgram Bot — aiogram 3.x + SQLite. Made by Gubo Studios"""
import os, time, random, logging, sqlite3
from dotenv import load_dotenv
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.filters import Command, CommandStart
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.enums import ChatType
from aiogram.types import (
    Message, CallbackQuery, PreCheckoutQuery, ChatMemberUpdated,
    InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice,
    FSInputFile, BotCommand, BotCommandScopeDefault,
    BotCommandScopeAllGroupChats, Update, TelegramObject
)
from aiogram.utils.deep_linking import create_startgroup_link
from PIL import Image, ImageDraw, ImageFont

# ==================== SOZLAMALAR ====================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID  = int(os.getenv("ADMIN_ID", "0"))
DB_PATH   = os.getenv("DB_PATH", "virusgram.db")
COOLDOWN  = int(os.getenv("COOLDOWN", "0"))
FOOTER    = "\n\nMade by Gubo Studios"
BASE_DIR  = os.getenv("BASE_DIR", "/root/bot")

if not BOT_TOKEN: raise SystemExit("BOT_TOKEN topilmadi")
if not ADMIN_ID: raise SystemExit("ADMIN_ID topilmadi")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
router = Router()

# ==================== ADMIN TEKSHIRUVI (MIDDLEWARE) ====================
_admin_cache = {}

class AdminRequiredMiddleware(BaseMiddleware):
    """Guruhda bot admin bo'lmasa — buyruqlar ishlamaydi."""
    async def __call__(self, handler, event: TelegramObject, data: dict):
        try:
            # Faqat Message va CallbackQuery
            if not isinstance(event, (Message, CallbackQuery)):
                return await handler(event, data)

            message = event if isinstance(event, Message) else event.message
            if not message:
                return await handler(event, data)

            # Shaxsiy chatda tekshiruv yo'q
            if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
                return await handler(event, data)

            bot = data.get("bot")
            if not bot:
                return await handler(event, data)

            cid = message.chat.id
            now = time.time()

            # 30 sekund kesh
            cached = _admin_cache.get(cid)
            if cached and (now - cached[1]) < 30:
                is_adm = cached[0]
            else:
                me = await bot.get_me()
                member = await bot.get_chat_member(chat_id=cid, user_id=me.id)
                status = str(member.status).lower()
                is_adm = status in ("administrator", "creator")
                _admin_cache[cid] = (is_adm, now)
                logging.info(f"[ADMIN CHECK] chat={cid} status={status} admin={is_adm}")

            if not is_adm:
                text = ("⚠️ <b>Bot admin emas!</b>\n\n"
                        "Barcha buyruqlar ishlashi uchun meni guruhga admin qiling:\n\n"
                        "1️⃣ Guruh nomini bosing → <b>Manage Group</b>\n"
                        "2️⃣ <b>Administrators</b> → <b>Add Admin</b>\n"
                        "3️⃣ <b>Virusgram</b> botni tanlang\n"
                        "4️⃣ <b>Save</b> bosing\n\n"
                        "Shundan keyin barcha buyruqlar ishlaydi ✅")
                try:
                    if isinstance(event, CallbackQuery):
                        await event.answer("Bot admin emas!", show_alert=True)
                    else:
                        await message.reply(text, parse_mode="HTML")
                except Exception:
                    pass
                return

            return await handler(event, data)
        except Exception as e:
            logging.exception(f"Middleware xatosi: {e}")
            return await handler(event, data)

# ==================== SQLITE ====================
def db_conn(): return sqlite3.connect(DB_PATH)

def db_init():
    with db_conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, first_name TEXT, viruses INTEGER DEFAULT 0, last_virus REAL DEFAULT 0, banned INTEGER DEFAULT 0, PRIMARY KEY (user_id, chat_id))")
        try: c.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
        except: pass
        c.commit()

def db_ensure_user(uid, cid, name):
    with db_conn() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id,chat_id,first_name,viruses,last_virus,banned) VALUES (?,?,?,0,0,0)", (uid,cid,name))
        c.execute("UPDATE users SET first_name=? WHERE user_id=? AND chat_id=?", (name,uid,cid))
        c.commit()

def db_get_user(uid, cid):
    with db_conn() as c:
        r = c.execute("SELECT user_id,chat_id,first_name,viruses,last_virus,banned FROM users WHERE user_id=? AND chat_id=?", (uid,cid)).fetchone()
    if not r: return None
    return {"user_id":r[0],"chat_id":r[1],"first_name":r[2],"viruses":r[3],"last_virus":r[4],"banned":r[5]}

def db_update_virus(uid, cid, total, ts):
    with db_conn() as c:
        c.execute("UPDATE users SET viruses=?, last_virus=? WHERE user_id=? AND chat_id=?", (total,ts,uid,cid))
        c.commit()

def db_add_viruses(uid, cid, amt):
    with db_conn() as c:
        c.execute("UPDATE users SET viruses=MAX(0,viruses+?) WHERE user_id=? AND chat_id=?", (amt,uid,cid))
        c.commit()

def db_top(cid, limit=10):
    with db_conn() as c:
        return c.execute("SELECT first_name,viruses FROM users WHERE chat_id=? ORDER BY viruses DESC,user_id ASC LIMIT ?", (cid,limit)).fetchall()

def db_rank(cid, v):
    with db_conn() as c:
        n = c.execute("SELECT COUNT(*) FROM users WHERE chat_id=? AND viruses>?", (cid,v)).fetchone()[0]
    return n+1

def db_admin_set(uid, amt):
    with db_conn() as c:
        c.execute("UPDATE users SET viruses=MAX(0,viruses+?) WHERE user_id=?", (amt,uid))
        c.commit()

def db_admin_reset(uid):
    with db_conn() as c:
        c.execute("UPDATE users SET viruses=0, last_virus=0 WHERE user_id=?", (uid,))
        c.commit()

def db_admin_ban(uid, b=1):
    with db_conn() as c:
        c.execute("UPDATE users SET banned=? WHERE user_id=?", (b,uid))
        c.commit()

def db_admin_stats():
    with db_conn() as c:
        tu=c.execute("SELECT COUNT(DISTINCT user_id) FROM users").fetchone()[0]
        tc=c.execute("SELECT COUNT(DISTINCT chat_id) FROM users").fetchone()[0]
        tv=c.execute("SELECT COALESCE(SUM(viruses),0) FROM users").fetchone()[0]
        tb=c.execute("SELECT COUNT(*) FROM users WHERE banned=1").fetchone()[0]
    return tu,tc,tv,tb

def db_all_ids():
    with db_conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT user_id FROM users").fetchall()]

# ==================== O'YIN MANTIQI ====================
def roll_virus(cur):
    """5+ virusda 15% ehtimolda -1..-10, aks holda +1..+20."""
    if cur >= 5 and random.random() < 0.15:
        return random.randint(-10, -1)
    return random.randint(1, 20)

# ==================== SHRIFT ====================
def _get_font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"):
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

# ==================== RASM CHIZISH ====================
_IMG_CACHE = {}

def _load_img(name, box):
    key = f"{name}_{box[0]}x{box[1]}"
    if key in _IMG_CACHE: return _IMG_CACHE[key]
    src = os.path.join(BASE_DIR, name)
    if not os.path.exists(src):
        _IMG_CACHE[key] = None; return None
    try: base = Image.open(src).convert("RGBA")
    except:
        _IMG_CACHE[key] = None; return None
    tw, th = box
    bw, bh = base.size
    sc = min(tw/bw, th/bh)
    nw, nh = max(1,int(bw*sc)), max(1,int(bh*sc))
    base = base.resize((nw,nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (tw,th), (0,0,0,0))
    canvas.paste(base, ((tw-nw)//2, (th-nh)//2), base)
    base = canvas
    px = base.load()
    pts = []
    for y in range(th):
        for x in range(tw):
            r,g,b,a = px[x,y]
            if a < 50: continue
            if r>240 and g>240 and b>240: continue
            pts.append((x,y))
    if not pts:
        _IMG_CACHE[key] = None; return None
    cx = sum(p[0] for p in pts)/len(pts)
    cy = sum(p[1] for p in pts)/len(pts)
    pts.sort(key=lambda p: (p[0]-cx)**2 + (p[1]-cy)**2)
    _IMG_CACHE[key] = (base, pts, (cx,cy))
    return base, pts, (cx,cy)

def _draw_fill(img, d, name, box, pct, fill, outline, W, H):
    x0,y0,x1,y1 = box
    bw, bh = x1-x0, y1-y0
    d.rounded_rectangle([x0-12,y0-12,x1+12,y1+12], radius=18, fill=(18,26,48), outline=(60,90,140), width=2)
    cached = _load_img(name, (bw,bh))
    if cached is None:
        d.rounded_rectangle([x0,y0,x1,y1], radius=10, fill=(42,52,72), outline=outline, width=2)
        if pct > 0:
            yf = y1 - (y1-y0)*pct/100
            d.rectangle([x0+3,yf,x1-3,y1-3], fill=fill)
        return
    base, pts, (cx,cy) = cached
    work = base.copy()
    px = work.load()
    total = len(pts)
    n = int(total*pct/100)
    for i in range(n):
        x,y = pts[i]; px[x,y] = fill
    rnd = random.Random(42+int(pct*10))
    start, end = max(0,n-100), min(total,n+30)
    dd = ImageDraw.Draw(work)
    for i in range(start,end):
        x,y = pts[i]
        if rnd.random() < 0.3:
            r = rnd.randint(1,2)
            dd.ellipse([x-r,y-r,x+r,y+r], fill=(220,255,230,230))
    if n > 20:
        for ring in (6,12,20):
            dd.ellipse([cx-ring,cy-ring,cx+ring,cy+ring], outline=(200,255,220,120), width=1)
    img.paste(work, (x0,y0), work)

def create_virus_image(name, v, uid, cid):
    W, H = 700, 520
    if v <= 100:
        title, img_name = "O'zbekiston xaritasi", "uzbekistan.png"
        cur, total = max(0,v), 100
        fill = (80,210,120,255)
    else:
        title, img_name = "Yer shari", "earth.png"
        cur, total = min(v,1000)-100, 900
        fill = (230,70,70,255)
    pct = max(0.0, min(100.0, cur*100.0/total))
    img = Image.new("RGB", (W,H), (12,18,34))
    d = ImageDraw.Draw(img)
    ft, fn, fs, fb, ftn = _get_font(30), _get_font(26), _get_font(20), _get_font(52), _get_font(14)
    d.text((30,20), title, font=ft, fill=(255,255,255))
    _draw_fill(img, d, img_name, (60,90,W-60,340), pct, fill, (130,170,220), W, H)
    pt = f"{pct:.0f}%"
    bb = d.textbbox((0,0), pt, font=fb)
    d.text((W//2-(bb[2]-bb[0])//2, 380), pt, font=fb, fill=(255,255,255))
    d.text((30,H-135), f"Ism: {name}", font=fn, fill=(255,255,255))
    d.text((30,H-95), f"Jami virus: {v}", font=fs, fill=(255,220,100))
    d.text((30,H-60), f"To'lgan: {pct:.1f}%", font=fs, fill=(150,220,255))
    d.text((W-230,H-30), "Made by Gubo Studios", font=ftn, fill=(160,160,160))
    out = os.path.join(BASE_DIR, f"virus_{cid}_{uid}.png")
    try: img.save(out)
    except: out = f"virus_{cid}_{uid}.png"; img.save(out)
    return out

# ==================== HANDLERLAR ====================
@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    name = message.from_user.first_name if message.from_user else "Do'stim"
    text = (f"Salom, <b>{name}</b>! 🦠\n\nVirusgram Bot — guruhda virus to'plash o'yini.\n\n"
            "📋 <b>QOIDALAR:</b>\n"
            "1. /virus — +1 dan +20 gacha virus\n"
            "2. 5+ virusda 15% ehtimolda -1 dan -10 gacha\n"
            "3. /top — eng virusli 10 kishi\n"
            "4. /pic — virus kartangiz (rasm)\n"
            "5. /shop — Stars orqali virus sotib olish\n"
            "6. /profile — shaxsiy statistika\n\nOmad! 🎯")
    try: gl = await create_startgroup_link(bot=bot)
    except:
        me = await bot.get_me()
        gl = f"https://t.me/{me.username}?startgroup=true"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Botni guruhga qo'shish", url=gl)],
        [InlineKeyboardButton(text="🛒 Virus do'koni", callback_data="open_shop")]])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.message(Command("help"))
async def cmd_help(message: Message):
    text = ("📖 <b>Komandalar:</b>\n\n/start — qoidalar\n/help — yordam\n"
            "/virus — virus yuqtirish\n/top — TOP 10\n/pic — virus kartangiz\n"
            "/profile — statistika\n/shop — virus sotib olish")
    if message.from_user and message.from_user.id == ADMIN_ID:
        text += "\n\n👑 <b>Admin:</b>\n/admin — admin panel"
    await message.answer(text, parse_mode="HTML")

@router.message(Command("virus"))
async def cmd_virus(message: Message):
    try:
        if not message.from_user: return
        uid, cid = message.from_user.id, message.chat.id
        name = message.from_user.first_name or "Do'stim"
        db_ensure_user(uid, cid, name)
        u = db_get_user(uid, cid)
        if u.get("banned"):
            await message.reply(f"{name}, siz banlangansiz 🚫"); return
        now, last = time.time(), u["last_virus"] or 0
        if COOLDOWN > 0 and last and (now-last) < COOLDOWN:
            rem = COOLDOWN - (now-last)
            h, m = int(rem//3600), int((rem%3600)//60)
            if rem % 60 > 0: m += 1
            await message.reply(f"{name}, yana {h} soat {m} daqiqa kuting" if h>0 else f"{name}, yana {m} daqiqa kuting")
            return
        delta = roll_virus(u["viruses"])
        new_total = max(0, u["viruses"] + delta)
        db_update_virus(uid, cid, new_total, now)
        if delta > 0:
            t = f"{name}, sizga +{delta} virus yuqdi. Hozir {new_total} 🦠"
        else:
            t = f"{name}, sizga {delta} virus yuqdi. Hozir {new_total} 🦠 Omad keyingi safar!"
        await message.reply(t)
    except Exception as e: logging.exception(e)

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

@router.message(Command("top"))
async def cmd_top(message: Message):
    try:
        rows = db_top(message.chat.id, 10)
        if not rows:
            await message.answer("Hozircha hech kim virus yig'magan 🦠"); return
        lines = ["🏆 <b>TOP 10 — Virusgram</b>", ""]
        for i, (n, v) in enumerate(rows, start=1):
            lines.append(f"{MEDALS.get(i, f'{i}.')} {n} — {v} 🦠")
        await message.answer("\n".join(lines), parse_mode="HTML")
    except Exception as e: logging.exception(e)

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    try:
        if not message.from_user: return
        uid, cid = message.from_user.id, message.chat.id
        name = message.from_user.first_name or "Do'stim"
        db_ensure_user(uid, cid, name)
        u = db_get_user(uid, cid)
        rank = db_rank(cid, u["viruses"])
        last = u["last_virus"] or 0
        rem = max(0, COOLDOWN - (time.time()-last)) if last else 0
        if COOLDOWN == 0 or rem <= 0:
            cd = "Tayyor! /virus yuborishingiz mumkin ✅"
        else:
            h, m = int(rem//3600), int((rem%3600)//60)
            if rem % 60 > 0: m += 1
            cd = f"Yana {h} soat {m} daqiqa ⏳" if h>0 else f"Yana {m} daqiqa ⏳"
        ban = " 🚫 BANLANGAN" if u.get("banned") else ""
        text = (f"👤 <b>{name}</b> profili{ban}\n\n"
                f"🦠 Jami virus: <b>{u['viruses']}</b>\n"
                f"🏅 O'rni: <b>#{rank}</b>\n"
                f"⏰ Keyingi /virus: {cd}")
        await message.answer(text + FOOTER, parse_mode="HTML")
    except Exception as e: logging.exception(e)

@router.message(Command("pic"))
async def cmd_pic(message: Message, bot: Bot):
    try:
        if not message.from_user: return
        uid, cid = message.from_user.id, message.chat.id
        name = message.from_user.first_name or "Do'stim"
        db_ensure_user(uid, cid, name)
        u = db_get_user(uid, cid)
        path = create_virus_image(name, u["viruses"], uid, cid)
        await message.reply_photo(FSInputFile(path), caption=f"🦠 {name} — {u['viruses']} virus" + FOOTER)
        try: os.remove(path)
        except: pass
    except Exception as e:
        logging.exception(e)
        await message.reply("Rasm chizishda xatolik.")

SHOP_ITEMS = {
    "v10": {"stars": 20,  "viruses": 10, "label": "10 🦠"},
    "v30": {"stars": 50,  "viruses": 30, "label": "30 🦠"},
    "v70": {"stars": 100, "viruses": 70, "label": "70 🦠"},
}

def _shop_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10 🦠 — 20 ⭐", callback_data="buy:v10")],
        [InlineKeyboardButton(text="30 🦠 — 50 ⭐", callback_data="buy:v30")],
        [InlineKeyboardButton(text="70 🦠 — 100 ⭐", callback_data="buy:v70")]])

@router.message(Command("shop"))
async def cmd_shop(message: Message):
    await message.answer("🛒 <b>Virus Do'koni</b>\n\n• 10 🦠 — 20 ⭐\n• 30 🦠 — 50 ⭐\n• 70 🦠 — 100 ⭐\n\nKerakli paketni tanlang:", reply_markup=_shop_kb(), parse_mode="HTML")

@router.callback_query(F.data == "open_shop")
async def cb_open_shop(cb: CallbackQuery):
    await cb.message.answer("🛒 <b>Virus Do'koni</b>\n\n• 10 🦠 — 20 ⭐\n• 30 🦠 — 50 ⭐\n• 70 🦠 — 100 ⭐\n\nKerakli paketni tanlang:", reply_markup=_shop_kb(), parse_mode="HTML")
    await cb.answer()

@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(cb: CallbackQuery, bot: Bot):
    try:
        item = SHOP_ITEMS.get(cb.data.split(":",1)[1])
        if not item:
            await cb.answer("Noma'lum", show_alert=True); return
        await bot.send_invoice(chat_id=cb.message.chat.id,
            title=f"{item['viruses']} virus paketi",
            description=f"{item['viruses']} ta virus\n\nMade by Gubo Studios",
            payload=f"shop:{cb.data.split(':')[1]}:{cb.from_user.id}",
            provider_token="", currency="XTR",
            prices=[LabeledPrice(label=item["label"], amount=item["stars"])])
        await cb.answer()
    except Exception as e:
        logging.exception(e)
        await cb.answer("Xatolik", show_alert=True)

@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    try: await q.answer(ok=True)
    except: await q.answer(ok=False, error_message="Xatolik")

@router.message(F.successful_payment)
async def pay_ok(message: Message, bot: Bot):
    try:
        parts = (message.successful_payment.invoice_payload or "").split(":")
        if len(parts) < 3: return
        item = SHOP_ITEMS.get(parts[1])
        if not item: return
        uid, cid = int(parts[2]), message.chat.id
        name = message.from_user.first_name if message.from_user else "Do'stim"
        db_ensure_user(uid, cid, name)
        db_add_viruses(uid, cid, item["viruses"])
        u = db_get_user(uid, cid)
        await message.answer(f"✅ <b>To'lov muvaffaqiyatli!</b>\n\n➕ {item['viruses']} virus qo'shildi.\n🦠 Jami: <b>{u['viruses']}</b>", parse_mode="HTML")
    except Exception as e: logging.exception(e)

@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_join(event: ChatMemberUpdated, bot: Bot):
    try:
        user = event.new_chat_member.user
        name = user.first_name or "Do'stim"
        me = await bot.get_me()
        if user.id == me.id:
            t = ("🦠 <b>Virusgram Bot guruhga qo'shildi!</b>\n\n"
                 "⚙️ <b>Botni admin qiling</b> — aks holda barcha buyruqlar ishlamaydi:\n\n"
                 "📋 <b>Qanday admin qilish:</b>\n"
                 "1️⃣ Guruh nomini bosing → <b>Manage Group</b>\n"
                 "2️⃣ <b>Administrators</b> → <b>Add Admin</b>\n"
                 "3️⃣ <b>Virusgram</b> botni tanlang\n"
                 "4️⃣ <b>Save</b> bosing\n\n"
                 "🎮 Keyin sinab ko'ring:\n/virus /top /pic /shop")
            await bot.send_message(event.chat.id, t, parse_mode="HTML")
        else:
            t = (f"👋 Xush kelibsiz, <b>{name}</b>!\n\n"
                 "Bu guruhda virus yig'ib do'stlaringizni ortda qoldiring.\n\n"
                 "🎮 <b>Komandalar:</b>\n"
                 "/virus — virus yuqtirish\n/top — reyting\n"
                 "/pic — karta\n/profile — statistika\n/shop — sotib olish")
            await bot.send_message(event.chat.id, t, parse_mode="HTML")
    except Exception as e: logging.exception(e)

# ==================== ADMIN PANEL ====================
class AdminState(StatesGroup):
    add_uid = State(); add_amt = State()
    rem_uid = State(); rem_amt = State()
    reset_uid = State()
    ban_uid = State(); unban_uid = State()
    bcast = State()

def is_admin(uid): return uid == ADMIN_ID

def _admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="adm:stats")],
        [InlineKeyboardButton(text="➕ Ball qo'shish", callback_data="adm:add"),
         InlineKeyboardButton(text="➖ Ball ayirish", callback_data="adm:rem")],
        [InlineKeyboardButton(text="🔄 Reset", callback_data="adm:reset"),
         InlineKeyboardButton(text="🚫 Ban", callback_data="adm:ban")],
        [InlineKeyboardButton(text="✅ Unban", callback_data="adm:unban")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="adm:bcast")]])

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ Ruxsat yo'q"); return
    await message.answer("🛠 <b>Admin panel</b>\n\nAmalni tanlang:", reply_markup=_admin_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("adm:"))
async def adm_cb(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True); return
    act = cb.data.split(":")[1]
    if act == "stats":
        tu,tc,tv,tb = db_admin_stats()
        await cb.message.edit_text(
            f"📊 <b>Statistika</b>\n\n👥 Foydalanuvchilar: <b>{tu}</b>\n💬 Guruhlar: <b>{tc}</b>\n🦠 Jami viruslar: <b>{tv}</b>\n🚫 Banlanganlar: <b>{tb}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:back")]]))
    elif act in ("add","rem","reset","ban","unban","bcast"):
        prompts = {
            "add": ("➕ Ball qo'shish\n\nFoydalanuvchi ID:", AdminState.add_uid),
            "rem": ("➖ Ball ayirish\n\nFoydalanuvchi ID:", AdminState.rem_uid),
            "reset": ("🔄 Reset\n\nFoydalanuvchi ID:", AdminState.reset_uid),
            "ban": ("🚫 Ban\n\nFoydalanuvchi ID:", AdminState.ban_uid),
            "unban": ("✅ Unban\n\nFoydalanuvchi ID:", AdminState.unban_uid),
            "bcast": ("📢 Broadcast\n\nXabarni yozing:", AdminState.bcast)}
        text, st = prompts[act]
        await state.set_state(st)
        await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor", callback_data="adm:back")]]))
    elif act == "back":
        await state.clear()
        await cb.message.edit_text("🛠 <b>Admin panel</b>\n\nAmalni tanlang:", reply_markup=_admin_kb(), parse_mode="HTML")
    await cb.answer()

def _pid(text):
    try: return int(text.strip())
    except: return None

@router.message(AdminState.add_uid)
async def adm_add_uid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    uid = _pid(message.text)
    if not uid: await message.answer("❌ ID raqam"); return
    await state.update_data(uid=uid)
    await state.set_state(AdminState.add_amt)
    await message.answer(f"➕ ID {uid} uchun nechta ball? (1-10000)")

@router.message(AdminState.add_amt)
async def adm_add_amt(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try:
        amt = int(message.text.strip())
        if not 1 <= amt <= 10000:
            await message.answer("❌ 1-10000"); return
    except: await message.answer("❌ Raqam"); return
    d = await state.get_data()
    db_admin_set(d["uid"], amt)
    await state.clear()
    await message.answer(f"✅ ID {d['uid']} ga +{amt} qo'shildi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]]))

@router.message(AdminState.rem_uid)
async def adm_rem_uid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    uid = _pid(message.text)
    if not uid: await message.answer("❌ ID raqam"); return
    await state.update_data(uid=uid)
    await state.set_state(AdminState.rem_amt)
    await message.answer(f"➖ ID {uid} dan nechta ayiramiz? (1-10000)")

@router.message(AdminState.rem_amt)
async def adm_rem_amt(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try:
        amt = int(message.text.strip())
        if not 1 <= amt <= 10000:
            await message.answer("❌ 1-10000"); return
    except: await message.answer("❌ Raqam"); return
    d = await state.get_data()
    db_admin_set(d["uid"], -amt)
    await state.clear()
    await message.answer(f"✅ ID {d['uid']} dan -{amt} ayirildi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]]))

@router.message(AdminState.reset_uid)
async def adm_reset_uid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    uid = _pid(message.text)
    if not uid: await message.answer("❌ ID raqam"); return
    db_admin_reset(uid)
    await state.clear()
    await message.answer(f"🔄 ID {uid} reset qilindi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]]))

@router.message(AdminState.ban_uid)
async def adm_ban_uid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    uid = _pid(message.text)
    if not uid: await message.answer("❌ ID raqam"); return
    db_admin_ban(uid, 1)
    await state.clear()
    await message.answer(f"🚫 ID {uid} banlandi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]]))

@router.message(AdminState.unban_uid)
async def adm_unban_uid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    uid = _pid(message.text)
    if not uid: await message.answer("❌ ID raqam"); return
    db_admin_ban(uid, 0)
    await state.clear()
    await message.answer(f"✅ ID {uid} unban qilindi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]]))

@router.message(AdminState.bcast)
async def adm_bcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    text = (message.text or "").strip()
    if not text: await message.answer("❌ Bo'sh"); return
    await state.clear()
    ids = db_all_ids()
    sent, fail = 0, 0
    for uid in ids:
        try:
            await message.bot.send_message(uid, f"📢 <b>Xabar</b>\n\n{text}", parse_mode="HTML")
            sent += 1
        except: fail += 1
    await message.answer(f"📢 Yuborildi: {sent}\n❌ Xato: {fail}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:back")]]))

# ==================== MENYU ====================
async def setup_commands(bot: Bot):
    priv = [
        BotCommand(command="start",   description="🚀 Boshlash"),
        BotCommand(command="help",    description="📖 Yordam"),
        BotCommand(command="virus",   description="🦠 Virus yuqtirish"),
        BotCommand(command="top",     description="🏆 TOP 10"),
        BotCommand(command="pic",     description="🖼️ Virus kartangiz"),
        BotCommand(command="profile", description="👤 Profil"),
        BotCommand(command="shop",    description="🛒 Virus do'koni"),
    ]
    grp = [
        BotCommand(command="virus",   description="🦠 Virus yuqtirish"),
        BotCommand(command="top",     description="🏆 TOP 10"),
        BotCommand(command="pic",     description="🖼️ Virus kartangiz"),
        BotCommand(command="profile", description="👤 Profil"),
        BotCommand(command="shop",    description="🛒 Virus do'koni"),
    ]
    try:
        await bot.set_my_commands(priv, scope=BotCommandScopeDefault())
        await bot.set_my_commands(grp, scope=BotCommandScopeAllGroupChats())
        logging.info("Buyruqlar menyusi o'rnatildi")
    except Exception as e:
        logging.warning(f"Menyu: {e}")

# ==================== WEBHOOK / POLLING ====================
bot = None
dp = None

async def handle_webhook(request):
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.exception(e)
    return web.Response(text="OK")

async def handle_health(request):
    return web.Response(text="OK")

async def main():
    global bot, dp
    db_init()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Admin middleware
    router.message.middleware(AdminRequiredMiddleware())
    router.callback_query.middleware(AdminRequiredMiddleware())
    logging.info("Admin tekshiruvi middleware o'rnatildi")

    logging.info("Virusgram Bot ishga tushdi")

    PORT = int(os.getenv("PORT", 10000))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

    if WEBHOOK_URL:
        try: await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e: logging.warning(f"Webhook: {e}")
        await setup_commands(bot)
        full_url = f"{WEBHOOK_URL}/webhook"
        await bot.set_webhook(url=full_url, drop_pending_updates=True)
        logging.info(f"Webhook: {full_url}")
        app = web.Application()
        app.router.add_post("/webhook", handle_webhook)
        app.router.add_get("/", handle_health)
        app.router.add_get("/health", handle_health)
        logging.info(f"Server 0.0.0.0:{PORT}")
        await web._run_app(app, host="0.0.0.0", port=PORT)
    else:
        try: await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e: logging.warning(f"Webhook: {e}")
        await setup_commands(bot)
        logging.info("Polling rejimi")
        await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): logging.info("Bot to'xtatildi.")
