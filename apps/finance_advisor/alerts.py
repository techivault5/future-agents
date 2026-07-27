#!/usr/bin/env python3
"""Alert rules for the Finance Advisor dashboard.

Rules are stored in data/alerts.json. `python -m finance_advisor.alerts
--check` evaluates all active rules against live market data and emails
triggered ones via SMTP (config from env; see .env.example). Run it on a
schedule (GitHub Actions workflow: finance-alerts.yml).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR.parent.parent))

logger = logging.getLogger(__name__)

ALERTS_FILE = PROJECT_DIR / "data" / "alerts.json"

CONDITIONS = {
    "price_below": "price drops below threshold",
    "price_above": "price rises above threshold",
    "drop_from_52w_high_pct": "price falls at least N% below its 52-week high (dip window)",
    "day_change_below_pct": "1-day change is worse than -N% (sharp fall)",
    "day_change_above_pct": "1-day change is better than +N% (sharp rise)",
    "signal_dip_watch": "signal enters the dip-watch zone",
}


class AlertRule(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:10])
    asset: str  # key from market_data.WATCHED_ASSETS
    condition: str  # key from CONDITIONS
    threshold: float = 0.0
    note: str = ""
    email: str = ""  # empty → ALERT_EMAIL env var at send time
    active: bool = True
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    last_triggered: str | None = None


def load_alerts() -> list[AlertRule]:
    if not ALERTS_FILE.exists():
        return []
    raw = json.loads(ALERTS_FILE.read_text())
    return [AlertRule(**r) for r in raw]


def save_alerts(rules: list[AlertRule]) -> None:
    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_FILE.write_text(json.dumps([r.model_dump() for r in rules], indent=2))


def evaluate_rule(rule: AlertRule, quote: dict) -> str | None:
    """Return a trigger message if the rule fires against this quote, else None."""
    price = quote.get("price")
    if price is None:
        return None
    name = quote.get("name", rule.asset)
    if rule.condition == "price_below" and price < rule.threshold:
        return f"{name} is at {price:,.2f}, below your {rule.threshold:,.2f} threshold."
    if rule.condition == "price_above" and price > rule.threshold:
        return f"{name} is at {price:,.2f}, above your {rule.threshold:,.2f} threshold."
    if rule.condition == "drop_from_52w_high_pct":
        gap = quote.get("pct_from_52w_high")
        if gap is not None and gap <= -abs(rule.threshold):
            return (
                f"{name} is {abs(gap):.1f}% below its 52-week high "
                f"(your dip trigger: {abs(rule.threshold):.0f}%). "
                "Historically a staggered-buying window — verify against your allocation plan."
            )
    if rule.condition == "day_change_below_pct":
        chg = quote.get("change_1d_pct")
        if chg is not None and chg <= -abs(rule.threshold):
            return f"{name} fell {abs(chg):.1f}% today (trigger: {abs(rule.threshold):.1f}%)."
    if rule.condition == "day_change_above_pct":
        chg = quote.get("change_1d_pct")
        if chg is not None and chg >= abs(rule.threshold):
            return f"{name} rose {chg:.1f}% today (trigger: {abs(rule.threshold):.1f}%)."
    if rule.condition == "signal_dip_watch" and quote.get("signal") == "dip-watch":
        return f"{name} entered dip-watch: {quote.get('signal_reason', '')}."
    return None


def evaluate_all(rules: list[AlertRule], quotes: list[dict]) -> list[tuple[AlertRule, str]]:
    by_key = {q["key"]: q for q in quotes}
    triggered: list[tuple[AlertRule, str]] = []
    for rule in rules:
        if not rule.active:
            continue
        quote = by_key.get(rule.asset)
        if not quote:
            continue
        msg = evaluate_rule(rule, quote)
        if msg:
            triggered.append((rule, msg))
    return triggered


def send_email(subject: str, body: str, to_addr: str) -> bool:
    host = os.environ.get("SMTP_HOST", "")
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    if not (host and user and password and to_addr):
        logger.warning("SMTP not configured (SMTP_HOST/USER/PASSWORD, recipient) — skipping email")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [to_addr], msg.as_string())
        return True
    except (smtplib.SMTPException, OSError) as err:
        logger.error("email send failed: %s", err)
        return False


def check_and_notify(dry_run: bool = False) -> int:
    """Evaluate all rules against live data; email triggered ones. Returns count."""
    from finance_advisor.market_data import fetch_all_quotes

    rules = load_alerts()
    if not rules:
        print("No alert rules configured.")
        return 0
    quotes = fetch_all_quotes()
    triggered = evaluate_all(rules, quotes)
    now = datetime.now(timezone.utc)
    default_to = os.environ.get("ALERT_EMAIL", "")
    disclaimer = (
        "\n\n--\nAutomated educational alert from your Finance Advisor dashboard. "
        "Not licensed financial advice — verify against your own plan before acting."
    )
    for rule, msg in triggered:
        # Cooldown: skip if already triggered in the last 20h (daily cron ≈ 1/day)
        if rule.last_triggered:
            last = datetime.fromisoformat(rule.last_triggered)
            if (now - last).total_seconds() < 20 * 3600:
                continue
        to_addr = rule.email or default_to
        subject = f"[Finance Advisor] {msg[:80]}"
        body = msg + (f"\nYour note: {rule.note}" if rule.note else "") + disclaimer
        print(f"TRIGGERED [{rule.id}] {msg}")
        if not dry_run and send_email(subject, body, to_addr):
            rule.last_triggered = now.isoformat(timespec="seconds")
    if not dry_run:
        save_alerts(rules)
    return len(triggered)


def main() -> int:
    parser = argparse.ArgumentParser(description="Finance Advisor alerts")
    parser.add_argument("--check", action="store_true", help="Evaluate rules and send emails")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without emailing")
    parser.add_argument("--list", action="store_true", help="List configured rules")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.list:
        for rule in load_alerts():
            state = "on" if rule.active else "off"
            print(
                f"[{rule.id}] {state} {rule.asset} {rule.condition} "
                f"{rule.threshold} → {rule.email or '$ALERT_EMAIL'}"
            )
        return 0
    if args.check or args.dry_run:
        count = check_and_notify(dry_run=args.dry_run)
        print(f"{count} alert(s) triggered.")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
