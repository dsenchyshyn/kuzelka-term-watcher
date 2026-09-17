#!/usr/bin/env python3
"""
Monitors https://planovac.kuzelka.sk/ for free driving-lesson slots (terminy)
in a given month that either start at/after 16:00 or fall on a weekend.
Sends an email notification via Gmail SMTP when new matching slots appear.
"""
import json
import os
import smtplib
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://planovac.kuzelka.sk/"
CALENDAR_URL = "https://planovac.kuzelka.sk/ziak/kalendar"
STATE_FILE = Path(__file__).parent / "state.json"

USERNAME = os.environ["KUZELKA_USERNAME"]
PASSWORD = os.environ["KUZELKA_PASSWORD"]

# Month(s) to watch, as they appear in the "adminkalendar-obdobie" <select>.
# The site lists months as option values counting forward from "current" - 1
# (value "1" = next month, "2" = current month, etc. per observed markup),
# but the safest approach is to match by visible month label text.
TARGET_MONTH_LABEL = os.environ.get("KUZELKA_TARGET_MONTH", "september 2026")
POLL_INTERVAL_SECONDS = int(os.environ.get("KUZELKA_POLL_INTERVAL_SECONDS", "30"))
# Leave a safety margin below GitHub Actions' six-hour job limit for setup.
WATCH_DURATION_SECONDS = int(
    os.environ.get("KUZELKA_WATCH_DURATION_SECONDS", str(5 * 60 * 60 + 50 * 60))
)

MIN_START_HOUR_MINUTE = (16, 0)  # inclusive: 16:00 counts
WEEKEND_WEEKDAYS = {5, 6}  # Saturday=5, Sunday=6 (Python weekday())

WEEKDAY_NAMES_SK = [
    "pondelok",
    "utorok",
    "streda",
    "stvrtok",
    "piatok",
    "sobota",
    "nedela",
]

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTIFY_TO = os.environ.get("NOTIFY_TO", GMAIL_USER)


@dataclass(frozen=True)
class FreeSlot:
    date: str  # dd.mm.yyyy
    start: str  # HH:MM
    end: str  # HH:MM

    def key(self) -> str:
        return f"{self.date} {self.start}-{self.end}"


def parse_date(date_str: str) -> datetime:
    day, month, year = date_str.split(".")
    return datetime(int(year), int(month), int(day))


def slot_matches_criteria(slot: FreeSlot) -> bool:
    date = parse_date(slot.date)
    if date.weekday() in WEEKEND_WEEKDAYS:
        return True
    hour, minute = (int(x) for x in slot.start.split(":"))
    return (hour, minute) >= MIN_START_HOUR_MINUTE


def login(page):
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.locator("#login").fill(USERNAME)
    page.locator("#password").fill(PASSWORD)
    page.locator("#prihlasit").click()
    # Wait for the post-login navigation to actually land, rather than
    # racing "domcontentloaded" (which can still see the old login page's
    # DOM right after the click, before the server-side redirect happens).
    page.wait_for_selector("#login", state="detached", timeout=15000)


def select_month(page, month_label: str):
    page.goto(CALENDAR_URL, wait_until="domcontentloaded")
    if page.locator("#login").is_visible():
        login(page)
        page.goto(CALENDAR_URL, wait_until="domcontentloaded")
    select = page.locator("#adminkalendar-obdobie")
    select.select_option(label=month_label)
    page.locator("#kalendar-hladat").click()
    page.wait_for_selector("td.kalendar-termin, #adminkalendar-obdobie", timeout=15000)


def extract_free_slots(page) -> list[FreeSlot]:
    cells = page.locator("td.kalendar-termin")
    count = cells.count()
    free_slots: list[FreeSlot] = []

    for i in range(count):
        cell = cells.nth(i)
        rows = cell.locator("tbody > tr")
        row_count = rows.count()
        if row_count == 0:
            continue
        line_texts = [rows.nth(r).inner_text().strip() for r in range(row_count)]
        time_line = line_texts[0]
        other_lines = [t for t in line_texts[1:] if t]
        if other_lines:
            continue  # occupied slot (has student/instructor/note info)

        start_end = time_line.split()[0] if time_line else ""
        if "-" not in start_end:
            continue
        start, end = start_end.split("-", 1)

        date_str = find_cell_date(cell)
        if date_str is None:
            continue

        free_slots.append(FreeSlot(date=date_str, start=start.strip(), end=end.strip()))

    return free_slots


def find_cell_date(cell) -> str | None:
    # DOM shape: td.den > table.admin-kalendar-den > tbody > tr (first row has
    # the date inside a <center>) ... > tr > td.kalendar-termin (4 hops up
    # from the termin cell reaches td.den).
    text = cell.evaluate(
        """el => {
            let node = el;
            for (let i = 0; i < 4 && node; i++) node = node.parentElement;
            if (!node) return '';
            const dayTable = node.querySelector('table.admin-kalendar-den');
            if (!dayTable) return '';
            const center = dayTable.querySelector('tr center');
            return center ? center.textContent.trim() : '';
        }"""
    )
    import re

    match = re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", text)
    return match.group(0) if match else None


def load_previous_state() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    data = json.loads(STATE_FILE.read_text())
    return set(data.get("known_slot_keys", []))


def save_state(slot_keys: set[str]):
    STATE_FILE.write_text(json.dumps({"known_slot_keys": sorted(slot_keys)}, indent=2))


def commit_state():
    """Persist state.json to git immediately, so a mid-run crash doesn't
    lose scan progress (previously this only happened once, after the
    whole ~6h job finished)."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", str(STATE_FILE)],
            cwd=STATE_FILE.parent,
            capture_output=True,
            text=True,
            check=True,
        )
        if not status.stdout.strip():
            return
        subprocess.run(
            ["git", "config", "user.name", "kuzelka-watcher-bot"],
            cwd=STATE_FILE.parent,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "actions@users.noreply.github.com"],
            cwd=STATE_FILE.parent,
            check=True,
        )
        subprocess.run(
            ["git", "add", str(STATE_FILE)], cwd=STATE_FILE.parent, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Update known terminy state [skip ci]"],
            cwd=STATE_FILE.parent,
            check=True,
        )
        subprocess.run(
            ["git", "pull", "--rebase"], cwd=STATE_FILE.parent, check=True
        )
        subprocess.run(["git", "push"], cwd=STATE_FILE.parent, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"Failed to persist state.json to git: {exc}", file=sys.stderr)


def send_email(new_slots: list[FreeSlot]):
    lines = [
        f"- {s.date} ({WEEKDAY_NAMES_SK[parse_date(s.date).weekday()]}) {s.start}-{s.end}"
        for s in sorted(new_slots, key=lambda s: (s.date, s.start))
    ]
    body = "Najdene nove volne terminy (po 16:00 alebo cez vikend):\n\n" + "\n".join(lines)
    body += f"\n\nOdkaz: {CALENDAR_URL}"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"Kuzelka: {len(new_slots)} novy volny termin(y)"
    msg["From"] = GMAIL_USER
    msg["To"] = NOTIFY_TO

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_USER, [NOTIFY_TO], msg.as_string())


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        previous_keys = load_previous_state()
        deadline = time.monotonic() + WATCH_DURATION_SECONDS
        scan_number = 0

        logged_in = False
        try:
            while time.monotonic() < deadline:
                scan_number += 1
                scan_started = time.monotonic()
                try:
                    if not logged_in:
                        login(page)
                        logged_in = True
                    select_month(page, TARGET_MONTH_LABEL)
                    all_free_slots = extract_free_slots(page)
                    matching_slots = [
                        s for s in all_free_slots if slot_matches_criteria(s)
                    ]
                    matching_keys = {s.key() for s in matching_slots}
                    new_keys = matching_keys - previous_keys
                    new_slots = [s for s in matching_slots if s.key() in new_keys]

                    print(
                        f"Scan {scan_number}: total={len(all_free_slots)}, "
                        f"matching={len(matching_slots)}, new={len(new_slots)}"
                    )

                    notification_succeeded = True
                    if new_slots:
                        try:
                            send_email(new_slots)
                        except (OSError, smtplib.SMTPException) as exc:
                            print(
                                f"Notification email failed: {exc}",
                                file=sys.stderr,
                            )
                            notification_succeeded = False
                        else:
                            print("Notification email sent.")

                    # Track the current page, not all slots ever seen. This makes
                    # a slot notify again if it disappears and later reappears.
                    if notification_succeeded:
                        previous_keys = matching_keys
                        save_state(previous_keys)
                        commit_state()
                except (PlaywrightError, RuntimeError, ValueError) as exc:
                    print(f"Scan {scan_number} failed: {exc}", file=sys.stderr)
                    logged_in = False

                remaining = deadline - time.monotonic()
                sleep_for = min(
                    POLL_INTERVAL_SECONDS - (time.monotonic() - scan_started),
                    remaining,
                )
                if sleep_for > 0:
                    time.sleep(sleep_for)
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
