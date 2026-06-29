# 🇮🇹 Italy Visa Slot Checker — Edinburgh

A headless bot that monitors [VFS Global](https://visa.vfsglobal.com/gbr/en/ita/book-an-appointment) for available Italy Schengen visa appointment slots in Edinburgh and sends you a **free Gmail notification** the moment one opens.

Designed to run 24/7 on [Railway](https://railway.app) (free tier is sufficient for light polling).

---

## How it works

1. Every N seconds (default: **2 minutes**) Playwright launches a headless Chromium browser.
2. It logs in to your VFS Global account and navigates to the appointment booking page.
3. It inspects the page for available slot indicators.
4. If a slot is detected it sends you an email via Gmail SMTP and continues monitoring.

---

## Prerequisites

| What | Where to get it |
|---|---|
| VFS Global account | [Register at VFS](https://visa.vfsglobal.com/gbr/en/ita) |
| Gmail account | Any Gmail address |
| Gmail **App Password** | [Google Account → Security → App Passwords](https://myaccount.google.com/apppasswords) *(requires 2-Step Verification to be enabled)* |
| [Railway](https://railway.app) account | Free signup |

---

## Local setup (optional — for testing)

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/visa_bot.git
cd visa_bot

# 2. Install dependencies
pip install -r requirements.txt
playwright install chromium --with-deps

# 3. Configure secrets
cp .env.example .env
# Edit .env with your real values

# 4. Run
export $(cat .env | xargs)
python -m bot.checker
```

---

## Deploy to Railway

### Step 1 — Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit: Italy visa slot checker"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/visa_bot.git
git push -u origin main
```

### Step 2 — Create a Railway project

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
2. Select your `visa_bot` repository.
3. Railway will auto-detect the `Dockerfile` and start building.

### Step 3 — Set environment variables

In Railway: **Project → Variables**, add each of the following:

| Variable | Description |
|---|---|
| `VFS_EMAIL` | Your VFS Global login email |
| `VFS_PASSWORD` | Your VFS Global password |
| `GMAIL_SENDER` | Gmail address to send from |
| `GMAIL_APP_PWD` | 16-char App Password (spaces are fine) |
| `NOTIFY_EMAIL` | Email address to receive alerts |
| `PROXY_SERVER` | **Required** — residential proxy `host:port` (see below) |
| `PROXY_USERNAME` | Proxy username (if your provider requires auth) |
| `PROXY_PASSWORD` | Proxy password (if your provider requires auth) |
| `CHECK_INTERVAL_SECONDS` | *(optional)* Seconds between checks, default `120` |
| `HEADLESS` | *(optional)* Keep `true` on Railway |

### Step 4 — Get a free residential proxy

VFS Global blocks all datacenter IPs (AWS, GCP, Railway, etc.) with a `403201` error.
You must route requests through a **residential IP** that looks like a real home user.

**Webshare — free tier (10 residential proxies, no credit card needed):**

1. Sign up at [proxy.webshare.io](https://proxy.webshare.io)
2. Go to **Proxy** → **Residential** → **List** (or **Proxy List** on the free plan)
3. Copy any entry in the format `host:port:username:password`
4. In Railway variables set:
   - `PROXY_SERVER` = `host:port`  (e.g. `p.webshare.io:80`)
   - `PROXY_USERNAME` = the username part
   - `PROXY_PASSWORD` = the password part

> **Why residential?** Datacenter IPs have known ASN ranges that VFS (and most government sites) actively block. A residential proxy uses real home ISP IPs, which pass through fine.

### Step 5 — Deploy

Click **Deploy** (or push a new commit). The bot starts automatically and logs appear in the Railway dashboard.

---

## Generating a Gmail App Password

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security).
2. Enable **2-Step Verification** if not already enabled.
3. Search for **"App passwords"** in the search bar.
4. Select **App** → *Mail* and **Device** → *Other (custom name)* → type `visa_bot`.
5. Copy the 16-character password and paste it into the `GMAIL_APP_PWD` variable.

> **Important:** Use the App Password, not your regular Gmail password. The App Password looks like `abcd efgh ijkl mnop`.

---

## Adjusting selectors

VFS Global occasionally updates their UI. If the bot stops detecting slots correctly:

1. Open `bot/checker.py`.
2. Update `SEL_SLOT_INDICATORS` and `SEL_NO_SLOTS_TEXT` to match the current page HTML (inspect with browser DevTools).

---

## File structure

```
visa_bot/
├── bot/
│   ├── checker.py      # Main monitoring loop (Playwright)
│   └── notifier.py     # Gmail SMTP notification
├── .env.example        # Template for environment variables
├── Dockerfile          # Railway / Docker build
├── railway.toml        # Railway project config
├── requirements.txt    # Python dependencies
└── README.md
```

---

## Disclaimer

This tool is for personal use only. Check VFS Global's terms of service. Do not set `CHECK_INTERVAL_SECONDS` below 60 to avoid overloading their servers.
