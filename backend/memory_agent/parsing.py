"""Turn raw inputs (pasted text, .eml, WhatsApp export, CSV, PDF/DOCX/XLSX, transcripts) into `Interaction`s.

Pure functions, no network: tested in test_parsing.py. Audio is handled in stt.py and then comes back here as
transcript turns.
"""
import csv
import email
import hashlib
import io
import re
from collections import OrderedDict
from datetime import datetime, timezone
from email import policy
from email.utils import getaddresses, parsedate_to_datetime

from contracts import Channel, Interaction, Participant, Turn

from .errors import InvalidInput

PREFIX = {"call": "CALL", "email": "EM", "whatsapp": "WA", "crm": "CRM", "note": "NOTE", "document": "FILE",
          "outcome": "OUT"}
AUDIO_EXT = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg", ".flac"}
DOC_EXT = {".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".html", ".htm"}
MAX_TEXT_CHARS = 60_000


def now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def next_id(channel: str, existing: set[str]) -> str:
    """EM-04 after EM-01..EM-03: short, readable ids because the agent cites them and people click them."""
    p = PREFIX[channel]
    nums = [int(m.group(1)) for i in existing if (m := re.fullmatch(rf"{p}-(\d+)", i))]
    return f"{p}-{max(nums, default=0) + 1:02d}"


def extension(name: str | None) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if name and "." in name else ""


def slug(text: str, n: int = 30) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n] or "file"


# ---------- detection ----------

WA_ANDROID = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4}),?\s(\d{1,2}):(\d{2})(?::\d{2})?\s?([AaPp]\.?[Mm]\.?)?\s[-–]\s([^:]{1,60}):\s?(.*)$")
WA_IOS = re.compile(r"^\[(\d{1,2})/(\d{1,2})/(\d{2,4}),?\s(\d{1,2}):(\d{2})(?::\d{2})?\s?([AaPp]\.?[Mm]\.?)?\]\s([^:]{1,60}):\s?(.*)$")
SPEAKER_LINE = re.compile(r"^\s*([A-Z][\w .'’-]{0,40}?)\s*(?:\(([^)]{1,40})\))?\s*:\s+(.+)$")
EMAIL_HEADERS = re.compile(r"^(From|To|Subject|Date):\s", re.M)


def _clean(text: str) -> str:
    # WhatsApp exports use narrow no-break spaces before AM/PM and left-to-right marks
    return text.replace(" ", " ").replace("‎", "").replace("﻿", "").replace("\r\n", "\n")


def detect_channel(text: str, file_name: str | None = None) -> Channel:
    ext = extension(file_name)
    if ext in AUDIO_EXT:
        return "call"
    if ext == ".eml":
        return "email"
    if ext == ".csv":
        return "crm"
    if ext in DOC_EXT:
        return "document"
    lines = [ln for ln in _clean(text).split("\n")[:40] if ln.strip()]
    if lines and sum(bool(WA_ANDROID.match(ln) or WA_IOS.match(ln)) for ln in lines) >= max(1, len(lines) // 3):
        return "whatsapp"
    if len(EMAIL_HEADERS.findall(text[:2000])) >= 2:
        return "email"
    if lines and sum(bool(SPEAKER_LINE.match(ln)) for ln in lines) >= max(2, len(lines) // 3):
        return "call"
    return "note"


# ---------- rendering (what gets retained) ----------

def render(it: Interaction) -> str:
    people = "; ".join(f"{p.name}" + (f" ({p.role})" if p.role else "") + (" [ours]" if p.side == "ours" else "")
                       for p in it.participants)
    head = f"[{it.document_id}] {it.channel.upper()} on {it.occurred_at.date().isoformat()}: {it.title}."
    if people:
        head += f" Participants: {people}."
    if it.turns:
        body = "\n".join(f"{t.at + ' ' if t.at else ''}{t.speaker}"
                         + (f" ({'our side' if t.side == 'ours' else 'customer'})" if t.side != "unknown" else "")
                         + f": {t.text}" for t in it.turns)
    else:
        body = it.text
    return f"{head}\n{body}"[:MAX_TEXT_CHARS]


def finish(it: Interaction) -> Interaction:
    """`text` stays the raw body; `render()` adds the header and speaker labels at retain time, so a preview the
    salesperson edited (speaker labels, names) is rendered from its edited turns."""
    if it.turns and not it.text:
        it.text = "\n".join(f"{t.speaker}: {t.text}" for t in it.turns)
    return it


# ---------- WhatsApp export ----------

def _wa_date(a: int, b: int, y: int, day_first: bool) -> tuple[int, int, int]:
    y = y + 2000 if y < 100 else y
    return (y, b, a) if day_first else (y, a, b)


def parse_whatsapp(text: str, existing_ids: set[str], known_fps: set[str]) -> tuple[list[Interaction], int, int]:
    """WhatsApp 'Export chat' text → one Interaction per day with only unseen messages.

    Handles Android (`12/09/2026, 21:16 - Name: text`) and iOS (`[12/09/26, 9:16:05 PM] Name: text`) lines,
    multi-line messages, and day/month order (day-first unless a line proves otherwise).
    Returns (interactions, new_messages, duplicate_messages).
    """
    rows = []
    for line in _clean(text).split("\n"):
        m = WA_ANDROID.match(line) or WA_IOS.match(line)
        if m:
            a, b, y, hh, mm, ampm, who, msg = m.groups()
            rows.append([int(a), int(b), int(y), int(hh), int(mm), (ampm or "").lower().replace(".", ""), who.strip(), msg])
        elif rows and line.strip():
            rows[-1][7] += "\n" + line  # continuation of the previous message
    if not rows:
        raise InvalidInput("No WhatsApp messages found. Export the chat with 'Without media' and upload the .txt.")
    day_first = not any(r[1] > 12 for r in rows) or any(r[0] > 12 for r in rows)
    days: OrderedDict[str, list[Turn]] = OrderedDict()
    fps: dict[str, list[str]] = {}
    new = dup = 0
    for a, b, y, hh, mm, ampm, who, msg in rows:
        if msg.strip() in ("<Media omitted>", "") or "end-to-end encrypted" in msg:
            continue
        hh = hh % 12 + (12 if ampm == "pm" else 0) if ampm else hh
        yy, mo, dd = _wa_date(a, b, y, day_first)
        day = f"{yy:04d}-{mo:02d}-{dd:02d}"
        fp = fingerprint(day, f"{hh:02d}:{mm:02d}", who, msg)
        if fp in known_fps:
            dup += 1
            continue
        new += 1
        days.setdefault(day, []).append(Turn(speaker=who, text=msg.strip(), at=f"{hh:02d}:{mm:02d}"))
        fps.setdefault(day, []).append(fp)
    out = []
    for day, turns in days.items():
        doc_id = f"WA-{day}"
        people = list(OrderedDict.fromkeys(t.speaker for t in turns))
        out.append(finish(Interaction(
            document_id=doc_id, channel="whatsapp", occurred_at=datetime.fromisoformat(day + "T12:00:00+00:00"),
            title=f"WhatsApp chat on {day} ({len(turns)} messages)",
            participants=[Participant(name=p, side="unknown") for p in people], turns=turns, text="",
            fingerprints=fps[day], mode="append" if doc_id in existing_ids else "replace")))
    return out, new, dup


# ---------- email ----------

def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", html)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"<[^>]+>", "", html)).strip()


def parse_email(raw: bytes | str, existing_ids: set[str], known_fps: set[str]) -> Interaction:
    msg = (email.message_from_bytes(raw, policy=policy.default) if isinstance(raw, bytes)
           else email.message_from_string(raw, policy=policy.default))
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        body = body_part.get_content()
        if body_part.get_content_type() == "text/html":
            body = _html_to_text(body)
    if not body.strip() and isinstance(raw, str):
        body = raw
    msg_id = (msg.get("Message-ID") or "").strip()
    fp = fingerprint(msg_id) if msg_id else fingerprint(msg.get("Subject", ""), msg.get("Date", ""), body[:500])
    if fp in known_fps:
        from .errors import DuplicateContent
        raise DuplicateContent("This email is already in memory.")
    try:
        when = parsedate_to_datetime(msg["Date"]) if msg.get("Date") else now()
    except (TypeError, ValueError):
        when = now()
    people = []
    for header, side in (("From", "unknown"), ("To", "unknown"), ("Cc", "unknown")):
        for name, addr in getaddresses([str(msg.get(header, ""))]):
            if addr or name:
                people.append(Participant(name=name or addr, side=side, role=header.lower()))
    frm = str(msg.get("From", "")).strip()
    return finish(Interaction(
        document_id=next_id("email", existing_ids), channel="email", occurred_at=when,
        title=str(msg.get("Subject") or "Email").strip()[:120], participants=people,
        text=f"From: {frm}\nTo: {msg.get('To', '')}\nSubject: {msg.get('Subject', '')}\n\n{body.strip()}",
        source_ref=msg_id, fingerprints=[fp]))


# ---------- transcripts, notes, CRM, documents ----------

def transcript_turns(text: str) -> list[Turn]:
    """'Name: words' / 'Name (role): words' lines → turns. Lines without a speaker join the previous turn."""
    turns: list[Turn] = []
    for line in _clean(text).split("\n"):
        if not line.strip():
            continue
        m = SPEAKER_LINE.match(line)
        if m:
            turns.append(Turn(speaker=m.group(1).strip(), text=m.group(3).strip()))
        elif turns:
            turns[-1].text += " " + line.strip()
        else:
            turns.append(Turn(speaker="Unknown", text=line.strip()))
    return turns


def parse_text(text: str, channel: Channel, existing_ids: set[str], title: str | None,
               when: datetime | None, participants: list[Participant]) -> Interaction:
    text = _clean(text).strip()
    if len(text) < 5:
        raise InvalidInput("The text is empty.")
    turns = transcript_turns(text) if channel == "call" else []
    if channel == "call" and len({t.speaker for t in turns}) < 2:
        turns = []  # not speaker-labelled: keep it as plain text
    return finish(Interaction(
        document_id=next_id(channel, existing_ids), channel=channel, occurred_at=when or now(),
        title=(title or text.split("\n", 1)[0])[:120], participants=participants, turns=turns, text=text,
        fingerprints=[fingerprint(channel, text[:2000])]))


def parse_csv(data: bytes, file_name: str, existing_ids: set[str], when: datetime | None) -> Interaction:
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    if not rows:
        raise InvalidInput("The CSV has no rows.")
    lines = ["; ".join(f"{k}: {v}" for k, v in r.items() if k and v not in (None, "")) for r in rows[:200]]
    body = f"CRM export {file_name} ({len(rows)} rows" + (", first 200 shown" if len(rows) > 200 else "") + "):\n"
    return finish(Interaction(
        document_id=next_id("crm", existing_ids), channel="crm", occurred_at=when or now(),
        title=f"CRM export: {file_name}", text=body + "\n".join(lines), source_ref=file_name,
        fingerprints=[fingerprint("csv", hashlib.sha1(data).hexdigest())]))


def parse_document(data: bytes, file_name: str, existing_ids: set[str], when: datetime | None) -> Interaction:
    """PDF / DOCX / XLSX / PPTX / HTML → markdown text with markitdown (the converter Hindsight uses by default),
    so the file goes through our own extraction and customer/company split like every other input."""
    from markitdown import MarkItDown
    try:
        text = MarkItDown().convert_stream(io.BytesIO(data), file_extension=extension(file_name)).text_content
    except Exception as e:
        raise InvalidInput(f"Could not read {file_name}: {str(e)[:150]}") from e
    if not text.strip():
        raise InvalidInput(f"No text found in {file_name} (scanned PDFs need OCR, which is not supported).")
    doc_id = f"FILE-{slug(file_name.rsplit('.', 1)[0])}"
    return finish(Interaction(
        document_id=doc_id, channel="document", occurred_at=when or now(), title=file_name[:120],
        text=text, source_ref=file_name, fingerprints=[fingerprint("file", hashlib.sha1(data).hexdigest())]))
