# kuzelka-term-watcher

Sleduje kalendár na https://planovac.kuzelka.sk/ a upozorní e-mailom, keď sa
objaví nový voľný termín v sledovanom mesiaci, ktorý:
- začína o 16:00 alebo neskôr, alebo
- pripadá na sobotu/nedeľu.

Sledujú sa **dva mesiace súčasne**: aktuálny kalendárny mesiac a nasledujúci
(napr. september 2026 aj október 2026). Toto okno sa prepočítava pri každej
kontrole, takže po prechode do nového mesiaca sa samo posunie ďalej (žiadne
ručné prenastavovanie). Mesiac sa vyberá priamo cez `<select
id="adminkalendar-obdobie">` podľa jeho popisku (obsahuje vopred široký
rozsah mesiacov dopredu aj dozadu) a potvrdzuje kliknutím na „Hľadať“ - bez
potreby klikať na šípky „<<<“/„>>>“.

GitHub Actions spustí watcher približne každých 6 hodín
(`.github/workflows/watch.yml`). Každý job potom drží prihlásený prehliadač
takmer 6 hodín a v rámci každej kontroly prejde postupne oba sledované
mesiace, s pauzou 30 sekúnd medzi kontrolami. GitHub môže začiatok
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
- `KUZELKA_TARGET_MONTHS` – explicitný zoznam mesiacov oddelený čiarkou, napr.
  `september 2026,október 2026`. Ak nie je nastavené, watcher si sám dopočíta
  aktuálny mesiac + nasledujúci pri každej kontrole (odporúčané - nevyžaduje
  ručné prenastavovanie pri prechode do nového mesiaca).
- `KUZELKA_POLL_INTERVAL_SECONDS` – interval kontroly v sekundách (default `30`)

## Lokálne spustenie

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

export KUZELKA_USERNAME="XXXXXX/XXXX"
export KUZELKA_PASSWORD="heslo"
export GMAIL_USER="you@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export NOTIFY_TO="you@gmail.com"
# voliteľné - inak sa použije aktuálny mesiac + nasledujúci:
# export KUZELKA_TARGET_MONTHS="september 2026,október 2026"

python3 watcher.py
```

Stav (`state.json`) uchováva aktuálne voľné termíny **osobitne pre každý
sledovaný mesiac**, aby sa neposielali opakované notifikácie počas ich
dostupnosti. Ak termín zmizne a neskôr sa znova objaví, príde nová
notifikácia. Mesiac, ktorý vypadne zo sledovaného okna (napr. po prechode do
nového mesiaca), sa zo stavu odstráni.
