# 🇮🇹 Italy Visa Slot Checker — Edinburgh

Monitors [VFS Global](https://visa.vfsglobal.com/gbr/en/ita/book-an-appointment) for available Italy Schengen visa appointment slots in Edinburgh and sends you a free Gmail notification the moment one opens.

Runs on your **Mac** — no cloud, no proxy, no third-party services beyond Gmail.

---

## How it works

Every 2 minutes a headless Chromium browser:
1. Logs in to your VFS Global account
2. Walks the booking wizard → selects Schengen category → Edinburgh centre
3. Reads the calendar page — if any date is available it emails you instantly
4. Keeps running and re-notifies each time new slots appear

---

## One-time setup

### 1. Install dependencies

```bash
cd /Users/anantraj/Documents/visa_bot
pip3 install -r requirements.txt
python3 -m playwright install chromium --with-deps
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in your real values:

| Variable | What to put |
|---|---|
| `VFS_EMAIL` | Your VFS Global login email |
| `VFS_PASSWORD` | Your VFS Global password |
| `GMAIL_SENDER` | Your Gmail address (sends the alert from here) |
| `GMAIL_APP_PWD` | 16-char Gmail App Password — see section below |
| `NOTIFY_EMAIL` | Where to receive alerts (can be same as `GMAIL_SENDER`) |
| `CHECK_INTERVAL_SECONDS` | How often to check — default `120` (2 min) |
| `HEADLESS` | `true` = silent background, `false` = watch the browser |

### 3. Make the run script executable

```bash
chmod +x run.sh
```

### 4. Test it manually first

```bash
./run.sh
```

You should see log lines like:
```
── Step 1: Loading VFS landing page …
[landing] URL: https://visa.vfsglobal.com/gbr/en/ita/book-an-appointment
[landing] Body: skip to main content  united kingdom  italy …
Clicked: CTA button […]
── Step 2: Attempting login …
Filled email.
Filled password.
── Step 3: Walking booking wizard …
…
❌  No slots available.
```

Press `Ctrl+C` to stop.

---

## Auto-start on login (launchd)

So the bot starts automatically whenever your Mac is on, without keeping a terminal open:

```bash
# Create the logs directory
mkdir -p /Users/anantraj/Documents/visa_bot/logs

# Install the launchd job
cp com.visabot.italychecker.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.visabot.italychecker.plist
```

The bot now starts on login and restarts itself if it crashes.

**To watch the live logs:**
```bash
tail -f /Users/anantraj/Documents/visa_bot/logs/visabot.log
```

**To stop it:**
```bash
launchctl unload ~/Library/LaunchAgents/com.visabot.italychecker.plist
```

**To start it again:**
```bash
launchctl load ~/Library/LaunchAgents/com.visabot.italychecker.plist
```

---

## Gmail App Password

Your normal Gmail password won't work — you need an App Password:

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already on
3. Search for **"App passwords"** in the search bar
4. Name it `visa_bot`, click **Create**
5. Copy the 16-character code (looks like `abcd efgh ijkl mnop`) into `.env`

---

## Adjusting selectors

VFS Global occasionally updates their UI. If the bot stops detecting slots:

1. Set `HEADLESS=false` in `.env` so you can see the browser
2. Run `./run.sh` and watch what step it gets stuck on
3. Use browser DevTools to inspect the page and update `SLOT_SELECTORS` or
   `NO_SLOT_PHRASES` at the top of [`bot/checker.py`](bot/checker.py)

---

## File structure

```
visa_bot/
├── bot/
│   ├── checker.py                  # Main monitoring loop
│   └── notifier.py                 # Gmail SMTP notification
├── logs/                           # Created on first run
├── .env                            # Your secrets (never commit this)
├── .env.example                    # Template
├── com.visabot.italychecker.plist  # macOS launchd auto-start config
├── run.sh                          # Convenience launcher
├── requirements.txt
└── README.md
```

---

## Security note

`.env` contains your passwords — it is listed in `.gitignore` and will never be committed to git. Do not share it.
