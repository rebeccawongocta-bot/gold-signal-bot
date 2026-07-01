#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot/bot_combined.py — Octopus Smart TG Bot (合并版)
# 版本: v3.0 | 2026-07-01
# 功能：XAUUSD信号推送(中英文双频道) + 周一开盘提醒 + 周六休市提醒 + 每日欢迎消息 + HTTP保活
# 运行时间：周一 05:30 CST ~ 周六 07:00 CST（周末休眠省时长）
# 时长计算：~120h/周 × 4.33 = ~520h/月 < 750h ✅

import os
import sys
import json
import time
import random
import logging
import threading
import requests
import pytz
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ─── 配置区 ──────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8702664592:AAE7QP3z9Tc9lHegOhOnXuWWpGDWGZKlY7I")

# 频道 ID
EN_CID = os.environ.get("SIGNAL_CID", "-1003899183014")        # 英文频道 @OctopusAITrader
ZH_CID = os.environ.get("CHINESE_CID", "-1004433114637")       # 中文频道 @OctopusAITrader_ZH

# Octopus API
OCTOPUS_API = "https://app.octopus-vision.com/prod-api/appHuginn/app-api/ai/quote-predict/latest"
OCTOPUS_HEADERS_EN = {"Client-Type": "ANDROID", "Platform": "OCTOPUS"}
OCTOPUS_HEADERS_ZH = {"Client-Type": "ANDROID", "Platform": "OCTOPUS", "Accept-Language": "zh-TW"}

# Render 保活
RENDER_URL = os.environ.get("RENDER_URL", "https://gold-signal-bot-wrk9.onrender.com")

# 时区
TZ = pytz.timezone("Asia/Shanghai")     # CST (UTC+8)
NY_TZ = pytz.timezone("US/Eastern")     # 纽约时区（自动处理夏令时）

# ─── 日志 ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("bot_combined")

# ─── 工具函数 ──────────────────────────────────────────────────────────────

def tg_api(method, payload=None, retries=3):
    """调用 Telegram Bot API"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    for i in range(retries):
        try:
            if payload:
                r = requests.post(url, json=payload, timeout=10)
            else:
                r = requests.get(url, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning(f"tg_api {method} 失败({i+1}/{retries}): {e}")
            time.sleep(2)
    return None


def fetch_octopus(symbol="XAUUSD", lang="en"):
    """调用 Octopus API 获取信号数据"""
    headers = OCTOPUS_HEADERS_ZH if lang == "zh" else OCTOPUS_HEADERS_EN
    try:
        url = f"{OCTOPUS_API}?systemCode={symbol}"
        resp = requests.get(url, headers=headers, timeout=15)
        data = resp.json()
        if data.get("code") == 200 and data.get("data"):
            return data["data"]
        log.warning(f"[API] {symbol} 返回异常: {data}")
    except Exception as e:
        log.warning(f"[API] 获取 {symbol} 失败: {e}")
    return None


# ─── 信号推送 ─────────────────────────────────────────────────────────────

def build_signal_en(symbol="XAUUSD"):
    """构造英文信号消息"""
    data = fetch_octopus(symbol, lang="en")
    if not data:
        return None
    try:
        direction = data.get("direction", "NEUTRAL").upper()
        prob       = int(data.get("directionProbability", 0))
        support_p  = data.get("supportPrice", "N/A")
        resist_p   = data.get("resistancePrice", "N/A")
        target_p   = data.get("targetPrice", "N/A")
        change_r   = data.get("changeRate", "")
        period     = data.get("updatePeriod", "1H")

        # 品种名
        name_raw = data.get("name", symbol)
        try:
            name_obj = json.loads(name_raw) if isinstance(name_raw, str) and name_raw.startswith("{") else {}
            sym_name = name_obj.get("en", str(name_raw))
        except:
            sym_name = str(name_raw)

        # AI 分析
        suggestion_raw = data.get("suggestion", "")
        try:
            sug = json.loads(suggestion_raw) if isinstance(suggestion_raw, str) and suggestion_raw.startswith("{") else {}
            ai_text = sug.get("en", str(suggestion_raw))
        except:
            ai_text = str(suggestion_raw)

        # 方向
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
            f"📊 AI suggestions: {ai_text}",
            "",
            "⚠️ Investing involves risk.",
            "🤝 BD: @rebecca_octopus",
        ]
        return "\n".join(lines)
    except Exception as e:
        log.warning(f"[EN signal] 构造失败: {e}")
        return None


def build_signal_zh(symbol="XAUUSD"):
    """构造中文信号消息"""
    data = fetch_octopus(symbol, lang="zh")
    if not data:
        return None
    try:
        direction = data.get("direction", "NEUTRAL").upper()
        prob       = int(data.get("directionProbability", 0))
        support_p  = data.get("supportPrice", "N/A")
        resist_p   = data.get("resistancePrice", "N/A")
        target_p   = data.get("targetPrice", "N/A")
        change_r   = data.get("changeRate", "")
        period     = data.get("updatePeriod", "1H")

        # 品种名（API 对 zh-TW 请求直接返回中文）
        name_raw = data.get("name", symbol)
        sym_name = str(name_raw).strip() or symbol

        # AI 分析（API 对 zh-TW 请求直接返回中文）
        suggestion_raw = data.get("suggestion", "")
        ai_text = str(suggestion_raw).strip()

        # 方向
        if direction == "UP":
            emoji, arrow, dir_text = "🔵", "⬆️", "做多"
        elif direction == "DOWN":
            emoji, arrow, dir_text = "🔴", "⬇️", "做空"
        else:
            emoji, arrow, dir_text = "⚪", "➖", "持有"

        lines = [
            f"{emoji} {symbol} · {sym_name}",
            f"{arrow} {dir_text}  {prob}%  |  {period}  |  {change_r}",
            "",
            f"🎯 目标位:  {target_p}",
            f"🛡️ 支撑位:  {support_p}",
            f"🚧 阻力位:  {resist_p}",
            "",
            f"📊 AI分析: {ai_text}",
            "",
            "⚠️ 投资有风险，入市需谨慎。",
            "🤝 商务合作: @rebecca_octopus",
        ]
        return "\n".join(lines)
    except Exception as e:
        log.warning(f"[ZH signal] 构造失败: {e}")
        return None


def send_signals():
    """同时推送 XAUUSD 信号到中英文两个频道"""
    now_str = datetime.now(TZ).strftime("%m-%d %H:%M")

    # 英文频道
    msg_en = build_signal_en("XAUUSD")
    if msg_en:
        result = tg_api("sendMessage", {
            "chat_id": EN_CID,
            "text": msg_en,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        if result and result.get("ok"):
            log.info(f"[{now_str}] [EN] 信号推送成功")
        else:
            log.warning(f"[{now_str}] [EN] 信号推送失败: {result}")
    else:
        log.warning(f"[{now_str}] [EN] 无信号数据，跳过")

    # 中文频道
    msg_zh = build_signal_zh("XAUUSD")
    if msg_zh:
        result = tg_api("sendMessage", {
            "chat_id": ZH_CID,
            "text": msg_zh,
            "parse_mode": "HTML",
        })
        if result and result.get("ok"):
            log.info(f"[{now_str}] [ZH] 信号推送成功")
        else:
            log.warning(f"[{now_str}] [ZH] 信号推送失败: {result}")
    else:
        log.warning(f"[{now_str}] [ZH] 无信号数据，跳过")


# ─── 线程 1：信号调度器（每小时 :05 推送 XAUUSD）────────────────────────

def start_signal_scheduler():
    def loop():
        now = datetime.now(TZ)
        log.info(f"信号调度器启动（{now.strftime('%Y-%m-%d %H:%M')} CST）")

        # 启动时如果已过 :05，补发一次
        if now.minute >= 5:
            try:
                log.info("启动补发信号")
                send_signals()
            except Exception as e:
                log.warning(f"补发失败: {e}")

        while True:
            now = datetime.now(TZ)
            # 每小时 :05 推送
            target = now.replace(minute=5, second=0, microsecond=0)
            if now.minute >= 5:
                target += timedelta(hours=1)
            sleep_secs = (target - now).total_seconds()
            log.info(f"下次推送: {target.strftime('%m-%d %H:%M')} CST（{sleep_secs/60:.1f}分钟后）")
            time.sleep(sleep_secs)
            try:
                send_signals()
            except Exception as e:
                log.warning(f"定时推送异常: {e}")
            time.sleep(60)

    t = threading.Thread(target=loop, daemon=True, name="SignalScheduler")
    t.start()
    log.info("信号调度器线程已启动（每小时 :05 推送 XAUUSD）")


# ─── 线程 2：周一开盘提醒 + 周六休市提醒 ────────────────────────────────

def start_weekly_reminders():
    """每周提醒：周一开盘 + 周六休市（仅各发一次）"""

    def loop():
        sent_monday = None   # 记录周一提醒日期
        sent_close  = None   # 记录休市提醒日期

        while True:
            try:
                now = datetime.now(TZ)
                today = now.strftime("%Y-%m-%d")

                # ── 周一开盘提醒（06:00 CST）──
                if now.weekday() == 0 and now.hour == 6 and now.minute < 30:
                    if sent_monday != today:
                        # 英文频道
                        msg_en = (
                            "🚀 <b>New Week, New Opportunities!</b>\n\n"
                            "Markets are opening — a fresh start awaits.\n"
                            "Trade smart, stay sharp, and make it a great week! 📈"
                        )
                        tg_api("sendMessage", {
                            "chat_id": EN_CID,
                            "text": msg_en,
                            "parse_mode": "HTML",
                        })

                        # 中文频道
                        msg_zh = (
                            "🚀 <b>新的一周开始了！</b>\n\n"
                            "市场即将开盘 — 新的机会正在等待。\n"
                            "祝您交易顺利，把握每一个机会！📈"
                        )
                        tg_api("sendMessage", {
                            "chat_id": ZH_CID,
                            "text": msg_zh,
                            "parse_mode": "HTML",
                        })

                        log.info("周一开盘提醒已发送")
                        sent_monday = today

                # ── 周六休市提醒（纽约时间周五 16:50，自动适配夏令时/冬令时）──
                now_ny = datetime.now(NY_TZ)
                if now_ny.weekday() == 4 and now_ny.hour == 16 and now_ny.minute >= 50:
                    close_key = now_ny.strftime("%Y-%m-%d")
                    if sent_close != close_key:
                        # 英文频道
                        msg_en = (
                            "📊 <b>Market Closing Soon</b>\n\n"
                            "The weekend is approaching.\n"
                            "Please check if all your orders are closed.\n\n"
                            "Great job this week — have a wonderful weekend! 🥂"
                        )
                        tg_api("sendMessage", {
                            "chat_id": EN_CID,
                            "text": msg_en,
                            "parse_mode": "HTML",
                        })

                        # 中文频道
                        msg_zh = (
                            "📊 <b>市场即将休市</b>\n\n"
                            "周末即将到来。\n"
                            "请检查您的订单是否都已关闭。\n\n"
                            "本周辛苦了 — 祝您周末愉快！我们下周见 👋"
                        )
                        tg_api("sendMessage", {
                            "chat_id": ZH_CID,
                            "text": msg_zh,
                            "parse_mode": "HTML",
                        })

                        log.info("周六休市提醒已发送")
                        sent_close = close_key

                        # 10 分钟后自动暂停 Render 服务（省时长）
                        threading.Thread(target=suspend_self_delayed, daemon=True).start()

                time.sleep(30)
            except Exception as e:
                log.warning(f"周提醒异常: {e}")
                time.sleep(60)

    t = threading.Thread(target=loop, daemon=True, name="WeeklyReminders")
    t.start()
    log.info("周提醒线程已启动（周一开盘 + 周六休市）")


# ─── 线程 3：每日欢迎消息（14:00-18:00 + 19:00-23:00 随机各一次）────────

def start_daily_welcome():
    """每天 14:00-18:00 和 19:00-23:00 CST 各随机发一次欢迎消息（中英文双频道）"""

    def loop():
        last_sent_date = None
        targets_today  = []

        def pick_random_targets():
            now = datetime.now(TZ)
            # 第一档：14:00-18:00
            base1 = now.replace(hour=14, minute=0, second=0, microsecond=0)
            rand1 = random.randint(0, 4 * 60 - 1)
            t1 = base1 + timedelta(minutes=rand1)
            # 第二档：19:00-23:00
            base2 = now.replace(hour=19, minute=0, second=0, microsecond=0)
            rand2 = random.randint(0, 4 * 60 - 1)
            t2 = base2 + timedelta(minutes=rand2)
            return [(t1, False), (t2, False)]

        while True:
            try:
                now = datetime.now(TZ)
                today = now.strftime("%Y-%m-%d")

                # 新的一天，重新生成目标时间
                if today != last_sent_date:
                    last_sent_date = today
                    targets_today = pick_random_targets()
                    log.info(f"今日欢迎消息时间: {[t[0].strftime('%H:%M') for t in targets_today]}")

                # 检查是否到了发送时间
                for i, (target_time, sent) in enumerate(targets_today):
                    if not sent and now >= target_time:
                        # 英文频道
                        msg_en = (
                            "🤖 Welcome to Octopus AI Trader\n\n"
                            "📲 Download our APP for more AI predictions\n"
                            "📲 Forex · Crypto · Silver · Indices · Crude Oil · Taiwan Stocks · Korea Stocks & more\n\n"
                            "🎁 Invite code 【SG4879】 — Get 38 Credits!"
                        )
                        keyboard_en = {
                            "inline_keyboard": [
                                [
                                    {"text": "📝 Register", "url": "https://app.octopus-vision.com/html/register.html?code=C0144"},
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
                        tg_api("sendMessage", {
                            "chat_id": EN_CID,
                            "text": msg_en,
                            "parse_mode": "HTML",
                            "reply_markup": keyboard_en,
                        })

                        # 中文频道
                        msg_zh = (
                            "🤖 欢迎来到 章鱼智投\n\n"
                            "📲 下载官方APP获取更多品种AI预测\n"
                            "📲 外汇、加密货币、白银、指数、原油、台股、韩股等\n\n"
                            "🎁 填写邀请码【SG4879】领取38算力"
                        )
                        keyboard_zh = {
                            "inline_keyboard": [
                                [
                                    {"text": "📝 注册", "url": "https://app.octopus-vision.com/html/register.html?code=C0144"},
                                    {"text": "📱 下载APP", "url": "https://www.octopus-vision.com/#download"},
                                ],
                                [
                                    {"text": "🔑 复制邀请码", "copy_text": {"text": "SG4879"}},
                                ],
                                [
                                    {"text": "🤝 商务合作: @rebecca_octopus", "url": "https://t.me/rebecca_octopus"},
                                ],
                            ]
                        }
                        tg_api("sendMessage", {
                            "chat_id": ZH_CID,
                            "text": msg_zh,
                            "parse_mode": "HTML",
                            "reply_markup": keyboard_zh,
                        })

                        log.info(f"欢迎消息已发送 ({now.strftime('%H:%M')} CST)")
                        targets_today[i] = (target_time, True)

                time.sleep(30)
            except Exception as e:
                log.warning(f"欢迎消息异常: {e}")
                time.sleep(30)

    t = threading.Thread(target=loop, daemon=True, name="DailyWelcome")
    t.start()
    log.info("每日欢迎消息线程已启动（14:00-18:00 + 19:00-23:00 CST 随机各一次）")


# ─── 线程 4：自我保活（ping 外部 URL 防止 Render 休眠）──────────────────


def suspend_self_delayed():
    """休市提醒后延迟 10 分钟暂停 Render 服务（省周末时长）"""
    log.info("将在 10 分钟后自动暂停 Render 服务...")
    time.sleep(600)  # 10 分钟

    api_key = os.environ.get("RENDER_API_KEY", "")
    service_id = os.environ.get("RENDER_SERVICE_ID", "")
    if not api_key or not service_id:
        log.warning("缺少 RENDER_API_KEY 或 RENDER_SERVICE_ID，无法自动暂停")
        return

    try:
        r = requests.post(
            f"https://api.render.com/v1/services/{service_id}/suspend",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=15,
        )
        log.info(f"自动暂停 Render: HTTP {r.status_code}")
        if r.status_code == 200:
            log.info("✅ Render 服务已暂停，等待周一 GitHub Actions 唤醒")
    except Exception as e:
        log.warning(f"自动暂停失败: {e}")


def keep_alive_self():
    log.info("保活线程启动")
    time.sleep(10)

    render_url = os.environ.get("RENDER_URL", "").strip()
    if not render_url:
        service_name = os.environ.get("RENDER_SERVICE_NAME", "gold-signal-bot")
        render_url = f"https://{service_name}.onrender.com"

    log.info(f"保活目标: {render_url}")
    headers = {"User-Agent": "Render-KeepAlive/1.0"}

    while True:
        try:
            time.sleep(300)  # 5 分钟
            r = requests.get(render_url, headers=headers, timeout=10)
            log.info(f"保活 ping -> {r.status_code}")
        except Exception as e:
            log.warning(f"保活失败: {e}")


# ─── HTTP 保活服务器 ──────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    """Render 健康检查接口 — 返回 200 OK"""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "service": "bot_combined",
            "channels": {"en": EN_CID, "zh": ZH_CID},
            "time": datetime.now(TZ).isoformat()
        }).encode())

    def log_message(self, format, *args):
        log.debug(f"[HTTP] {format % args}")


def start_http_server():
    """启动 HTTP 服务器（主线程阻塞，Render 需要这个端口存活检测）"""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    log.info(f"HTTP 服务器启动，端口: {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()


# ─── 主函数 ────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("  Octopus Smart TG Bot (合并版) v3.0 启动")
    log.info(f"  英文频道: {EN_CID}")
    log.info(f"  中文频道: {ZH_CID}")
    log.info(f"  启动时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} CST")
    log.info(f"  信号品种: XAUUSD only")
    log.info(f"  调度模式: 每小时 :05 推送")
    log.info(f"  周提醒: 周一开盘 + 周六休市")
    log.info(f"  欢迎消息: 14:00-18:00 + 19:00-23:00 随机")
    log.info("=" * 60)

    # 验证 Bot Token
    me = tg_api("getMe")
    if not me or not me.get("ok"):
        log.error("Bot Token 无效，退出")
        sys.exit(1)
    log.info(f"Bot: @{me['result']['username']}")

    # 启动后台线程（全部 daemon）
    t1 = threading.Thread(target=start_signal_scheduler, daemon=True)
    t1.start()

    t2 = threading.Thread(target=start_weekly_reminders, daemon=True)
    t2.start()

    t3 = threading.Thread(target=start_daily_welcome, daemon=True)
    t3.start()

    t4 = threading.Thread(target=keep_alive_self, daemon=True)
    t4.start()

    # 主线程：启动 HTTP 服务器（阻塞）
    start_http_server()


if __name__ == "__main__":
    main()
