"""
chat_budget.py — Konfiguration, Kostenbudgets, Rate-Limits und Protokoll für «Frage zu den Daten»
================================================================================================
Eigene SQLite-Datei (chat.sqlite neben der Hauptdatenbank), damit die Dashboard-Daten unberührt bleiben.
Beträge werden als ganze Zahlen in µRappen geführt (1 Rappen = 1'000'000 µRp), keine Fliesskommafehler.

Mehrstufig und atomar (BEGIN IMMEDIATE, auch über mehrere gunicorn-Prozesse):
  * VOR jedem API-Aufruf wird der schlimmste Fall (geschätzte Eingabe-Tokens + max_tokens zum Ausgabepreis) gleichzeitig gegen Monats-, Sitzungs-
    und IP-Tagesbudget reserviert; reicht eines nicht, wird nichts aufgerufen. Nach der Antwort wird die Reservierung durch die tatsächlichen Kosten
    aus den usage-Angaben der API ersetzt.
  * Zusätzlich: Fragen je Sitzung, neue Sitzungen je IP und Tag, Anfragen je IP und Minute/Stunde, globale Anfragen je Stunde.
IP-Adressen werden nie im Klartext gespeichert: HMAC mit Tagessalz → am Folgetag nicht mehr verknüpfbar. Fragen werden gekürzt höchstens 30 Tage protokolliert.
"""

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

URP = 1_000_000                       # µRappen je Rappen


class ChatError(Exception):
    """Fehler mit nutzerfreundlicher Meldung."""
    status = 429

    def __init__(self, message: str, kind: str = ""):
        super().__init__(message)
        self.message = message
        self.kind = kind


class RateLimited(ChatError):
    status = 429


class BudgetExceeded(ChatError):
    status = 429


# ── Konfiguration ─────────────────────────────────────────────────────────────

_dotenv_cache: dict = {"path": None, "mtime": None, "vals": {}}


def _base_dir() -> str:
    sq = os.environ.get("SQLITE_PATH")
    if sq:
        return os.path.dirname(os.path.dirname(os.path.abspath(sq)))        # ~/daten-li (data/ liegt darin)
    return os.path.dirname(os.path.abspath(__file__))


def _dotenv() -> dict:
    """~/daten-li/.env (KEY=VALUE, # Kommentare); nur gelesen, wenn die Datei existiert. Umgebungsvariablen haben Vorrang."""
    path = os.environ.get("AI_CHAT_ENV_FILE") or os.path.join(_base_dir(), ".env")
    try:
        mt = os.stat(path).st_mtime
    except OSError:
        return {}
    c = _dotenv_cache
    if c["path"] == path and c["mtime"] == mt:
        return c["vals"]
    vals = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            vals[k] = v
    c.update(path=path, mtime=mt, vals=vals)
    return vals


def env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    if v is None or v == "":
        v = _dotenv().get(name, default)
    return v if v is not None else default


def _num(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        return float(default)


@dataclass
class Config:
    enabled: bool
    api_key: str
    model: str
    month_budget_urp: int
    session_budget_urp: int
    ip_day_budget_urp: int
    price_in_urp: float          # µRp je Eingabe-Token
    price_out_urp: float         # µRp je Ausgabe-Token
    max_tokens: int
    max_input_chars: int
    history: int
    questions_per_session: int
    ip_per_min: int
    ip_per_hour: int
    global_per_hour: int
    sessions_per_ip_day: int
    warn_pct: float
    log_days: int
    timeout: float
    effort: str
    thinking: str
    max_api_calls: int


def load_config() -> Config:
    """Liest die Konfiguration bei jedem Aufruf (Umgebung bzw. .env): der Kill-Switch wirkt ohne Neustart."""
    on = env("AI_CHAT_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
    if os.path.exists(os.path.join(_base_dir(), "data", "chat.disabled")):
        on = False
    return Config(
        enabled=on,
        api_key=env("AI_CHAT_API_KEY"),
        model=env("AI_CHAT_MODEL", "claude-haiku-5-5"),
        month_budget_urp=int(_num("AI_CHAT_MONTH_BUDGET_RP", 1000) * URP),
        session_budget_urp=int(_num("AI_CHAT_SESSION_BUDGET_RP", 20) * URP),
        ip_day_budget_urp=int(_num("AI_CHAT_IP_DAY_BUDGET_RP", 30) * URP),
        # Haiku 5.5: 0.10 USD / 0.50 USD je Million Token (Preisseite der Anthropic-Dokumentation); mit Kurs 1 CHF = 1 USD bewusst grosszügig gerechnet
        price_in_urp=_num("AI_CHAT_PRICE_IN_URP", 10.0),
        price_out_urp=_num("AI_CHAT_PRICE_OUT_URP", 50.0),
        max_tokens=int(_num("AI_CHAT_MAX_TOKENS", 800)),         # inkl. Denkanteil (Haiku 5.5 denkt standardmässig adaptiv) und Werkzeug-JSON
        max_input_chars=int(_num("AI_CHAT_MAX_INPUT_CHARS", 500)),
        history=int(_num("AI_CHAT_HISTORY", 2)),
        questions_per_session=int(_num("AI_CHAT_Q_PER_SESSION", 15)),
        ip_per_min=int(_num("AI_CHAT_IP_PER_MIN", 5)),
        ip_per_hour=int(_num("AI_CHAT_IP_PER_HOUR", 30)),
        global_per_hour=int(_num("AI_CHAT_GLOBAL_PER_HOUR", 200)),
        sessions_per_ip_day=int(_num("AI_CHAT_SESSIONS_PER_IP_DAY", 5)),
        warn_pct=_num("AI_CHAT_WARN_PCT", 80),
        log_days=int(_num("AI_CHAT_LOG_DAYS", 30)),
        timeout=_num("AI_CHAT_TIMEOUT", 25),
        effort=env("AI_CHAT_EFFORT", "low"),
        thinking=env("AI_CHAT_THINKING", ""),
        max_api_calls=int(_num("AI_CHAT_MAX_API_CALLS", 3)),
    )


def cost_urp(cfg: Config, usage: dict) -> int:
    """Tatsächliche Kosten aus der usage-Angabe der API-Antwort (aufgerundet). Cache-Schreibzugriffe zu 1.25×, -Lesezugriffe zu 0.1× des Eingabepreises."""
    u = usage or {}
    tin = int(u.get("input_tokens") or 0) + 1.25 * int(u.get("cache_creation_input_tokens") or 0) + 0.1 * int(u.get("cache_read_input_tokens") or 0)
    tout = int(u.get("output_tokens") or 0)
    return int(-(-(tin * cfg.price_in_urp + tout * cfg.price_out_urp) // 1))


def worst_case_urp(cfg: Config, input_chars: int) -> int:
    """Schlimmster Fall vor dem Aufruf: Eingabe grosszügig als 1 Token je 2.5 Zeichen (+200) und die volle max_tokens-Ausgabe."""
    est_in = int(input_chars / 2.5) + 200
    return int(-(-(est_in * cfg.price_in_urp + cfg.max_tokens * cfg.price_out_urp) // 1))


# ── Datenbank ─────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS chat_month (ym TEXT PRIMARY KEY, spent_urp INTEGER NOT NULL DEFAULT 0, reserved_urp INTEGER NOT NULL DEFAULT 0,
    calls INTEGER NOT NULL DEFAULT 0, questions INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS chat_session (sid TEXT PRIMARY KEY, created INTEGER NOT NULL, day TEXT NOT NULL, ip_hash TEXT NOT NULL,
    spent_urp INTEGER NOT NULL DEFAULT 0, reserved_urp INTEGER NOT NULL DEFAULT 0, questions INTEGER NOT NULL DEFAULT 0, last INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS chat_ip (day TEXT NOT NULL, ip_hash TEXT NOT NULL, spent_urp INTEGER NOT NULL DEFAULT 0, reserved_urp INTEGER NOT NULL DEFAULT 0,
    sessions INTEGER NOT NULL DEFAULT 0, questions INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, ip_hash));
CREATE TABLE IF NOT EXISTS chat_events (ts INTEGER NOT NULL, ip_hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_chat_events ON chat_events (ts);
CREATE TABLE IF NOT EXISTS chat_turn (sid TEXT NOT NULL, n INTEGER NOT NULL, q TEXT NOT NULL, a TEXT NOT NULL, PRIMARY KEY (sid, n));
CREATE TABLE IF NOT EXISTS chat_log (ts INTEGER NOT NULL, ip_hash TEXT NOT NULL, sid TEXT NOT NULL, q TEXT NOT NULL, outcome TEXT NOT NULL, cost_urp INTEGER NOT NULL DEFAULT 0);
"""
_init_done: set = set()
_init_lock = threading.Lock()


def db_path() -> str:
    p = os.environ.get("CHAT_DB")
    if p:
        return p
    sq = os.environ.get("SQLITE_PATH")
    return os.path.join(os.path.dirname(os.path.abspath(sq)), "chat.sqlite") if sq else os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_data", "chat.sqlite")


def usage_json_path() -> str:
    return os.environ.get("CHAT_USAGE_JSON") or os.path.join(os.path.dirname(db_path()), "chat_usage.json")


def connect() -> sqlite3.Connection:
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path, timeout=15, isolation_level=None)       # Autocommit: Transaktionen explizit per BEGIN IMMEDIATE
    c.execute("PRAGMA busy_timeout = 15000")
    c.row_factory = sqlite3.Row
    with _init_lock:
        if path not in _init_done:
            c.execute("PRAGMA journal_mode = WAL")
            c.executescript(_DDL)
            _init_done.add(path)
    return c


class _Tx:
    def __init__(self):
        self.c = connect()

    def __enter__(self):
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, et, ev, tb):
        try:
            self.c.execute("ROLLBACK" if et else "COMMIT")
        finally:
            self.c.close()
        return False


def _day(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")


def _ym(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")


def secret() -> bytes:
    s = env("AI_CHAT_SECRET")
    if s:
        return s.encode()
    path = os.path.join(os.path.dirname(db_path()), "chat_secret")
    try:
        with open(path, "rb") as f:
            v = f.read().strip()
            if v:
                return v
    except OSError:
        pass
    v = secrets.token_hex(32).encode()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600) if not os.path.exists(path) else None
    if fd is not None:
        with os.fdopen(fd, "wb") as f:
            f.write(v)
    else:                                       # parallel von anderem Prozess angelegt
        with open(path, "rb") as f:
            v = f.read().strip()
    return v


def ip_hash(ip: str, now: float | None = None) -> str:
    day = _day(now if now is not None else time.time())
    return hmac.new(secret(), f"{day}|{ip}".encode(), hashlib.sha256).hexdigest()[:20]


def clean_ip(candidate: str, fallback: str) -> str:
    try:
        return str(ipaddress.ip_address((candidate or "").strip()))
    except ValueError:
        return fallback or "0.0.0.0"


# ── Zulassung, Reservierung, Abrechnung ───────────────────────────────────────

@dataclass
class Admission:
    sid: str
    ip_hash: str
    day: str
    ym: str
    new_session: bool


def admit(sid: str | None, ip: str, cfg: Config, now: float | None = None) -> Admission:
    """Prüft Rate-Limits und legt bei Bedarf eine Sitzung an; zählt die Frage. Wirft RateLimited/BudgetExceeded mit freundlicher Meldung."""
    now = time.time() if now is None else now
    day, ym = _day(now), _ym(now)
    ih = ip_hash(ip, now)
    with _Tx() as c:
        n_min = c.execute("SELECT COUNT(*) FROM chat_events WHERE ip_hash = ? AND ts > ?", (ih, now - 60)).fetchone()[0]
        if n_min >= cfg.ip_per_min:
            raise RateLimited("Zu viele Fragen in kurzer Zeit. Bitte kurz warten und dann erneut versuchen.", "ip_min")
        n_hour = c.execute("SELECT COUNT(*) FROM chat_events WHERE ip_hash = ? AND ts > ?", (ih, now - 3600)).fetchone()[0]
        if n_hour >= cfg.ip_per_hour:
            raise RateLimited("Stundenlimit für diese Verbindung erreicht. Bitte später wieder versuchen.", "ip_hour")
        n_glob = c.execute("SELECT COUNT(*) FROM chat_events WHERE ts > ?", (now - 3600,)).fetchone()[0]
        if n_glob >= cfg.global_per_hour:
            raise RateLimited("Die Funktion ist gerade stark ausgelastet. Bitte später wieder versuchen.", "global_hour")
        c.execute("INSERT OR IGNORE INTO chat_ip (day, ip_hash) VALUES (?, ?)", (day, ih))
        ip_row = c.execute("SELECT * FROM chat_ip WHERE day = ? AND ip_hash = ?", (day, ih)).fetchone()
        s = c.execute("SELECT * FROM chat_session WHERE sid = ?", (sid,)).fetchone() if sid else None
        new = False
        if s is None:
            if ip_row["sessions"] >= cfg.sessions_per_ip_day:
                raise RateLimited("Für heute wurden von dieser Verbindung zu viele neue Sitzungen gestartet. Bitte morgen wieder.", "ip_sessions")
            sid = secrets.token_hex(16)
            c.execute("INSERT INTO chat_session (sid, created, day, ip_hash, last) VALUES (?, ?, ?, ?, ?)", (sid, int(now), day, ih, int(now)))
            c.execute("UPDATE chat_ip SET sessions = sessions + 1 WHERE day = ? AND ip_hash = ?", (day, ih))
            new = True
        elif s["questions"] >= cfg.questions_per_session:
            raise BudgetExceeded(f"In dieser Sitzung sind höchstens {cfg.questions_per_session} Fragen möglich.", "session_questions")
        c.execute("UPDATE chat_session SET questions = questions + 1, last = ? WHERE sid = ?", (int(now), sid))
        c.execute("UPDATE chat_ip SET questions = questions + 1 WHERE day = ? AND ip_hash = ?", (day, ih))
        c.execute("INSERT OR IGNORE INTO chat_month (ym) VALUES (?)", (ym,))
        c.execute("UPDATE chat_month SET questions = questions + 1 WHERE ym = ?", (ym,))
        c.execute("INSERT INTO chat_events (ts, ip_hash) VALUES (?, ?)", (int(now), ih))
    return Admission(sid, ih, day, ym, new)


def reserve(adm: Admission, worst_urp: int, cfg: Config) -> int:
    """Reserviert den schlimmsten Fall atomar auf Monat, Sitzung und IP-Tag; sonst BudgetExceeded (es wird nichts aufgerufen)."""
    with _Tx() as c:
        m = c.execute("SELECT spent_urp + reserved_urp AS u FROM chat_month WHERE ym = ?", (adm.ym,)).fetchone()
        s = c.execute("SELECT spent_urp + reserved_urp AS u FROM chat_session WHERE sid = ?", (adm.sid,)).fetchone()
        i = c.execute("SELECT spent_urp + reserved_urp AS u FROM chat_ip WHERE day = ? AND ip_hash = ?", (adm.day, adm.ip_hash)).fetchone()
        if m is None or m["u"] + worst_urp > cfg.month_budget_urp:
            raise BudgetExceeded("Das Kontingent für diesen Monat ist erschöpft. Die Funktion steht ab dem nächsten Monat wieder zur Verfügung.", "month")
        if s is None or s["u"] + worst_urp > cfg.session_budget_urp:
            raise BudgetExceeded(f"Das Kontingent dieser Sitzung ({cfg.session_budget_urp / URP:g} Rappen) ist erschöpft. Bitte später eine neue Sitzung beginnen.", "session")
        if i is None or i["u"] + worst_urp > cfg.ip_day_budget_urp:
            raise BudgetExceeded("Das Tageskontingent für diese Verbindung ist erschöpft. Bitte morgen wieder versuchen.", "ip_day")
        c.execute("UPDATE chat_month SET reserved_urp = reserved_urp + ? WHERE ym = ?", (worst_urp, adm.ym))
        c.execute("UPDATE chat_session SET reserved_urp = reserved_urp + ? WHERE sid = ?", (worst_urp, adm.sid))
        c.execute("UPDATE chat_ip SET reserved_urp = reserved_urp + ? WHERE day = ? AND ip_hash = ?", (worst_urp, adm.day, adm.ip_hash))
    return worst_urp


def settle(adm: Admission, reserved_urp: int, actual_urp: int, called: bool = True):
    """Ersetzt die Reservierung durch die tatsächlichen Kosten (actual_urp; bei nicht erfolgtem Aufruf 0)."""
    with _Tx() as c:
        c.execute("UPDATE chat_month SET reserved_urp = MAX(0, reserved_urp - ?), spent_urp = spent_urp + ?, calls = calls + ? WHERE ym = ?",
                  (reserved_urp, actual_urp, 1 if called else 0, adm.ym))
        c.execute("UPDATE chat_session SET reserved_urp = MAX(0, reserved_urp - ?), spent_urp = spent_urp + ? WHERE sid = ?", (reserved_urp, actual_urp, adm.sid))
        c.execute("UPDATE chat_ip SET reserved_urp = MAX(0, reserved_urp - ?), spent_urp = spent_urp + ? WHERE day = ? AND ip_hash = ?",
                  (reserved_urp, actual_urp, adm.day, adm.ip_hash))


def session_left_urp(adm: Admission, cfg: Config) -> int:
    with _Tx() as c:
        s = c.execute("SELECT spent_urp + reserved_urp AS u FROM chat_session WHERE sid = ?", (adm.sid,)).fetchone()
    return max(0, cfg.session_budget_urp - (s["u"] if s else 0))


# ── Verlauf und Protokoll ─────────────────────────────────────────────────────

def history(sid: str, n: int) -> list:
    if n <= 0:
        return []
    with _Tx() as c:
        rows = c.execute("SELECT q, a FROM chat_turn WHERE sid = ? ORDER BY n DESC LIMIT ?", (sid, n)).fetchall()
    return [(r["q"], r["a"]) for r in reversed(rows)]


def add_turn(sid: str, q: str, a: str):
    with _Tx() as c:
        n = c.execute("SELECT COALESCE(MAX(n), 0) + 1 FROM chat_turn WHERE sid = ?", (sid,)).fetchone()[0]
        c.execute("INSERT INTO chat_turn (sid, n, q, a) VALUES (?, ?, ?, ?)", (sid, n, q[:600], a[:1500]))


def log_question(adm: Admission, q: str, outcome: str, cost: int, now: float | None = None):
    now = time.time() if now is None else now
    with _Tx() as c:
        c.execute("INSERT INTO chat_log (ts, ip_hash, sid, q, outcome, cost_urp) VALUES (?, ?, ?, ?, ?, ?)",
                  (int(now), adm.ip_hash, adm.sid[:8], q[:300], outcome[:60], int(cost)))


def prune(cfg: Config | None = None, now: float | None = None) -> dict:
    """Löscht Protokoll/Verlauf nach cfg.log_days, Zähler alter Tage und Sitzungen; ruft der Worker täglich auf."""
    cfg = cfg or load_config()
    now = time.time() if now is None else now
    cutoff = now - cfg.log_days * 86400
    with _Tx() as c:
        a = c.execute("DELETE FROM chat_log WHERE ts < ?", (int(cutoff),)).rowcount
        sess = [r[0] for r in c.execute("SELECT sid FROM chat_session WHERE last < ?", (int(cutoff),)).fetchall()]
        for sid in sess:
            c.execute("DELETE FROM chat_turn WHERE sid = ?", (sid,))
        b = c.execute("DELETE FROM chat_session WHERE last < ?", (int(cutoff),)).rowcount
        d = c.execute("DELETE FROM chat_ip WHERE day < ?", (_day(now - 3 * 86400),)).rowcount
        e = c.execute("DELETE FROM chat_events WHERE ts < ?", (int(now - 2 * 3600),)).rowcount
    return {"log": a, "sessions": b, "ip_days": d, "events": e}


# ── Verbrauch für das Monitoring ──────────────────────────────────────────────

def usage_snapshot(cfg: Config | None = None, now: float | None = None) -> dict:
    cfg = cfg or load_config()
    now = time.time() if now is None else now
    ym = _ym(now)
    with _Tx() as c:
        c.execute("INSERT OR IGNORE INTO chat_month (ym) VALUES (?)", (ym,))
        m = c.execute("SELECT * FROM chat_month WHERE ym = ?", (ym,)).fetchone()
    used = m["spent_urp"] + m["reserved_urp"]
    pct = round(100.0 * used / cfg.month_budget_urp, 2) if cfg.month_budget_urp else 100.0
    state = "exhausted" if pct >= 100 else "warn" if pct >= cfg.warn_pct else "ok"
    return {
        "month": ym, "enabled": cfg.enabled, "budget_rp": round(cfg.month_budget_urp / URP, 4), "spent_rp": round(m["spent_urp"] / URP, 4),
        "reserved_rp": round(m["reserved_urp"] / URP, 4), "percent": pct, "warn_percent": cfg.warn_pct, "state": state,
        "calls": m["calls"], "questions": m["questions"], "model": cfg.model,
        "updated": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_usage_json(cfg: Config | None = None, now: float | None = None) -> dict:
    """Atomar nach chat_usage.json (Pfad: CHAT_USAGE_JSON, sonst neben chat.sqlite) – wird vom Monitor (bnutt.li/monitor.php) gelesen."""
    snap = usage_snapshot(cfg, now)
    path = usage_json_path()
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return snap
