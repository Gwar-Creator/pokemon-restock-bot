from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import requests

import family_watch as fw
import family_watch_direct as direct
import family_watch_runner as runner

STATE_PATH = Path(os.getenv("FAMILY_WATCH_EMAIL_STATE", "family_watch_email_state.json"))
EMAIL_TO = [x.strip() for x in os.getenv("FAMILY_WATCH_EMAIL_TO", "").split(",") if x.strip()]
SMTP_HOST = os.getenv("FAMILY_WATCH_SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("FAMILY_WATCH_SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("FAMILY_WATCH_SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("FAMILY_WATCH_SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("FAMILY_WATCH_EMAIL_FROM", "").strip() or SMTP_USERNAME
DRY_RUN = os.getenv("FAMILY_WATCH_EMAIL_DRY_RUN", "1").strip().lower() in {"1", "true", "yes", "on"}


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"version": 1, "sent": {}, "last_run_at": None, "last_sent_at": None}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "sent": {}, "last_run_at": None, "last_sent_at": None}
    if not isinstance(value, dict):
        value = {}
    value.setdefault("version", 1)
    value.setdefault("sent", {})
    return value


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def phase_token(offer: fw.Offer, phase: str) -> str:
    return f"{offer.key}|{phase}"


def pending_items(offers: list[fw.Offer], state: dict, now: datetime) -> list[tuple[str, fw.Offer]]:
    sent = state.get("sent", {}) if isinstance(state.get("sent"), dict) else {}
    items: list[tuple[str, fw.Offer]] = []
    for offer in offers:
        phase = fw.offer_phase(offer, now)
        if phase not in {"upcoming", "current"}:
            continue
        if phase_token(offer, phase) in sent:
            continue
        items.append((phase, offer))
    return items


def _clean_description(offer: fw.Offer) -> tuple[str, dict, dict]:
    aggregate = runner._aggregate_meta(offer.description)
    if aggregate:
        return "", {}, aggregate
    description, access = runner._access_from_description(offer.description)
    return description, access, {}


def format_item(phase: str, offer: fw.Offer) -> str:
    description, access, aggregate = _clean_description(offer)
    status = "KOMMENDE" if phase == "upcoming" else "AKTUELT"
    lines = [f"{status} · {offer.store}", offer.name]

    if aggregate:
        count = int(aggregate.get("count") or 0)
        if count:
            lines.append(f"{count} relevante tøjtilbud samlet")
        low = fw.maybe_float(aggregate.get("min_price"))
        high = fw.maybe_float(aggregate.get("max_price"))
        if low is not None:
            price = fw.format_price(low)
            if high is not None and high != low:
                price += f"–{fw.format_price(high)}"
            lines.append(f"Pris: {price}")
        highlight_count = int(aggregate.get("highlight_count") or 0)
        if highlight_count:
            label = str(aggregate.get("highlight_label") or "SÆRLIGT FUND")
            names = [str(x) for x in aggregate.get("highlight_items", []) if x]
            suffix = f": {' · '.join(names[:4])}" if names else ""
            lines.append(f"🧶 {label}: {highlight_count}{suffix}")
    else:
        lines.append(f"Pris: {fw.format_price(offer.price)}")

    lines.append(f"Gælder: {fw.format_period(offer)}")
    if access.get("access"):
        lines.append(f"Kræver: {access['access']}")
    if description:
        short = description.replace(" | ", ". ").strip()
        if short and fw.normalize_text(short) != fw.normalize_text(offer.name):
            lines.append(short[:240])
    url = direct.official_offer_url(offer)
    if url:
        lines.append(url)
    return "\n".join(lines)


def build_digest(items: list[tuple[str, fw.Offer]], now: datetime) -> tuple[str, str]:
    current = [offer for phase, offer in items if phase == "current"]
    upcoming = [offer for phase, offer in items if phase == "upcoming"]
    local = now.astimezone(fw.COPENHAGEN)
    subject = f"Family Watch – {len(items)} nye tilbud · {local.day}/{local.month}"
    lines = ["Family Watch", "", f"{len(items)} nye tilbud siden seneste mail."]

    if current:
        lines += ["", "AKTUELLE TILBUD", "=" * 18]
        for offer in current:
            lines += [format_item("current", offer), ""]
    if upcoming:
        lines += ["", "KOMMENDE TILBUD", "=" * 18]
        for offer in upcoming:
            lines += [format_item("upcoming", offer), ""]

    lines += ["", "Mailen samler kun nye fase-overgange: ét KOMMENDE og ét AKTUELT pr. tilbud."]
    return subject, "\n".join(lines).rstrip() + "\n"


def send_email(subject: str, body: str) -> None:
    if not EMAIL_TO or not SMTP_USERNAME or not SMTP_PASSWORD or not EMAIL_FROM:
        raise RuntimeError("Email recipient/SMTP credentials are not fully configured")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = EMAIL_FROM
    message["To"] = ", ".join(EMAIL_TO)
    message.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)


def main() -> int:
    direct.install()
    now = datetime.now(timezone.utc)
    config = json.loads(fw.CONFIG_PATH.read_text(encoding="utf-8"))
    session = requests.Session()
    session.headers.update({"User-Agent": fw.USER_AGENT})
    offers, errors = fw.collect_offers(config, session, now=now)
    for error in errors:
        print("SOURCE WARNING:", error)

    state = load_state()
    items = pending_items(offers, state, now)
    print(f"Family Watch email: {len(offers)} matching offers; {len(items)} pending digest items")
    state["last_run_at"] = now.isoformat().replace("+00:00", "Z")

    if not items:
        if not DRY_RUN:
            save_state(state)
        print("No new email digest items.")
        return 0

    subject, body = build_digest(items, now)
    print("SUBJECT:", subject)
    print(body)

    if DRY_RUN:
        print("DRY RUN: no email sent and no email state written.")
        return 0

    send_email(subject, body)
    sent = state.setdefault("sent", {})
    timestamp = now.isoformat().replace("+00:00", "Z")
    for phase, offer in items:
        sent[phase_token(offer, phase)] = {
            "sent_at": timestamp,
            "phase": phase,
            "store": offer.store,
            "name": offer.name,
            "valid_from": offer.valid_from.isoformat().replace("+00:00", "Z"),
            "valid_until": offer.valid_until.isoformat().replace("+00:00", "Z"),
        }
    state["last_sent_at"] = timestamp
    save_state(state)
    print(f"Email sent to {len(EMAIL_TO)} recipient(s); state saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
