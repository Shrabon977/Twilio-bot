#!/usr/bin/env python3
"""
Super‑fast Twilio ⇆ Telegram bot (Bengali)
-----------------------------------------
✓ <1 s reply (threaded)
✓ ইউজার শুধু +1xxxxxxxxxx পেস্ট করলেই অটো‑BUY
✓ Unavailable হলে: ❌ … is not available
✓ Auto‑receive OTP (View SMS বাটন রেখেই)
✓ Termux + nohup উপযোগী
"""

import re, random, threading
from datetime import datetime, timedelta

import telebot
from telebot import types
from twilio.rest import Client

# ────────────────────────────
# 🔐  Tokens (hard‑coded)
BOT_TOKEN = "7630288391:AAFNCjLfeihTwIjd6aFghMhI92mzvB0HoMY"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ────────────────────────────
user_session: dict[int, dict] = {}
CANADA_AREA_CODES = [
    "204","236","249","250","289","306","343","365","387","403","416","418","431",
    "437","438","450","506","514","519","548","579","581","587","604","613","639",
    "647","672","705","709","742","778","780","782","807","819","825","867","873",
    "902","905",
]

# ────────────────────────────
def extract_otp(text: str) -> str:
    m = re.search(r"\b(\d{3}-\d{3}|\d{6})\b", text)
    return m.group(1) if m else "N/A"

# (ঐচ্ছিক) গ্রুপে ফরওয়ার্ড
GROUP_ID = -1002850295679
def forward_to_group(html: str):
    try: bot.send_message(GROUP_ID, html)
    except Exception as e: print("[WARN] group forward:", e)

# Utility
def run_async(fn):
    def wrap(*a, **k): threading.Thread(target=fn, args=a, kwargs=k, daemon=True).start()
    return wrap
def logged(uid): return uid in user_session and "twilio_client" in user_session[uid]

# ─── SMS listener helpers ──
def _stop_sms_listener(sess: dict):
    ev = sess.get("sms_stop_evt")
    if ev: ev.set()
    for k in ("sms_thread","sms_stop_evt","last_msg_sid"): sess.pop(k, None)

def _start_sms_listener(uid: int, chat_id: int):
    sess = user_session[uid]; _stop_sms_listener(sess)
    stop_evt = threading.Event(); sess["sms_stop_evt"] = stop_evt; sess["last_msg_sid"] = None

    def poll():
        client: Client = sess["twilio_client"]; num = sess["purchased_number"]
        while not stop_evt.is_set():
            try:
                msgs = client.messages.list(to=num, limit=1)
                if msgs and sess.get("last_msg_sid") != msgs[0].sid:
                    sess["last_msg_sid"] = msgs[0].sid
                    _send_formatted_sms(chat_id, msgs[0], num)
            except Exception as e: print("[SMS‑poll]", e)
            stop_evt.wait(5)

    threading.Thread(target=poll, daemon=True).start()

# ─── Commands ──
@bot.message_handler(commands=["start"])
def start(m):
    bot.reply_to(
        m,
        "🧾 Twilio SID ও Token এইভাবে পাঠান:\nACxxxx tokenxxxx\n\n"
        "🔐 উদাহরণ:\nAC123… token123…"
    )

@bot.message_handler(commands=["login"])
def login_cmd(m): bot.reply_to(m, "🔐 SID এবং Token পাঠান:\nACxxx tokenxxx")

@bot.message_handler(commands=["logout"])
@run_async
def logout(m):
    uid=m.from_user.id
    if not logged(uid): bot.reply_to(m,"❗️ আপনি এখনও লগইন করেননি।"); return
    sess=user_session[uid]; client:Client=sess["twilio_client"]; old=sess.get("purchased_number")
    _stop_sms_listener(sess)
    try:
        if old:
            for n in client.incoming_phone_numbers.list():
                if n.phone_number==old: client.incoming_phone_numbers(n.sid).delete(); break
    except: pass
    user_session.pop(uid,None)
    bot.send_message(m.chat.id,"✅ সফলভাবে লগআউট হয়েছে।")

@bot.message_handler(commands=["buy"])
def buy(m):
    if not logged(m.from_user.id): bot.reply_to(m,"🔐 আগে /login করুন।"); return
    bot.send_message(m.chat.id,"📟 ৩ সংখ্যার এরিয়া কোড দিন (যেমন 825):")

@bot.message_handler(commands=["random"])
def random_ac(m):
    if not logged(m.from_user.id): bot.reply_to(m,"🔐 আগে /login করুন।"); return
    ac=random.choice(CANADA_AREA_CODES)
    bot.send_message(m.chat.id,f"🎲 র‍্যান্ডম এরিয়া কোড: {ac}")
    _send_area_code_numbers(m.from_user.id,m.chat.id,ac)

@bot.message_handler(commands=["returnsms"])
@run_async
def returnsms(m):
    uid=m.from_user.id
    if not logged(uid): bot.reply_to(m,"🔐 আগে /login করুন।"); return
    sess=user_session[uid]; client:Client=sess["twilio_client"]; num=sess.get("purchased_number")
    if not num: bot.reply_to(m,"❗️ আপনি এখনো কোনো নাম্বার কিনেননি।"); return
    since=datetime.utcnow()-timedelta(hours=1)
    try:
        msgs=client.messages.list(to=num,date_sent_after=since); 
        _send_formatted_sms(m.chat.id,msgs[0],num) if msgs else bot.send_message(m.chat.id,"📭 কোনো মেসেজ নেই।")
    except: bot.send_message(m.chat.id,"⚠️ মেসেজ আনতে সমস্যা।")

# ─── Login catcher ──
cred_re=re.compile(r"^(AC[a-zA-Z0-9]{32})\s+([a-zA-Z0-9]{32,})$")
@bot.message_handler(func=lambda m: cred_re.match(m.text or ""))
@run_async
def handle_login(m):
    try:
        sid,token=m.text.strip().split(); c=Client(sid,token); c.api.accounts(sid).fetch()
        user_session[m.from_user.id]={"twilio_client":c,"sid":sid,"token":token,"purchased_number":None}
        bot.send_message(m.chat.id,"✅ লগইন সফল। এখন এরিয়া কোড দিন বা /buy ব্যবহার করুন।")
    except: bot.send_message(m.chat.id,"❌ লগইন ব্যর্থ। SID বা Token ভুল।")

# ─── Area code ──
@bot.message_handler(func=lambda m: re.fullmatch(r"\d{3}",m.text or ""))
def handle_ac(m):
    if not logged(m.from_user.id): bot.reply_to(m,"🔐 আগে /login করুন।"); return
    _send_area_code_numbers(m.from_user.id,m.chat.id,m.text.strip())

# ─── AUTO‑BUY on pasted number ──
@bot.message_handler(func=lambda m: re.fullmatch(r"\+1\d{10}",m.text or ""))
@run_async
def auto_buy(m):
    if not logged(m.from_user.id): bot.reply_to(m,"🔐 আগে /login করুন।"); return
    uid,chat,num=m.from_user.id,m.chat.id,m.text.strip()
    sess=user_session[uid]; client:Client=sess["twilio_client"]

    _stop_sms_listener(sess)               # purge old listener
    old=sess.get("purchased_number")       # delete previous number
    try:
        if old:
            for n in client.incoming_phone_numbers.list():
                if n.phone_number==old: client.incoming_phone_numbers(n.sid).delete(); break
    except: pass

    try:
        client.incoming_phone_numbers.create(phone_number=num)
        sess["purchased_number"]=num; _start_sms_listener(uid,chat)
        kb=types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton("📥 View SMS",callback_data="viewsms"))
        bot.send_message(chat,f"✅ আপনি সাফল্যের সাথে নাম্বার কিনেছেন: {num}",reply_markup=kb)
    except Exception as e:
        txt=str(e).lower()
        if "not available" in txt: bot.send_message(chat,f"❌ নাম্বার কেনা যায়নি: {num} is not available")
        else: bot.send_message(chat,f"❌ নাম্বার কেনা যায়নি।\n{e}")

# ─── View SMS ──
@bot.callback_query_handler(func=lambda c:c.data=="viewsms")
@run_async
def view_sms(call):
    if not logged(call.from_user.id): bot.answer_callback_query(call.id,"❌ লগইন নেই।"); return
    sess=user_session[call.from_user.id]; client:Client=sess["twilio_client"]; num=sess.get("purchased_number")
    try:
        msgs=client.messages.list(to=num,limit=1)
        _send_formatted_sms(call.message.chat.id,msgs[0],num) if msgs else bot.send_message(call.message.chat.id,"📭 কোনো মেসেজ নেই।")
    except: bot.send_message(call.message.chat.id,"⚠️ মেসেজ আনতে সমস্যা।")

# ─── Helpers ──
@run_async
def _send_area_code_numbers(uid:int,chat:int,ac:str):
    sess=user_session[uid]; client:Client=sess["twilio_client"]
    try:
        nums=client.available_phone_numbers("CA").local.list(area_code=ac,limit=30)
        if not nums: bot.send_message(chat,f"❗️ এরিয়া কোড {ac}-এ কোনো নাম্বার নেই।"); return
        bot.send_message(chat,f"📞 ৩০টি নাম্বার ({ac}):")
        for n in nums: bot.send_message(chat,n.phone_number)
        bot.send_message(chat,"✅ পছন্দসই নাম্বারটি কপি করে পাঠান।")
    except Exception as e: bot.send_message(chat,f"⚠️ এরিয়া কোড নাম্বার আনতে সমস্যা।\n{e}")

def _send_formatted_sms(chat:int,msg,number:str):
    otp=extract_otp(msg.body)
    html=(f"🕰️ Time: {msg.date_sent}\n📞 Number: {number}\n🌍 Country: 🇨🇦 Canada\n"
          f"🔑 OTP: <code>{otp}</code>\n📬 Full massage:\n<blockquote>{msg.body}</blockquote>\n\n"
          "👑 BOT OWNER: SHRABON AHMED")
    bot.send_message(chat,html); forward_to_group(html)

# ─── Fallback ──
@bot.message_handler(func=lambda *_:True)
def fallback(m):
    bot.reply_to(m,"⚠️ দুঃখিত, আমি বুঝতে পারিনি। Twilio SID/Token, এরিয়া কোড, বা নাম্বার দিন। 😊")

# ─── Launch ──
print("🤖 Bot running…")
if __name__=="__main__":
    bot.infinity_polling(none_stop=True,timeout=0,skip_pending=True)
