# bot/bot.py — Octa Trade TG Bot (Render 24/7 部署版)
# 框架：AIPRIME 云端部署框架
# 功能：XAUUSD/BTC 信号推送 + 市场开盘提醒 + 保活机制

import os
import sys
import time
import json
import threading
import requests
from datetime import datetime, timezone, timedelta
import pytz

# ─── 配置区 ────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8702664592:AAE7QP3z9Tc9lHegOhOnXuWWpGDWGZKlY7I")
SIGNAL_CID = os.environ.get("SIGNAL_CID", "-1003800874000")   # @octatradehongkong
GROUP_CID  = os.environ.get("GROUP_CID",  "")                  # 预留行情问答群

OCTOPUS_API = "https://app.octopus-vision.com/prod-api/appHuginn/app-api/ai/quote-predict/latest"
OCTOPUS_HEADERS = {"Client-Type": "ANDROID", "Platform": "OCTOPUS"}

RENDER_URL = os.environ.get("RENDER_URL", "https://octatrade-tg-bot.onrender.com")

# 推送时段（CST 整点，±5分钟窗口）
SIGNAL_HOURS_CST = {0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 21, 22}
TZ = pytz.timezone("Asia/Shanghai")  # CST (UTC+8)

# 市场开盘提醒（UTC 时间，开盘前5分钟）
MARKET_REMINDERS = [
    (0,  5, "悉尼 Forex",  "Australia/Sydney"),
    (2,  5, "东京 Forex",   "Asia/Tokyo"),
    (7,  5, "伦敦 Forex",   "Europe/London"),
    (8,  5, "法兰克福 Forex","Europe/Berlin"),
    (13, 5, "纽约 Forex",   "US/Eastern"),
    (14, 5, "芝加哥 Forex", "US/Central"),
]

KEEP_ALIVE_INTERVAL = 600   # 10 分钟
WINDOW_MINUTES = 5          # 推送时间窗口 ±5 分钟

# ─── 工具函数 ──────────────────────────────────────────────────────────────

def tg_api(method, payload=None, timeout=15):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        return resp.json()
    except Exception as e:
        print(f"[TG API] {method} 失败: {e}")
        return None

def fetch_octopus(symbol="XAUUSD"):
    """从 Octopus API 获取最新 AI 预测"""
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
    """构造推送消息（原有格式）"""
    data = fetch_octopus(symbol)
    if not data:
        # 备用：BTC 数据
        if symbol == "XAUUSD":
            return build_signal_message("BTCUSDT")
        return None

    try:
        direction   = data.get("direction", "NEUTRAL")
        probability = data.get("probability", 0)
        resistance  = data.get("resistance", "N/A")
        support     = data.get("support", "N/A")
        suggestion  = data.get("suggestion", {})
        if isinstance(suggestion, str):
            # 尝试解析 JSON 字符串
            try:
                suggestion = json.loads(suggestion)
            except:
                suggestion = {}

        entry = suggestion.get("entry", "N/A")
        tp    = suggestion.get("takeProfit", suggestion.get("tp", "N/A"))
        sl    = suggestion.get("stopLoss",   suggestion.get("sl", "N/A"))

        now_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

        emoji = "🟢" if direction.upper() == "LONG" else "🔴" if direction.upper() == "SHORT" else "⚪"
        dir_text = "做多 LONG" if direction.upper() == "LONG" else "做空 SHORT" if direction.upper() == "SHORT" else "观望"

        lines = [
            f"{emoji} **AI Signal — {symbol}**",
            f"🕐 {now_str} (CST)",
            "",
            f"**方向**: {dir_text}",
            f"**概率**: {probability}%",
            "",
            f"**阻力位**: {resistance}",
            f"**支撑位**: {support}",
            "",
            "**AI Suggestion**",
            f"  入场价: {entry}",
            f"  止盈: {tp}",
            f"  止损: {sl}",
            "",
            "---",
            "📡 Octopus Smart AI · 章鱼智投",
            "@rebeccawongocta",
        ]
        return "\n".join(lines)
    except Exception as e:
        print(f"[build_signal] 构造消息失败: {e}")
        return None

def send_signal_to_channel(symbol="XAUUSD"):
    """推送信号到频道"""
    msg = build_signal_message(symbol)
    if not msg:
        print(f"[{datetime.now(TZ).strftime('%H:%M')}] ⚠️ 无法获取 {symbol} 数据，跳过推送")
        return False

    payload = {
        "chat_id": SIGNAL_CID,
        "text": msg,
        "parse_mode": "Markdown",
    }
    result = tg_api("sendMessage", payload)
    now_str = datetime.now(TZ).strftime("%m-%d %H:%M")
    if result and result.get("ok"):
        print(f"[{now_str}] ✅ 信号推送成功: {symbol}")
        return True
    else:
        print(f"[{now_str}] ❌ 信号推送失败: {result}")
        return False

# ─── 线程 1：信号调度器 ────────────────────────────────────────────────────

def start_signal_scheduler():
    """后台线程 — 在 SIGNAL_HOURS_CST 的 :05 分推送信号"""
    def loop():
        # 启动时补发逻辑
        now = datetime.now(TZ)
        if now.weekday() < 5 and now.hour in SIGNAL_HOURS_CST and now.minute > 5:
            print(f"⏰ 启动时补发（CST {now.hour}:00 已过 :05）")
            try:
                send_signal_to_channel()
            except Exception as e:
                print(f"⏰ 补发失败: {e}")

        while True:
            now = datetime.now(TZ)
            # 计算下一个推送目标时间
            target_today = now.replace(minute=5, second=0, microsecond=0)
            if now.minute >= 5:
                # 找下一个整点
                next_hour = (now.hour + 1) % 24
                target = now.replace(hour=next_hour, minute=5, second=0, microsecond=0)
                if next_hour == 0 and now.hour != 23:
                    target = target + timedelta(days=1)
            else:
                target = target_today

            # 如果目标时间不在 SIGNAL_HOURS_CST 里，往前找到最近的一个
            while target.hour not in SIGNAL_HOURS_CST:
                target = target.replace(hour=(target.hour - 1) % 24)
                if target.hour == now.hour:  # 绕了一圈，找明天
                    target = (target + timedelta(days=1)).replace(hour=list(SIGNAL_HOURS_CST)[0], minute=5)
                    break

            sleep_secs = (target - now).total_seconds()
            if sleep_secs > 0:
                print(f"⏰ 下次推送: {target.strftime('%H:%M')} CST（{sleep_secs/60:.1f} 分钟后）")
                time.sleep(sleep_secs)

            # 到达推送时间，检查窗口
            now2 = datetime.now(TZ)
            if now2.weekday() < 5 and now2.hour in SIGNAL_HOURS_CST:
                try:
                    send_signal_to_channel()
                except Exception as e:
                    print(f"⏰ 定时信号推送异常: {e}")
            else:
                print(f"⏰ {now2.strftime('%a %H:%M')} 非工作日/非推送时段，跳过")

            time.sleep(60)  # 防止同一时段重复推送

    t = threading.Thread(target=loop, daemon=True, name="SignalScheduler")
    t.start()
    print("⏰ 信号调度器线程已启动")

# ─── 线程 2：市场开盘提醒 ─────────────────────────────────────────────────

def start_market_reminder():
    """后台线程 — 主要市场开盘前 5 分钟提醒"""
    def loop():
        last_sent = set()  # 当天已发送的提醒，格式: "YYYY-MM-DD_HH"
        while True:
            now_utc = datetime.now(pytz.UTC)
            now_cst = now_utc.astimezone(TZ)

            # 每天重置 last_sent
            today_key = now_cst.strftime("%Y-%m-%d")
            if not any(k.startswith(today_key) for k in last_sent):
                last_sent.clear()

            for utc_h, utc_m, name, tz_str in MARKET_REMINDERS:
                send_key = f"{today_key}_{utc_h:02d}"
                if send_key in last_sent:
                    continue
                # 检查是否到达提醒时间（UTC）
                if now_utc.hour == utc_h and now_utc.minute >= utc_m and now_utc.minute < utc_m + WINDOW_MINUTES:
                    market_tz = pytz.timezone(tz_str)
                    market_time = now_utc.astimezone(market_tz).strftime("%H:%M")
                    msg = (
                        f"🔔 **市场开盘提醒**\n\n"
                        f"**{name}** 市场将在 **{market_time}** 开盘！\n"
                        f"做好准备，关注行情波动。\n\n"
                        f"📡 Octopus Smart AI"
                    )
                    payload = {"chat_id": SIGNAL_CID, "text": msg, "parse_mode": "Markdown"}
                    result = tg_api("sendMessage", payload)
                    if result and result.get("ok"):
                        print(f"🔔 市场提醒已发送: {name}")
                    else:
                        print(f"🔔 市场提醒发送失败: {name} — {result}")
                    last_sent.add(send_key)

            time.sleep(30)

    t = threading.Thread(target=loop, daemon=True, name="MarketReminder")
    t.start()
    print("🔔 市场提醒线程已启动")

# ─── 线程 3：保活机制 ─────────────────────────────────────────────────────

def start_keep_alive():
    """每 10 分钟 ping 自己，防止 Render 免费版休眠"""
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

# ─── 线程 4：Flask Web 服务（接收 Telegram Webhook）───────────────────────

from flask import Flask, request

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health_check():
    return {"status": "ok", "service": "octatrade-tg-bot", "time": datetime.now(TZ).isoformat()}

@app.route(f"/webhook/{BOT_TOKEN.split(':')[0]}", methods=["POST"])
def telegram_webhook():
    """接收 Telegram 用户消息（预留，用于未来行情问答功能）"""
    data = request.get_json(force=True, silent=True)
    if not data:
        return {"ok": False}, 400

    message = data.get("message", {})
    text = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id")

    if text and chat_id:
        # 简单 echo，未来可接入 AI 问答
        tg_api("sendMessage", {"chat_id": chat_id, "text": f"收到：{text}\n（AI 问答功能开发中）"})
        print(f"[Webhook] 收到消息 from {chat_id}: {text[:50]}")

    return {"ok": True}

def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Web 服务启动，端口 {port}")
    app.run(host="0.0.0.0", port=port)

# ─── 主程序 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Octa Trade TG Bot — Render 24/7 部署版")
    print(f"  启动时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} CST")
    print(f"  目标频道: {SIGNAL_CID}")
    print("=" * 60)

    # 启动 4 个线程
    start_keep_alive()      # 💓 保活（先启动，确保服务不会被休眠）
    time.sleep(1)
    start_signal_scheduler() # ⏰ 信号调度
    time.sleep(1)
    start_market_reminder()  # 🔔 市场提醒

    # 主线程运行 Web 服务（Render 要求端口监听）
    start_web_server()
