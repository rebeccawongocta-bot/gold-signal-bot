# ai_signals.py — GitHub Actions 备用推送脚本
# 用法: python ai_signals.py [XAUUSD|BTCUSDT]
# 触发: workflow_dispatch（手动触发，当 Render 服务异常时备用）

import os
import sys
import requests
import json
from datetime import datetime, timezone, timedelta
import pytz

# ─── 配置 ──────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8702664592:AAE7QP3z9Tc9lHegOhOnXuWWpGDWGZKlY7I")
SIGNAL_CID = os.environ.get("SIGNAL_CID", "-1003800874000")

OCTOPUS_API = "https://app.octopus-vision.com/prod-api/appHuginn/app-api/ai/quote-predict/latest"
OCTOPUS_HEADERS = {"Client-Type": "ANDROID", "Platform": "OCTOPUS"}

TZ = pytz.timezone("Asia/Shanghai")

# ─── 核心函数 ──────────────────────────────────────────────────────────────

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
            return build_signal_message("BTCUSDT")
        return None

    try:
        direction   = data.get("direction", "NEUTRAL")
        probability = data.get("probability", 0)
        resistance  = data.get("resistance", "N/A")
        support     = data.get("support", "N/A")
        suggestion  = data.get("suggestion", {})
        if isinstance(suggestion, str):
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

# ─── 主程序 ────────────────────────────────────────────────────────────────

def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    print(f"[{datetime.now(TZ).strftime('%H:%M')}] 开始推送 {symbol} 信号（GitHub Actions 备用）")

    msg = build_signal_message(symbol)
    if not msg:
        print("❌ 无法获取数据，退出")
        sys.exit(1)

    payload = {"chat_id": SIGNAL_CID, "text": msg, "parse_mode": "Markdown"}
    result = tg_api("sendMessage", payload)
    if result and result.get("ok"):
        print(f"✅ GitHub Actions 备用推送成功: {symbol}")
    else:
        print(f"❌ 推送失败: {result}")
        sys.exit(1)

if __name__ == "__main__":
    main()
