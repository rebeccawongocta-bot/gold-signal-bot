# bot/bot.py — Octopus Smart TG Bot (Render 24/7 部署版)
# 版本: v2.7 | 2026-06-12 | 频道: @OctopusAITrader
# 功能：信号推送 + 市场开盘/休市提醒 + 每日欢迎消息（14:00-18:00 + 19:00-23:00 CST随机）+ 保活机制

import os
import sys
import time
import json
import random
import threading
import requests
from datetime import datetime, timezone, timedelta
import pytz

from flask import Flask, request

# ─── 配置区 ────────────────────────────────────────────────────────────────

BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "8702664592:AAE7QP3z9Tc9lHegOhOnXuWWpGDWGZKlY7I")
SIGNAL_CID = os.environ.get("SIGNAL_CID", "-1003899183014")

OCTOPUS_API     = "https://app.octopus-vision.com/prod-api/appHuginn/app-api/ai/quote-predict/latest"
OCTOPUS_HEADERS = {"Client-Type": "ANDROID", "Platform": "OCTOPUS"}

RENDER_URL = os.environ.get("RENDER_URL", "https://octatrade-tg-bot.onrender.com")

TZ = pytz.timezone("Asia/Shanghai")  # CST (UTC+8)

# ─── 市场开盘提醒配置 ─────────────────────────────────────────────────────────
# 格式: (本地小时, 本地分钟, [(地区名, emoji), ...], 时区, 星期几过滤)
#   星期几过滤: None=每天, [0]=仅周一, [4]=仅周五
MARKET_REMINDERS = [
    # 周一：整周开盘（Wellington + Sydney 合并）
    (6, 50, [("Wellington", "🇳🇿"), ("Sydney", "🇦🇺")], "Australia/Sydney",        [0]),
    # 亚洲主力时段
    (8, 50, [("Tokyo", "🇯🇵")],                              "Asia/Tokyo",              None),
    # 欧洲盘（London 主盘，温馨语提示 Frankfurt/Zurich/Paris 即将开市）
    (7, 50, [("London", "🇬🇧")],                              "Europe/London",            None),
    # 美盘（纽约本地 08:20 = 数据公布 CST 20:30 前 10 分钟）
    (8, 20, [("New York", "🇺🇸")],                        "US/Eastern",              None),
]

# ─── 温馨语轮播池 ──────────────────────────────────────────────────────────
# 每次开盘提醒随机选一条，避免视觉疲劳
TIPS = {
    "Wellington": [
        "Asia-Pacific session starting — watch for early volatility 🌏",
        "Sydney open — first liquidity of the week is flowing in 💧",
        "New week, new opportunities! 🚀",
    ],
    "Sydney": [
        "Asia-Pacific session starting — watch for early volatility 🌏",
        "Sydney open — first liquidity of the week is flowing in 💧",
        "New week, new opportunities! 🚀",
    ],
    "Tokyo": [
        "Tokyo session starting — Asian liquidity is rising 📈",
        "Asia session in progress — range-bound moves likely 📊",
        "Tokyo open — watch JPY pairs for action 🇯🇵",
        "Wish you a profitable session! 📈",
    ],
    "London": [
        "London open — European liquidity floodgate opens 🇬🇧",
        "UK session starting — expect stronger moves in EUR/GBP 📈",
        "Frankfurt 🇩🇪, Zurich 🇨🇭 & Paris 🇫🇷 opening soon.",
        "Wish you a profitable session! 📈",
    ],
    "New York": [
        "US session open — Wall Street is waking up 🇺🇸",
        "New York open — major data releases ahead, watch your risk! ⚠️",
        "US market open — high liquidity, tight spreads. Trade safe! 📊",
        "Non-farm payroll days: expect sharp moves. Set your stops! 🎯",
        "Wish you a profitable session! 📈",
    ],
}

# ─── 美国假期 2026（硬编码，每年更新一次）─────────────────────────────
# 格式: "MM-DD"
US_HOLIDAYS_2026 = {
    "01-01": "New Year's Day",
    "01-19": "Martin Luther King Jr. Day",
    "02-16": "Presidents' Day",
    "04-03": "Good Friday",
    "05-25": "Memorial Day",
    "06-19": "Juneteenth",
    "07-04": "Independence Day",
    "09-07": "Labor Day",
    "11-26": "Thanksgiving Day",
    "11-27": "Thanksgiving (obs)",
    "12-25": "Christmas Day",
    "12-24": "Christmas (obs)",
}

KEEP_ALIVE_INTERVAL = 300    # 5 分钟（保持 Render 唤醒）

# ─── 工具函数 ────────────────────────────────────────────────────────────────

def tg_api(method, payload=None, timeout=15):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        return resp.json()
    except Exception as e:
        print(f"[TG API] {method} 失败: {e}")
        return None


def fetch_octopus(symbol="XAUUSD"):
    try:
        url = f"{OCTOPUS_API}?systemCode={symbol}"
        resp = requests.get(url, headers=OCTOPUS_HEADERS, timeout=15)
        data = resp.json()
        if data.get("code") == 200 and data.get("data"):
            return data["data"]
        print(f"[Octopus] API 返回异常: {data}")
    except Exception as e:
        print(f"[Octopus] 获取 {symbol} 失败: {e}")
    return None


def build_signal_message(symbol="XAUUSD"):
    data = fetch_octopus(symbol)
    if not data:
        if symbol == "XAUUSD":
            print(f"[build_signal] {symbol} 无数据，尝试 BTCUSDT")
            return build_signal_message("BTCUSDT")
        return None
    try:
        direction    = data.get("direction", "NEUTRAL").upper()
        prob        = int(data.get("directionProbability", 0))
        support_p   = data.get("supportPrice", "N/A")
        resist_p    = data.get("resistancePrice", "N/A")
        target_p    = data.get("targetPrice", "N/A")
        change_r    = data.get("changeRate", "")
        period      = data.get("updatePeriod", "1H")
        name_raw    = data.get("name", "{}")
        try:
            name_obj = json.loads(name_raw)
            sym_name  = name_obj.get("en", symbol)
        except:
            sym_name  = symbol
        suggestion_raw = data.get("suggestion", "{}")
        try:
            sug     = json.loads(suggestion_raw) if isinstance(suggestion_raw, str) else suggestion_raw
            ai_text = sug.get("en", str(suggestion_raw))
        except:
            ai_text = str(suggestion_raw)
        if direction == "UP":
            emoji, arrow, dir_text = "🔵", "⬆️", "BUY"
        elif direction == "DOWN":
            emoji, arrow, dir_text = "🔴", "⬇️", "SELL"
        else:
            emoji, arrow, dir_text = "⚪", "➖", "HOLD"
        lines = [
            f"{emoji} {symbol} · {sym_name}",
            f"{arrow} {dir_text}  {prob}%  |  {period}  |  {change_r}",
            "",
            f"🎯 Target:  {target_p}",
            f"🛡 Support:  {support_p}",
            f"🚧 Resistance: {resist_p}",
            "",
            f"📊 AI: {ai_text}",
            "",
            "⚠️ Investing involves risk.",
            "🤝 BD: @rebecca_octopus",
        ]
        return "\n".join(lines)
    except Exception as e:
        print(f"[build_signal] 构造消息失败: {e}")
        return None


def send_signal_to_channel(symbol="XAUUSD"):
    msg = build_signal_message(symbol)
    if not msg:
        print(f"[{datetime.now(TZ).strftime('%H:%M')}] ⚠️ 无法获取任何信号数据，跳过推送")
        return False
    payload = {"chat_id": SIGNAL_CID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}
    result = tg_api("sendMessage", payload)
    now_str = datetime.now(TZ).strftime("%m-%d %H:%M")
    if result and result.get("ok"):
        print(f"[{now_str}] ✅ 信号推送成功")
        return True
    else:
        print(f"[{now_str}] ❌ 信号推送失败: {result}")
        return False


# ─── 线程 1：信号调度器 ────────────────────────────────────────────────────

def start_signal_scheduler():
    def should_push_now():
        now = datetime.now(TZ)
        return now.weekday() <= 4 or (now.weekday() > 4 and now.hour % 2 == 0)
    def get_symbol_for_time():
        return "XAUUSD" if datetime.now(TZ).weekday() <= 4 else "BTCUSDT"
    def loop():
        now = datetime.now(TZ)
        print(f"⏰ 信号调度器启动（{now.strftime('%Y-%m-%d %H:%M')} CST）")
        current_minute = now.minute
        if current_minute >= 5 and should_push_now():
            try:
                print(f"⏰ 启动时补发: {get_symbol_for_time()}")
                send_signal_to_channel(get_symbol_for_time())
            except Exception as e:
                print(f"⏰ 补发失败: {e}")
        while True:
            now = datetime.now(TZ)
            if now.weekday() <= 4:
                target = now.replace(minute=5, second=0, microsecond=0)
                if now.minute >= 5:
                    target += timedelta(hours=1)
                sleep_secs = (target - now).total_seconds()
                print(f"⏰ 下次推送: {target.strftime('%H:%M')} CST（{sleep_secs/60:.1f} 分钟后）— 工作日模式")
            else:
                next_even = now.replace(minute=5, second=0, microsecond=0)
                if next_even.hour % 2 != 0 or now.minute > 5:
                    if next_even.hour % 2 != 0:
                        next_even += timedelta(hours=1)
                    else:
                        next_even += timedelta(hours=2)
                while next_even.hour % 2 != 0:
                    next_even += timedelta(hours=1)
                if next_even <= now:
                    next_even += timedelta(hours=2)
                sleep_secs = (next_even - now).total_seconds()
                print(f"⏰ 下次推送: {next_even.strftime('%H:%M')} CST（{sleep_secs/60:.1f} 分钟后）— 周末模式")
                target = next_even
            time.sleep(sleep_secs)
            if should_push_now():
                try:
                    send_signal_to_channel(get_symbol_for_time())
                except Exception as e:
                    print(f"⏰ 定时信号推送异常: {e}")
            time.sleep(60)
    t = threading.Thread(target=loop, daemon=True, name="SignalScheduler")
    t.start()
    print("⏰ 信号调度器线程已启动（工作日每小时 / 周末每两小时）")


# ─── 线程 2：市场开盘 + 休市提醒 ─────────────────────────────────────────
# 功能：开盘温馨语轮播 + 欧洲城市联动 + 美国假期/经济数据提醒

def is_first_friday(dt_ny):
    """判断今天是否是本月第一个周五"""
    return dt_ny.weekday() == 4 and dt_ny.day <= 7

def is_us_holiday(dt_ny):
    """判断今天是否是美国假期"""
    key = dt_ny.strftime("%m-%d")
    return US_HOLIDAYS_2026.get(key)

def get_random_tip(region_name):
    """从温馨语池中随机选一条"""
    tips = TIPS.get(region_name)
    if tips:
        return random.choice(tips)
    return "Wish you a profitable session! 📈"

def start_market_reminder():
    """后台线程 — 市场开盘提醒 + 周五休市提醒"""
    def loop():
        last_sent = set()
        while True:
            now_utc = datetime.now(pytz.UTC)
            today_key = now_utc.strftime("%Y-%m-%d")
            if not any(k.startswith(today_key) for k in last_sent):
                last_sent.clear()

            # ── 开盘提醒 ─────────────────────────────────────────────────
            for local_h, local_m, regions, tz_str, days_filter in MARKET_REMINDERS:
                if days_filter is not None:
                    tz_chk = pytz.timezone(tz_str)
                    if datetime.now(tz_chk).weekday() not in days_filter:
                        continue

                tz = pytz.timezone(tz_str)
                now_local = datetime.now(tz)
                target_local = now_local.replace(hour=local_h, minute=local_m, second=0, microsecond=0)
                remind_after  = target_local - timedelta(minutes=10)
                remind_before = target_local - timedelta(seconds=1)

                if not (remind_after <= now_local <= remind_before):
                    continue

                send_key = f"{today_key}_open_{tz_str}_{local_h:02d}{local_m:02d}"
                if send_key in last_sent:
                    continue

                emojis   = "".join([e for _, e in regions])
                names    = " / ".join([n for n, _ in regions])
                # 用第一个地区的温馨语（随机轮播）
                primary   = regions[0][0]
                tip      = get_random_tip(primary)

                # ── 纽约时段额外检查：经济数据 / 假期 ─────────────
                data_note = ""
                if tz_str == "US/Eastern":
                    dt_ny = datetime.now(tz)
                    # 周四：初请失业金
                    if dt_ny.weekday() == 3:
                        data_note = "\n📋 <b>Initial Jobless Claims</b> in 10 min — US labor data ahead."
                    # 每月第一个周五：非农
                    if is_first_friday(dt_ny):
                        data_note = "\n📊 <b>Non-Farm Payroll (NFP)</b> in 10 min — expect high volatility!"
                    # 美国假期
                    holiday = is_us_holiday(dt_ny)
                    if holiday:
                        data_note += f"\n� holiday <b>{holiday}</b> today — US market liquidity may be lower."

                msg = (
                    f"{emojis} <b>{names}</b> market open in 10 min\n"
                    f"Get ready and watch for volatility.\n"
                    f"{tip}"
                    f"{data_note}"
                )
                result = tg_api("sendMessage", {
                    "chat_id": SIGNAL_CID,
                    "text": msg,
                    "parse_mode": "HTML",
                })
                if result and result.get("ok"):
                    print(f"🔔 开盘提醒已发送: {names} ({tz_str})")
                    last_sent.add(send_key)
                else:
                    print(f"🔔 开盘提醒发送失败: {names} — {result}")

            # ── 休市提醒（周五 New York 收盘前 10 分钟）────────────
            ny_tz = pytz.timezone("US/Eastern")
            now_ny = datetime.now(ny_tz)
            if now_ny.weekday() == 4:
                close_target = now_ny.replace(hour=16, minute=50, second=0, microsecond=0)
                close_start = close_target
                close_end   = close_target + timedelta(minutes=5)
                send_key_close = f"{today_key}_close_ny"
                if close_start <= now_ny <= close_end and send_key_close not in last_sent:
                    msg = (
                        "🇺🇸 <b>New York</b> market closes in 10 min\n"
                        "Weekend is coming! 🎉\n"
                        "Great job this week — enjoy your weekend! 🥂"
                    )
                    result = tg_api("sendMessage", {
                        "chat_id": SIGNAL_CID,
                        "text": msg,
                        "parse_mode": "HTML",
                    })
                    if result and result.get("ok"):
                        print("🔔 休市提醒已发送（周五纽约收盘）")
                        last_sent.add(send_key_close)
                    else:
                        print(f"🔔 休市提醒发送失败: {result}")

            time.sleep(30)

    t = threading.Thread(target=loop, daemon=True, name="MarketReminder")
    t.start()
    print("🔔 市场提醒线程已启动（开盘 + 休市 + 经济数据 + 温馨语轮播）")


# ─── 线程 2.5：每日欢迎消息（随机时间）─────────────────────────────────────
def start_daily_welcome():
    """后台线程 — 每天 14:00–18:00 和 19:00–23:00 CST 各随机发一次欢迎消息
    引导新订阅者领取 38 算力 + 邀请码
    """
    last_sent_date = None   # 记录今天日期（用于跨天重置）
    targets_today  = []     # 今天的随机目标时间列表 [(datetime, sent_flag), ...]

    def pick_random_targets():
        """在 14:00–18:00 和 19:00–23:00 CST 各选一个随机时间"""
        now = datetime.now(TZ)
        # 第一档：14:00–18:00 = 0–239 分钟
        base1 = now.replace(hour=14, minute=0, second=0, microsecond=0)
        rand1 = random.randint(0, 4 * 60 - 1)
        t1 = base1 + timedelta(minutes=rand1)
        # 第二档：19:00–23:00 = 0–239 分钟
        base2 = now.replace(hour=19, minute=0, second=0, microsecond=0)
        rand2 = random.randint(0, 4 * 60 - 1)
        t2 = base2 + timedelta(minutes=rand2)
        return [(t1, False), (t2, False)]

    def loop():
        nonlocal last_sent_date, targets_today
        while True:
            now = datetime.now(TZ)
            today = now.strftime("%Y-%m-%d")

            # 新的一天：重置状态，重新随机选时间
            if today != last_sent_date:
                last_sent_date = today
                targets_today  = pick_random_targets()
                t1_str = targets_today[0][0].strftime('%H:%M')
                t2_str = targets_today[1][0].strftime('%H:%M')
                print(f"🤖 今日欢迎消息目标时间: {t1_str} CST / {t2_str} CST")

            # 检查是否到达任一目标时间
            for i, (target_time, sent) in enumerate(targets_today):
                if not sent and now >= target_time:
                    msg = (
                        "🤖 Welcome to <b>Octopus AI Trader</b>\n\n"
                        "📲 下载官方APP获取更多品种AI预测\n"
                        "📲 Download APP for Silver, Oil, ETH, EUR & more\n\n"
                        "🎁 填写邀请码【SG4879】领取38算力\n"
                        "🎁 Invite code [SG4879] — get 38 credits"
                    )
                    keyboard = {
                        "inline_keyboard": [
                            [
                                {"text": "📝 Register", "url": "https://app.octopus-vision.com/html/html/register.html?code=C0144"},
                                {"text": "📱 Download APP", "url": "https://www.octopus-vision.com/#download"},
                            ],
                            [
                                {"text": "🔑 Copy Invite Code", "copy_text": {"text": "SG4879"}},
                            ],
                            [
                                {"text": "🤝 Partnership: @rebecca_octopus", "url": "https://t.me/rebecca_octopus"},
                            ],
                        ]
                    }
                    payload = {
                        "chat_id": SIGNAL_CID,
                        "text": msg,
                        "parse_mode": "HTML",
                        "reply_markup": keyboard,
                    }
                    result = tg_api("sendMessage", payload)
                    if result and result.get("ok"):
                        print(f"🤖 每日欢迎消息已发送 ({now.strftime('%H:%M')} CST)")
                    else:
                        print(f"🤖 欢迎消息发送失败: {result}")
                    targets_today[i] = (target_time, True)

            time.sleep(30)

    t = threading.Thread(target=loop, daemon=True, name="DailyWelcome")
    t.start()
    print("🤖 每日欢迎消息线程已启动（14:00–18:00 + 19:00–23:00 CST 随机各一次）")


# ─── 线程 3：保活机制 ─────────────────────────────────────────────────────

def start_keep_alive():
    def ping():
        while True:
            try:
                resp = requests.get(RENDER_URL, timeout=10)
                print(f"💓 Keep-alive ping: {resp.status_code}")
            except Exception as e:
                print(f"💓 Keep-alive 错误: {e}")
            time.sleep(KEEP_ALIVE_INTERVAL)
    t = threading.Thread(target=ping, daemon=True, name="KeepAlive")
    t.start()
    print("💓 保活线程已启动")


# ─── 线程 4：Flask Web 服务 ───────────────────────────────────────────────

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health_check():
    return {"status": "ok", "service": "octatrade-tg-bot", "time": datetime.now(TZ).isoformat()}

@app.route(f"/webhook/{BOT_TOKEN.split(':')[0]}", methods=["POST"])
def telegram_webhook():
    data = request.get_json(force=True, silent=True)
    if not data:
        return {"ok": False}, 400
    message = data.get("message", {})
    text    = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id")
    if text and chat_id:
        tg_api("sendMessage", {"chat_id": chat_id, "text": f"Received: {text}\n(AI Q&A coming soon)"})
        print(f"[Webhook] 收到消息 from {chat_id}: {text[:50]}")
    return {"ok": True}

def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Web 服务启动，端口 {port}")
    app.run(host="0.0.0.0", port=port)


# ─── 主程序 ────────────────────────────────────────────────────────────────

CHANNEL_DISABLED = False

if __name__ == "__main__":
    print("=" * 60)
    print("  Octopus Smart TG Bot — Render 24/7 部署版")
    print("  版本: v2.6 | 2026-06-11 | 频道: @OctopusAITrader")
    print(f"  启动时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} CST")
    if CHANNEL_DISABLED:
        print("  ⚠️  频道推送已停用（CHANNEL_DISABLED = True）")
    else:
        print(f"  ✅ 目标频道: {SIGNAL_CID}")
        print("  📅 调度模式: 工作日每小时 / 周末每两小时")
        print("  💬 开盘提醒: 温馨语轮播 + 经济数据 + 假期检测")
    print("=" * 60)

    start_keep_alive()
    time.sleep(1)

    if not CHANNEL_DISABLED:
        start_signal_scheduler()
        time.sleep(1)
        start_market_reminder()
        time.sleep(1)
        start_daily_welcome()
    else:
        print("⏸  信号推送已暂停")
        print("⏸  市场提醒已暂停")
        print("⏸  每日欢迎消息已暂停")
        print("💓 仅保活 + Web 服务运行中...")

    start_web_server()
