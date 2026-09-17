# kuzelka-term-watcher

Sleduje kalendár na https://planovac.kuzelka.sk/ a upozorní e-mailom, keď sa
objaví nový voľný termín v sledovanom mesiaci, ktorý:
- začína o 16:00 alebo neskôr, alebo
- pripadá na sobotu/nedeľu.

GitHub Actions spustí watcher približne každých 6 hodín
(`.github/workflows/watch.yml`). Každý job potom drží prihlásený prehliadač
takmer 6 hodín a kalendár kontroluje každých 30 sekúnd. GitHub môže začiatok
naplánovaného jobu oneskoriť, ale kontrola už potom nezávisí od presnosti cron
intervalu. Ak webová relácia vyprší, watcher sa automaticky prihlási znova.

Kalendár podľa dostupnej stránky neposkytuje verejný websocket ani server-sent
events stream. Preto sa nedá spoľahlivo „počúvať socket“; najbližší spoľahlivý
variant je znovu načítať kalendár v jednej živej relácii. Interval je možné
zmeniť premennou `KUZELKA_POLL_INTERVAL_SECONDS`.

## Nastavenie

V nastaveniach repozitára (Settings → Secrets and variables → Actions) pridaj:

**Secrets:**
- `KUZELKA_USERNAME` – prihlasovacie meno (rodné číslo v tvare `XXXXXX/XXXX`)
- `KUZELKA_PASSWORD` – heslo
- `GMAIL_USER` – Gmail adresa, z ktorej sa bude posielať notifikácia
- `GMAIL_APP_PASSWORD` – [App Password](https://myaccount.google.com/apppasswords)
  vygenerované pre tento Gmail účet (vyžaduje zapnuté 2FA)
- `NOTIFY_TO` – e-mail, na ktorý má notifikácia prísť (môže byť rovnaký ako `GMAIL_USER`)

**Variables (voliteľné):**
- `KUZELKA_TARGET_MONTH` – napr. `august 2026` (default v workflowe, ak nie je nastavené)
- `KUZELKA_POLL_INTERVAL_SECONDS` – interval kontroly v sekundách (default `30`)

## Lokálne spustenie

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

export KUZELKA_USERNAME="XXXXXX/XXXX"
export KUZELKA_PASSWORD="heslo"
export KUZELKA_TARGET_MONTH="august 2026"
export GMAIL_USER="you@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export NOTIFY_TO="you@gmail.com"

python3 watcher.py
```

Stav (`state.json`) uchováva aktuálne voľné termíny, aby sa neposielali
opakované notifikácie počas ich dostupnosti. Ak termín zmizne a neskôr sa
znova objaví, príde nová notifikácia.
