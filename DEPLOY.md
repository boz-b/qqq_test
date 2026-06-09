# Deployment Guide — QQQ Intraday Dashboard (Pi + Vercel)

## Overview

This project is designed so a Raspberry Pi does the data work and Vercel serves a static site.

```text
cron on Raspberry Pi
  -> refresh local CSV caches in data/
  -> export static JSON into public/data/
  -> git push
  -> Vercel auto-deploys updated static files
```

### Canonical data locations

- local cache inputs: `data/*.csv`
- deployed static outputs: `public/data/*.json`

`dashboard.py` and `export_json.py` are aligned to this layout.

---

## 1. GitHub repository setup

Create a GitHub repo, then push this project:

```bash
cd ~/qqq_test
git remote add origin git@github.com:YOUR_USERNAME/qqq-dashboard.git
git push -u origin main
```

### Recommended `.gitignore`

Local cache/runtime files should not be committed:

```gitignore
__pycache__/
venv/
logs/
data/*.csv
```

Keep `public/data/` tracked, because those generated JSON files are what Vercel serves.

---

## 2. Vercel setup

1. Sign in to Vercel with GitHub
2. Import the repository
3. Framework preset: **Other**
4. Leave build settings at defaults
5. Deploy

Vercel serves the static app from `public/`, including `public/data/*.json`.

---

## 3. Raspberry Pi setup

### 3.1 Clone and install

```bash
git clone git@github.com:YOUR_USERNAME/qqq-dashboard.git ~/qqq_test
cd ~/qqq_test
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir -p data logs
```

### 3.2 Configure SSH for passwordless push

```bash
ssh-keygen -t ed25519 -C "pi-qqq-dashboard"
cat ~/.ssh/id_ed25519.pub
```

Add the public key to GitHub under **Settings → SSH and GPG keys**.

Test:

```bash
ssh -T git@github.com
```

### 3.3 Set git identity

```bash
git config --global user.email "you@example.com"
git config --global user.name "QQQ Pi Bot"
```

---

## 4. First-time data run

### 4.1 Refresh price caches

```bash
cd ~/qqq_test
source venv/bin/activate
python3 -c "from data_loader import DataLoader; DataLoader().fetch_all()"
```

This refreshes:
- `data/qqq_1m.csv`
- `data/qqq_daily.csv`

### 4.2 Refresh ForexFactory events

Run the scraper separately for the date range you want cached:

```bash
python3 ff_scraper.py --start 2026-02-01 --end 2026-03-31 --csv data/ff_events.csv
```

### 4.3 Export static JSON and push

```bash
python3 export_json.py
```

What this does:
1. refreshes intraday + daily price caches
2. reuses the latest `data/ff_events.csv`
3. writes `public/data/dates.json`
4. writes `public/data/YYYY-MM-DD.json`
5. removes stale `public/data/YYYY-MM-DD.json` files no longer listed in `dates.json`
6. commits + pushes `public/data/` additions, changes, and deletions if needed

---

## 5. Cron job

Edit crontab:

```bash
crontab -e
```

Example weekday export job:

```cron
0 2 * * 2-6 cd /home/pi/qqq_test && venv/bin/python3 export_json.py >> logs/export.log 2>&1
```

If your repo is not under `/home/pi/qqq_test`, change the path accordingly.

### Important note about ForexFactory

`export_json.py` does **not** scrape ForexFactory automatically.
If you want fresh FF events every day, add a separate scraper cron job before the export job.

Example:

```cron
45 1 * * 2-6 cd /home/pi/qqq_test && venv/bin/python3 ff_scraper.py --start $(date +\%F) --end $(date -d "+14 days" +\%F) --csv data/ff_events.csv >> logs/ff.log 2>&1
0 2 * * 2-6 cd /home/pi/qqq_test && venv/bin/python3 export_json.py >> logs/export.log 2>&1
```

If your system `date` flags differ, use a small wrapper shell script instead.

---

## 6. Validation

Useful checks:

```bash
# Dashboard data smoke test
python3 dashboard.py --smoke-test

# Export static JSON
python3 export_json.py

# Check export log
tail -50 ~/qqq_test/logs/export.log
```

---

## 7. Troubleshooting

### No dates in dashboard
- `data/qqq_1m.csv` missing or empty
- run `DataLoader().fetch_all()` first

### Export runs but FF events are stale/missing
- refresh `data/ff_events.csv` with `ff_scraper.py`
- `export_json.py` does not fetch FF events itself

### Vercel shows old data
- `git push` failed
- inspect `logs/export.log`

### Git asks for a password
- SSH key not configured correctly
- re-test with `ssh -T git@github.com`

### Dashboard reads old root-level CSVs
- old checkouts may still have repo-root CSVs
- current intended layout is `data/*.csv`
- migrate any old root CSVs into `data/`
