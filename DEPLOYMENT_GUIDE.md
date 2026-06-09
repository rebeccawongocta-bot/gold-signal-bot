# Octa Trade TG Bot — Render 24/7 部署指南

> 基于 AIPRIME 云端部署框架
> 为 @octatradehongkong 频道提供 24/7 不间断 AI 信号推送

---

## 📁 文件清单

```
octatrade-render/
├── bot/
│   ├── bot.py              # Render 主程序（4线程）
│   ├── requirements.txt    # Python 依赖
│   └── Procfile           # Render 启动命令
├── ai_signals.py          # GitHub Actions 备用推送脚本
├── render.yaml            # Render 配置文件
└── .github/
    └── workflows/
        └── signal.yml     # GitHub Actions 工作流
```

---

## 🚀 部署步骤

### Step 1: 创建 GitHub 仓库

```bash
# 在 GitHub 创建新仓库，例如：octatrade-tg-bot
# 然后将以下文件推送上去：
```

将 `octatrade-render/` 目录下的所有文件推送到你的 GitHub 仓库。

### Step 2: 在 Render.com 创建 Web Service

1. 访问 [render.com](https://render.com) 并登录（建议用 GitHub 登录）
2. 点击 **"New +"** → **"Web Service"**
3. 选择 **"Build and deploy from a Git repository"**
4. 连接你的 GitHub 仓库（例如：`你的用户名/octatrade-tg-bot`）
5. 配置：
   - **Name**: `octatrade-tg-bot`
   - **Environment**: `Python 3`
   - **Region**: 选择最近的（Singapore 或 Oregon）
   - **Branch**: `main`
   - **Build Command**: `pip install -r bot/requirements.txt`
   - **Start Command**: `python bot/bot.py`
6. 点击 **"Advanced"** 展开环境变量设置，添加：
   | Key | Value |
   |-----|-------|
   | `TELEGRAM_BOT_TOKEN` | `8702664592:AAE7QP3z9Tc9lHegOhOnXuWWpGDWGZKlY7I` |
   | `SIGNAL_CID` | `-1003800874000` |
   | `RENDER_URL` | `https://octatrade-tg-bot.onrender.com`（部署后替换） |
7. 点击 **"Create Web Service"**

### Step 3: 更新 RENDER_URL

部署成功后，Render 会给你一个 URL（格式：`https://octatrade-tg-bot.onrender.com`）：

1. 回到 Render Dashboard
2. 找到 `octatrade-tg-bot` 服务
3. 点击 **"Environment"** 标签
4. 修改 `RENDER_URL` 的值为你的实际 URL
5. 点击 **"Save Changes"**
6. 服务会自动重启

### Step 4: 配置 GitHub Actions 备用（可选）

如果 Render 服务出现异常，可以用 GitHub Actions 手动触发备用推送：

1. 进入你的 GitHub 仓库
2. 点击 **"Settings"** → **"Secrets and variables"** → **"Actions"**
3. 添加以下 Secrets：
   | Name | Value |
   |------|-------|
   | `TELEGRAM_BOT_TOKEN` | `8702664592:AAE7QP3z9Tc9lHegOhOnXuWWpGDWGZKlY7I` |
   | `SIGNAL_CID` | `-1003800874000` |
4. 保存后，进入 **"Actions"** 标签
5. 选择 **"XAUUSD Signal - Telegram Push (备用)"**
6. 点击 **"Run workflow"** → 选择品种 → **"Run workflow"**

---

## 🔍 验证部署

### 检查 Render 日志

部署后，在 Render Dashboard 点击服务名称 → **"Logs"** 标签，应该看到：

```
💓 保活线程已启动
⏰ 信号调度器线程已启动
🔔 市场提醒线程已启动
🌐 Web 服务启动，端口 10000
```

### 手动触发推送测试

在 Render 服务的 Shell 标签（如果有）或本地运行：

```bash
python ai_signals.py XAUUSD
```

检查 @octatradehongkong 频道是否收到消息。

---

## 📊 推送时间表

| CST 时间 | UTC 时间 | 说明 |
|---------|---------|------|
| 00:05 | 16:05 (前一天) | ✅ 推送 |
| 02:05 | 18:05 (前一天) | ✅ 推送 |
| 04:05 | 20:05 (前一天) | ✅ 推送 |
| 06:05 | 22:05 (前一天) | ✅ 推送 |
| 08:05 | 00:05 | ✅ 推送 |
| 10:05 | 02:05 | ✅ 推送 |
| 12:05 | 04:05 | ✅ 推送 |
| 14:05 | 06:05 | ✅ 推送 |
| 16:05 | 08:05 | ✅ 推送 |
| 18:05 | 10:05 | ✅ 推送 |
| 20:05 | 12:05 | ✅ 推送 |
| 21:05 | 13:05 | ✅ 推送 |
| 22:05 | 14:05 | ✅ 推送 |

**周末和节假日自动跳过**（仅推送工作日信号）。

---

## 🛠️ 故障排查

### 频道收不到信号

1. 检查 Render 日志是否有 `⏰` 相关输出
2. 如果只有 `💓 Keep-alive ping`，说明调度器线程未启动
3. 手动触发 GitHub Actions 备用推送测试 Bot 是否在线

### Render 服务休眠

- 保活线程每 10 分钟 ping 一次，理论上不会休眠
- 如果还是休眠，可以升级到 Render 付费版（每月 $7）

### Octopus API 失败

- 检查 `app.octopus-vision.com` 是否可访问
- 如果 API 失效，脚本会自动尝试 BTCUSDT 作为备用

---

## 📝 维护检查清单

- [ ] 每周检查一次 Render 日志
- [ ] 每月检查 Octopus API 是否正常工作
- [ ] 关注 @octatradehongkong 频道，确认信号是否正常推送
- [ ] 如有异常，手动触发 GitHub Actions 备用推送

---

**部署完成后，你的 @octatradehongkong 频道将实现 24/7 不间断 AI 信号推送！** 🎉
