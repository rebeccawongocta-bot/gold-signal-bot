# bot/bot.py — Octopus Smart TG Bot (Render 24/7 部署版)
# 版本: v2.1 | 2026-06-10 | 频道: @OctopusAITrader
# 功能：智能信号推送（工作日每小时 / 周末每两小时）+ 市场开盘提醒 + 保活机制

import os
import sys
import time
import json
import threading
import requests
from datetime import datetime, timezone, timedelta
import pytz

from flask import Flask, request

# ─── 配置区 ────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8702664592:AAE7QP3z9Tc9lHegOhOnXuWWpGDWGZKlY7I")
SIGNAL_CID = os.environ.get("SIGNAL_CID", "-1003899183014")   # @OctopusAITrader 新频道

OCTOPUS_API = "https://app.octopus-vision.com/prod-api/appHuginn/app-api/ai/quote-predict/latest"
OCTOPUS_HEADERS = {"Client-Type": "ANDROID", "Platform": "OCTOPUS"}

RENDER_URL = os.environ.get("RENDER_URL", "https://octatrade-tg-bot.onrender.com")

TZ = pytz.timezone("Asia/Shanghai")  # CST (UTC+8)

# 市场开盘提醒（UTC 时间，整点前10分钟提醒）
# 格式: (UTC小时, UTC分钟, 名称, 时区, emoji, 交易时段描述)
MARKET_REMINDERS = [
    (19, 50, "Wellington", "Pacific/Auckland",    "🇳🇿", "Mon-Fri | 07:00 NZST"),
    (21, 50, "Sydney",     "Australia/Sydney",    "🇦🇺", "Mon-Fri | 08:00 AEST"),
    (23, 50, "Tokyo",      "Asia/Tokyo",          "🇯🇵", "Mon-Fri | 09:00 JST"),
    ( 0, 50, "Hong Kong / Singapore", "Asia/Hong_Kong", "🇸🇬", "Mon-Fri | 08:00 CST"),
    ( 5, 50, "Dubai",      "Asia/Dubai",          "🇦🇪", "Sun-Thu | 09:00 GST"),
    ( 6, 50, "London",     "Europe/London",       "🇬🇧", "Mon-Fri | 08:00 BST"),
    (11, 50, "New York",   "US/Eastern",          "🇺🇸", "Mon-Fri | 08:00 EDT"),
    (14, 50, "Los Angeles","US/Pacific",          "🇺🇸", "Mon-Fri | 08:00 PDT"),
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
    """构造推送消息（最终格式）"""
    data = fetch_octopus(symbol)
    if not data:
        # XAUUSD 无返回时，尝试 BTCUSDT
        if symbol == "XAUUSD":
            print(f"[build_signal] {symbol} 无数据，尝试 BTCUSDT")
            return build_signal_message("BTCUSDT")
        return None

    try:
        direction = data.get("direction", "NEUTRAL").upper()
        prob      = int(data.get("directionProbability", 0))
        support_p = data.get("supportPrice", "N/A")
        resist_p  = data.get("resistancePrice", "N/A")
        target_p  = data.get("targetPrice", "N/A")
        change_r  = data.get("changeRate", "")
        period    = data.get("updatePeriod", "1H")

        # 解析品种名称
        name_raw = data.get("name", "{}")
        try:
            name_obj = json.loads(name_raw)
            sym_name = name_obj.get("en", symbol)
        except:
            sym_name = symbol

        # 解析 AI 分析（完整版，英文）
        suggestion_raw = data.get("suggestion", "{}")
        try:
            sug = json.loads(suggestion_raw) if isinstance(suggestion_raw, str) else suggestion_raw
            ai_text = sug.get("en", str(suggestion_raw))
        except:
            ai_text = str(suggestion_raw)

        if direction == "UP":
            emoji = "🔵"
            arrow = "⬆️"
            dir_text = "BUY"
        elif direction == "DOWN":
            emoji = "🔴"
            arrow = "⬇️"
            dir_text = "SELL"
        else:
            emoji = "⚪"
            arrow = "➖"
            dir_text = "HOLD"

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
    """推送信号到频道（使用最终格式）"""
    msg = build_signal_message(symbol)
    if not msg:
        print(f"[{datetime.now(TZ).strftime('%H:%M')}] ⚠️ 无法获取任何信号数据，跳过推送")
        return False

    payload = {
        "chat_id": SIGNAL_CID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
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
    """后台线程 — 智能推送调度
    周一至周五：每小时推送一次（XAUUSD 优先，无返回时推 BTCUSDT）
    周六至周日：每两小时推送一次（推 BTCUSDT）
    """
    def should_push_now():
        """判断是否应该推送（根据星期几）"""
        now = datetime.now(TZ)
        weekday = now.weekday()  # 0=周一, 6=周日
        
        if weekday <= 4:  # 周一至周五：每小时推送
            return True
        else:  # 周六、周日：每两小时推送（仅在偶数小时）
            return now.hour % 2 == 0

    def get_symbol_for_time():
        """根据时间决定推送品种"""
        now = datetime.now(TZ)
        weekday = now.weekday()
        
        if weekday <= 4:  # 周一至周五：优先 XAUUSD
            return "XAUUSD"
        else:  # 周六、周日：推 BTCUSDT（XAUUSD 休市）
            return "BTCUSDT"

    def loop():
        """主循环 — 在 :05 分推送"""
        # 启动时补发逻辑（如果当前已过 :05，立即补发）
        now = datetime.now(TZ)
        print(f"⏰ 信号调度器启动（{now.strftime('%Y-%m-%d %H:%M')} CST）")
        
        current_minute = now.minute
        if current_minute >= 5 and should_push_now():
            try:
                symbol = get_symbol_for_time()
                print(f"⏰ 启动时补发: {symbol}")
                send_signal_to_channel(symbol)
            except Exception as e:
                print(f"⏰ 补发失败: {e}")

        while True:
            now = datetime.now(TZ)
            
            # 计算下一个 :05 分时间点
            if now.weekday() <= 4:  # 周一至周五：每小时 :05
                target = now.replace(minute=5, second=0, microsecond=0)
                if now.minute >= 5:  # 已过当前小时的 :05，跳到下一小时
                    target += timedelta(hours=1)
                sleep_secs = (target - now).total_seconds()
                print(f"⏰ 下次推送: {target.strftime('%H:%M')} CST（{sleep_secs/60:.1f} 分钟后）— 工作日模式")
                
            else:  # 周六、周日：每两小时 :05（仅在偶数小时）
                # 找到下一个偶数小时的 :05
                next_even = now.replace(minute=5, second=0, microsecond=0)
                if next_even.hour % 2 != 0 or now.minute > 5:
                    # 当前是奇数小时，或者已过 :05，跳到下一个偶数小时
                    if next_even.hour % 2 != 0:
                        next_even += timedelta(hours=1)
                    else:
                        next_even += timedelta(hours=2)
                
                # 确保是偶数小时
                while next_even.hour % 2 != 0:
                    next_even += timedelta(hours=1)
                
                if next_even <= now:
                    next_even += timedelta(hours=2)
                
                sleep_secs = (next_even - now).total_seconds()
                print(f"⏰ 下次推送: {next_even.strftime('%H:%M')} CST（{sleep_secs/60:.1f} 分钟后）— 周末模式")
                target = next_even

            time.sleep(sleep_secs)

            # 到达推送时间
            if should_push_now():
                symbol = get_symbol_for_time()
                try:
                    send_signal_to_channel(symbol)
                except Exception as e:
                    print(f"⏰ 定时信号推送异常: {e}")

            time.sleep(60)  # 防止同一时段重复推送

    t = threading.Thread(target=loop, daemon=True, name="SignalScheduler")
    t.start()
    print("⏰ 信号调度器线程已启动（工作日每小时 / 周末每两小时）")


# ─── 线程 2：市场开盘提醒 ─────────────────────────────────────────────────

def start_market_reminder():
    """后台线程 — 全球主要市场开盘前 10 分钟提醒（英文）"""
    def loop():
        last_sent = set()
        while True:
            now_utc = datetime.now(pytz.UTC)
            now_cst = now_utc.astimezone(TZ)

            today_key = now_cst.strftime("%Y-%m-%d")
            if not any(k.startswith(today_key) for k in last_sent):
                last_sent.clear()

            for utc_h, utc_m, name, tz_str, emoji, schedule in MARKET_REMINDERS:
                send_key = f"{today_key}_{utc_h:02d}_{utc_m:02d}"
                if send_key in last_sent:
                    continue
                if now_utc.hour == utc_h and now_utc.minute >= utc_m and now_utc.minute < utc_m + WINDOW_MINUTES:
                    msg = (
                        f"{emoji} {name} open in 10 min\n"
                        f"📅 {schedule}"
                    )
                    payload = {"chat_id": SIGNAL_CID, "text": msg}
                    result = tg_api("sendMessage", payload)
                    if result and result.get("ok"):
                        print(f"🔔 市场提醒已发送: {name}")
                    else:
                        print(f"🔔 市场提醒发送失败: {name} — {result}")
                    last_sent.add(send_key)

            time.sleep(30)

    t = threading.Thread(target=loop, daemon=True, name="MarketReminder")
    t.start()
    print("🔔 市场提醒线程已启动（整点前10分钟，英文）")


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
        tg_api("sendMessage", {"chat_id": chat_id, "text": f"Received: {text}\n(AI Q&A coming soon)"})
        print(f"[Webhook] 收到消息 from {chat_id}: {text[:50]}")

    return {"ok": True}

def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Web 服务启动，端口 {port}")
    app.run(host="0.0.0.0", port=port)


# ─── 主程序 ────────────────────────────────────────────────────────────────
# CHANNEL_DISABLED = True  → 停止所有频道推送，只保留 Web 服务空转
CHANNEL_DISABLED = False

if __name__ == "__main__":
    print("=" * 60)
    print("  Octopus Smart TG Bot — Render 24/7 部署版")
    print("  版本: v2.1 | 2026-06-10 | 频道: @OctopusAITrader")
    print(f"  启动时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} CST")
    if CHANNEL_DISABLED:
        print("  ⚠️  频道推送已停用（CHANNEL_DISABLED = True）")
        print(f"  原目标频道: {SIGNAL_CID}")
    else:
        print(f"  ✅ 目标频道: {SIGNAL_CID}")
        print("  📅 调度模式: 工作日每小时 / 周末每两小时")
    print("=" * 60)

    # 保活线程始终启动（防止 Render 休眠）
    start_keep_alive()
    time.sleep(1)

    if not CHANNEL_DISABLED:
        start_signal_scheduler()
        time.sleep(1)
        start_market_reminder()
    else:
        print("⏸  信号推送已暂停")
        print("⏸  市场提醒已暂停")
        print("💓 仅保活 + Web 服务运行中...")

    # 主线程运行 Web 服务（Render 要求端口监听）
    start_web_server()
