#!/usr/bin/env python3
"""Sugarbag: a small issue tracker with a Kanban board, for one person or a small team. Issue tracking without the sting.

Runs as a long-lived web server (its own container, or `python3 sugarbag.py`). Serves the pages in static/ and a
JSON API under /api. Keeps everything in one SQLite file. Also has commands to add users and tokens: see --help.

Settings, all from the environment:
  SUGARBAG_DB             the database file (default ./sugarbag.db)
  SUGARBAG_BIND           address to listen on (default 127.0.0.1)
  SUGARBAG_PORT           port (default 8094)
  SUGARBAG_NAME           the name shown on the page (default Sugarbag)
  SUGARBAG_SECURE_COOKIE  set to 1 when served over https

Standard library only. Checks: python3 sugarbag_test.py
"""
import argparse
import getpass
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from datetime import date
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VERSION = "0.1.0"
HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PAGES = {"/": "index.html", "/app.js": "app.js", "/md.js": "md.js", "/style.css": "style.css"}

TYPES = ("epic", "story", "task", "bug", "subtask")
PRIORITIES = ("highest", "high", "medium", "low", "lowest")
ROLES = ("admin", "member", "viewer")
DEFAULT_STATUSES = (("ideas", "Ideas", 0), ("todo", "To do", 0), ("selected", "Selected for development", 0),
                    ("in_progress", "In progress", 0), ("blocked", "Blocked", 0), ("review", "Review", 0), ("done", "Done", 1))
MAX_BODY = 1_000_000
SESSION_DAYS = 30
KEY = re.compile(r"^([A-Z][A-Z0-9]{1,9})-(\d+)$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, role TEXT NOT NULL,
  password TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users ON DELETE CASCADE, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tokens (id INTEGER PRIMARY KEY, hash TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
  label TEXT NOT NULL, created INTEGER NOT NULL, last_used INTEGER);
CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, name TEXT NOT NULL, next_num INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS statuses (project_id INTEGER NOT NULL REFERENCES projects ON DELETE CASCADE, slug TEXT NOT NULL, name TEXT NOT NULL,
  position INTEGER NOT NULL, is_done INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (project_id, slug));
CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects ON DELETE CASCADE, num INTEGER NOT NULL,
  type TEXT NOT NULL, parent_id INTEGER REFERENCES items ON DELETE CASCADE, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'medium', assignee_id INTEGER REFERENCES users ON DELETE SET NULL,
  labels TEXT NOT NULL DEFAULT '[]', position REAL NOT NULL, start_date TEXT, due_date TEXT, ref TEXT,
  created_by INTEGER REFERENCES users ON DELETE SET NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL,
  UNIQUE (project_id, num), UNIQUE (project_id, ref));
CREATE INDEX IF NOT EXISTS items_board ON items (project_id, status, position);
CREATE INDEX IF NOT EXISTS items_parent ON items (parent_id);
CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items ON DELETE CASCADE,
  user_id INTEGER REFERENCES users ON DELETE SET NULL, body TEXT NOT NULL, at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items ON DELETE CASCADE,
  user_id INTEGER REFERENCES users ON DELETE SET NULL, field TEXT NOT NULL, old TEXT, new TEXT, at INTEGER NOT NULL);
"""

log = logging.getLogger("sugarbag")
failed_logins = {}
failed_lock = threading.Lock()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def db_path():
    return os.environ.get("SUGARBAG_DB") or str(HERE / "sugarbag.db")


def connect():
    # isolation_level None: transactions are opened by hand, so a new issue number can be taken with BEGIN IMMEDIATE.
    conn = sqlite3.connect(db_path(), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    conn.close()


class tx:
    """A write transaction that takes its lock at the start, so two writers can't read the same next number."""
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, kind, *_):
        self.conn.execute("ROLLBACK" if kind else "COMMIT")


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def hash_password(password):
    salt = secrets.token_bytes(16)
    return salt.hex() + "$" + hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


def check_password(password, stored):
    salt, _, digest = stored.partition("$")
    try:
        attempt = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    except ValueError:
        return False
    return hmac.compare_digest(attempt, digest)


def too_many_failures(ip):
    # shortcut: counted in memory per address, so a restart clears it. Move to the database if this ever faces the internet.
    now = time.time()
    with failed_lock:
        recent = [t for t in failed_logins.get(ip, []) if now - t < 600]
        failed_logins[ip] = recent
        return len(recent) >= 10


def note_failure(ip):
    with failed_lock:
        failed_logins.setdefault(ip, []).append(time.time())


# --- Rules ---

def text(body, field, limit, required=False):
    value = body.get(field)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, f"{field} must be text")
    value = value.strip()
    if required and not value:
        raise ApiError(400, f"{field} is required")
    if len(value) > limit:
        raise ApiError(400, f"{field} is too long (limit {limit})")
    return value


def clean_date(value, field):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ApiError(400, f"{field} must be a date like 2026-11-04") from None


def clean_labels(value):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ApiError(400, "labels must be a list of text")
    labels = sorted({v.strip().lower() for v in value if v.strip()})
    if len(labels) > 20 or any(len(v) > 40 for v in labels):
        raise ApiError(400, "too many labels, or a label is too long")
    return labels


def check_parent(item_type, parent_type):
    """Epic > story, task or bug > sub-task. Stories and tasks sit level, so nobody has to decide which contains which."""
    if item_type == "epic" and parent_type:
        raise ApiError(400, "an epic can't have a parent")
    if item_type == "subtask" and parent_type not in ("story", "task", "bug"):
        raise ApiError(400, "a sub-task needs a story, task or bug as its parent")
    if item_type in ("story", "task", "bug") and parent_type not in (None, "epic"):
        raise ApiError(400, f"a {item_type}'s parent must be an epic")


def check_children(conn, item_id, new_type):
    kinds = {r["type"] for r in conn.execute("SELECT DISTINCT type FROM items WHERE parent_id = ?", (item_id,))}
    for kind in kinds:
        check_parent(kind, new_type)


ITEM_SELECT = """
SELECT i.*, p.key AS project_key, u.name AS assignee, c.name AS creator, pi.num AS parent_num, pi.title AS parent_title, pi.type AS parent_type,
  (SELECT COUNT(*) FROM items k WHERE k.parent_id = i.id) AS children,
  (SELECT COUNT(*) FROM items k JOIN statuses s ON s.project_id = k.project_id AND s.slug = k.status
    WHERE k.parent_id = i.id AND s.is_done = 1) AS children_done
FROM items i JOIN projects p ON p.id = i.project_id
LEFT JOIN users u ON u.id = i.assignee_id LEFT JOIN users c ON c.id = i.created_by LEFT JOIN items pi ON pi.id = i.parent_id
"""


def item_json(row):
    key = row["project_key"]
    return {"key": f"{key}-{row['num']}", "project": key, "type": row["type"], "title": row["title"], "body": row["body"],
            "status": row["status"], "priority": row["priority"], "assignee": row["assignee"], "labels": json.loads(row["labels"]),
            "parent": f"{key}-{row['parent_num']}" if row["parent_num"] else None, "parent_title": row["parent_title"], "parent_type": row["parent_type"],
            "start": row["start_date"], "due": row["due_date"], "ref": row["ref"], "position": row["position"], "children": row["children"],
            "children_done": row["children_done"], "created_by": row["creator"], "created": row["created"], "updated": row["updated"]}


def find_project(conn, key):
    row = conn.execute("SELECT * FROM projects WHERE key = ?", (key,)).fetchone()
    if not row:
        raise ApiError(404, f"no project {key}")
    return row


def find_item(conn, key):
    m = KEY.match(key or "")
    row = m and conn.execute("SELECT i.* FROM items i JOIN projects p ON p.id = i.project_id WHERE p.key = ? AND i.num = ?", (m[1], int(m[2]))).fetchone()
    if not row:
        raise ApiError(404, f"no item {key}")
    return row


def load_item(conn, item_id):
    return item_json(conn.execute(ITEM_SELECT + " WHERE i.id = ?", (item_id,)).fetchone())


def statuses_of(conn, project_id):
    return [dict(r) for r in conn.execute("SELECT slug, name, position, is_done FROM statuses WHERE project_id = ? ORDER BY position", (project_id,))]


def check_status(conn, project_id, slug):
    if not conn.execute("SELECT 1 FROM statuses WHERE project_id = ? AND slug = ?", (project_id, slug)).fetchone():
        raise ApiError(400, f"no status {slug} in this project")


def find_assignee(conn, name):
    if not name:
        return None
    row = conn.execute("SELECT id FROM users WHERE name = ? AND active = 1", (name,)).fetchone()
    if not row:
        raise ApiError(400, f"no user {name}")
    return row["id"]


def record(conn, item_id, user_id, field, old, new):
    conn.execute("INSERT INTO activity (item_id, user_id, field, old, new, at) VALUES (?,?,?,?,?,?)",
                 (item_id, user_id, field, None if old is None else str(old), None if new is None else str(new), int(time.time())))


def bottom_of(conn, project_id, status):
    row = conn.execute("SELECT MAX(position) AS top FROM items WHERE project_id = ? AND status = ?", (project_id, status)).fetchone()
    return (row["top"] or 0) + 1


def position_before(conn, project_id, status, before_key):
    """A position just above before_key, or the bottom of the column. Halves the gap instead of renumbering every card."""
    if not before_key:
        return bottom_of(conn, project_id, status)
    target = find_item(conn, before_key)
    if target["project_id"] != project_id or target["status"] != status:
        raise ApiError(400, "before must be in the same column")
    for attempt in (1, 2):
        at = conn.execute("SELECT position FROM items WHERE id = ?", (target["id"],)).fetchone()["position"]
        above = conn.execute("SELECT MAX(position) AS p FROM items WHERE project_id = ? AND status = ? AND position < ?",
                             (project_id, status, at)).fetchone()["p"]
        if above is None:
            above = at - 2
        middle = (at + above) / 2
        if above < middle < at:
            return middle
        # About 50 moves into one gap runs out of decimal places, so space the whole column out and try again.
        ids = conn.execute("SELECT id FROM items WHERE project_id = ? AND status = ? ORDER BY position, id", (project_id, status)).fetchall()
        for n, r in enumerate(ids, 1):
            conn.execute("UPDATE items SET position = ? WHERE id = ?", (float(n), r["id"]))
    raise ApiError(500, "couldn't place the card")


# --- The API ---

ROUTES = []


def route(method, pattern, role="viewer"):
    """role is the least a user needs: viewer, member or admin. None means no login needed."""
    def add(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), role, fn))
        return fn
    return add


def public_user(row):
    return {"name": row["name"], "role": row["role"], "active": bool(row["active"])}


@route("GET", "/health", None)
def health(ctx):
    ctx.conn.execute("SELECT 1 FROM projects LIMIT 1")
    return {"ok": True}


@route("GET", "/info", None)
def info(ctx):
    return {"name": os.environ.get("SUGARBAG_NAME", "Sugarbag"), "version": VERSION}


@route("POST", "/api/login", None)
def login(ctx):
    if too_many_failures(ctx.ip):
        raise ApiError(429, "too many failed attempts: wait ten minutes")
    name, password = text(ctx.body, "name", 80, True), ctx.body.get("password")
    row = ctx.conn.execute("SELECT * FROM users WHERE name = ? AND active = 1", (name,)).fetchone()
    # A wrong name costs the same time as a wrong password, so the delay doesn't reveal which names exist.
    good = check_password(str(password), row["password"] if row else "00$00")
    if not row or not good:
        note_failure(ctx.ip)
        log.warning("failed login for %r from %s", name[:80], ctx.ip)
        raise ApiError(401, "wrong name or password")
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with tx(ctx.conn) as c:
        c.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        c.execute("INSERT INTO sessions VALUES (?,?,?)", (sha(token), row["id"], now + SESSION_DAYS * 86400))
    ctx.set_cookie(token, SESSION_DAYS * 86400)
    log.info("login: %s from %s", name, ctx.ip)
    return public_user(row)


@route("POST", "/api/logout")
def logout(ctx):
    if ctx.session:
        ctx.conn.execute("DELETE FROM sessions WHERE hash = ?", (sha(ctx.session),))
    ctx.set_cookie("", 0)
    return {"ok": True}


@route("GET", "/api/me")
def me(ctx):
    return public_user(ctx.user)


@route("POST", "/api/password")
def change_password(ctx):
    if not check_password(str(ctx.body.get("old")), ctx.user["password"]):
        raise ApiError(403, "the old password is wrong")
    new = ctx.body.get("new")
    if not isinstance(new, str) or len(new) < 8:
        raise ApiError(400, "a password needs at least 8 characters")
    ctx.conn.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(new), ctx.user["id"]))
    return {"ok": True}


@route("GET", "/api/users")
def list_users(ctx):
    # Every member can see names, to assign work. Only admins change them.
    return [public_user(r) for r in ctx.conn.execute("SELECT * FROM users ORDER BY name")]


@route("POST", "/api/users", "admin")
def add_user_route(ctx):
    name, role = text(ctx.body, "name", 80, True), ctx.body.get("role", "member")
    password = ctx.body.get("password")
    if role not in ROLES:
        raise ApiError(400, "role must be admin, member or viewer")
    if not re.match(r"^[\w.-]+$", name):
        raise ApiError(400, "a name can only have letters, numbers, dots and dashes")
    if not isinstance(password, str) or len(password) < 8:
        raise ApiError(400, "a password needs at least 8 characters")
    try:
        ctx.conn.execute("INSERT INTO users (name, role, password, created) VALUES (?,?,?,?)", (name, role, hash_password(password), int(time.time())))
    except sqlite3.IntegrityError:
        raise ApiError(409, "that name is taken") from None
    log.info("user added: %s (%s) by %s", name, role, ctx.user["name"])
    return {"name": name, "role": role, "active": True}


@route("PATCH", "/api/users/([^/]+)", "admin")
def edit_user(ctx, name):
    row = ctx.conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
    if not row:
        raise ApiError(404, "no such user")
    role, active = ctx.body.get("role", row["role"]), ctx.body.get("active", bool(row["active"]))
    if role not in ROLES or not isinstance(active, bool):
        raise ApiError(400, "bad role or active")
    with tx(ctx.conn) as c:
        others = c.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active = 1 AND id != ?", (row["id"],)).fetchone()["n"]
        if not others and (role != "admin" or not active) and row["role"] == "admin":
            raise ApiError(400, "that would leave nobody who can manage users")
        c.execute("UPDATE users SET role = ?, active = ? WHERE id = ?", (role, int(active), row["id"]))
        if not active:  # a switched-off user's logins and tokens must stop now, not when they expire
            c.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
            c.execute("DELETE FROM tokens WHERE user_id = ?", (row["id"],))
    log.info("user changed: %s role=%s active=%s by %s", name, role, active, ctx.user["name"])
    return {"name": name, "role": role, "active": active}


@route("GET", "/api/tokens")
def list_tokens(ctx):
    rows = ctx.conn.execute("SELECT id, label, created, last_used FROM tokens WHERE user_id = ? ORDER BY id", (ctx.user["id"],))
    return [dict(r) for r in rows]


@route("POST", "/api/tokens", "member")
def add_token(ctx):
    label = text(ctx.body, "label", 80, True)
    token = "sugarbag_" + secrets.token_urlsafe(32)
    ctx.conn.execute("INSERT INTO tokens (hash, user_id, label, created) VALUES (?,?,?,?)", (sha(token), ctx.user["id"], label, int(time.time())))
    return {"token": token, "label": label}


@route("DELETE", "/api/tokens/(\\d+)")
def del_token(ctx, token_id):
    if not ctx.conn.execute("DELETE FROM tokens WHERE id = ? AND user_id = ?", (int(token_id), ctx.user["id"])).rowcount:
        raise ApiError(404, "no such token")
    return {"ok": True}


@route("GET", "/api/projects")
def list_projects(ctx):
    rows = ctx.conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
    return [{"key": r["key"], "name": r["name"], "statuses": statuses_of(ctx.conn, r["id"])} for r in rows]


@route("POST", "/api/projects", "admin")
def add_project(ctx):
    key, name = text(ctx.body, "key", 10, True).upper(), text(ctx.body, "name", 80, True)
    if not re.match(r"^[A-Z][A-Z0-9]{1,9}$", key):
        raise ApiError(400, "a project key is 2 to 10 letters or numbers, starting with a letter")
    with tx(ctx.conn) as c:
        try:
            pid = c.execute("INSERT INTO projects (key, name) VALUES (?,?)", (key, name)).lastrowid
        except sqlite3.IntegrityError:
            raise ApiError(409, "that key is taken") from None
        for pos, (slug, label, done) in enumerate(DEFAULT_STATUSES):
            c.execute("INSERT INTO statuses VALUES (?,?,?,?,?)", (pid, slug, label, pos, done))
    return {"key": key, "name": name, "statuses": statuses_of(ctx.conn, pid)}


@route("PUT", "/api/projects/([^/]+)/columns", "admin")
def set_columns(ctx, key):
    """Replaces a project's columns with this list, in this order, all at once, so a half-done edit can't leave a broken board."""
    columns, moves = ctx.body.get("columns"), ctx.body.get("move") or {}
    if not isinstance(columns, list) or not 1 <= len(columns) <= 12 or not isinstance(moves, dict):
        raise ApiError(400, "send between 1 and 12 columns")
    with tx(ctx.conn) as c:
        project = find_project(c, key)
        old = {s["slug"]: s for s in statuses_of(c, project["id"])}
        rows, names = [], set()
        for col in columns:
            if not isinstance(col, dict):
                raise ApiError(400, "each column needs a name")
            name, slug = text(col, "name", 40, True), col.get("slug")
            if name.lower() in names:
                raise ApiError(400, f"two columns are called {name}")
            names.add(name.lower())
            if slug is not None and (not isinstance(slug, str) or slug not in old):
                raise ApiError(400, f"no column {slug} in this project")
            if slug is not None and slug in [r[0] for r in rows]:
                raise ApiError(400, f"column {slug} is listed twice")
            rows.append([slug, name, 1 if col.get("is_done") else 0])
        kept = {r[0] for r in rows if r[0]}
        for r in rows:  # a new column's slug comes from its name, kept unique, and never changes after that
            if not r[0]:
                base = re.sub(r"[^a-z0-9]+", "_", r[1].lower()).strip("_") or "column"
                r[0], n = base, 2
                while r[0] in old or r[0] in kept:
                    r[0], n = f"{base}_{n}", n + 1
                kept.add(r[0])
        for slug in set(old) - kept:
            count = c.execute("SELECT COUNT(*) AS n FROM items WHERE project_id = ? AND status = ?", (project["id"], slug)).fetchone()["n"]
            target = moves.get(slug)
            if count and target not in kept:
                raise ApiError(400, f"{old[slug]['name']} has {count} items: say which column they move to")
        c.execute("DELETE FROM statuses WHERE project_id = ?", (project["id"],))
        for pos, (slug, name, done) in enumerate(rows):
            c.execute("INSERT INTO statuses VALUES (?,?,?,?,?)", (project["id"], slug, name, pos, done))
        for slug in set(old) - kept:
            items = c.execute("SELECT id FROM items WHERE project_id = ? AND status = ? ORDER BY position", (project["id"], slug)).fetchall()
            for row in items:
                record(c, row["id"], ctx.user["id"], "status", slug, moves[slug])
                c.execute("UPDATE items SET status = ?, position = ? WHERE id = ?", (moves[slug], bottom_of(c, project["id"], moves[slug]), row["id"]))
        log.info("columns changed in %s by %s", key, ctx.user["name"])
        return {"key": project["key"], "name": project["name"], "statuses": statuses_of(c, project["id"])}


@route("GET", "/api/items")
def list_items(ctx):
    project = find_project(ctx.conn, ctx.query.get("project", ""))
    where, args = ["i.project_id = ?"], [project["id"]]
    for field, column in (("status", "i.status"), ("type", "i.type"), ("ref", "i.ref"), ("assignee", "u.name")):
        if field in ctx.query:
            where.append(f"{column} = ?")
            args.append(ctx.query[field])
    if "parent" in ctx.query:
        where.append("i.parent_id = ?")
        args.append(find_item(ctx.conn, ctx.query["parent"])["id"])
    if "q" in ctx.query:
        where.append("(i.title LIKE ? ESCAPE '\\' OR i.body LIKE ? ESCAPE '\\')")
        like = "%" + re.sub(r"([\\%_])", r"\\\1", ctx.query["q"]) + "%"
        args += [like, like]
    # shortcut: no paging, fine for thousands of items in one small team's project, add limit and offset past that.
    rows = ctx.conn.execute(ITEM_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY i.position", args).fetchall()
    items = [item_json(r) for r in rows]
    if "label" in ctx.query:
        items = [i for i in items if ctx.query["label"] in i["labels"]]
    return items


@route("POST", "/api/items", "member")
def add_item(ctx):
    b = ctx.body
    title, body = text(b, "title", 300, True), text(b, "body", 100_000)
    kind, priority = b.get("type", "task"), b.get("priority", "medium")
    if kind not in TYPES or priority not in PRIORITIES:
        raise ApiError(400, "bad type or priority")
    labels, start, due = clean_labels(b.get("labels")), clean_date(b.get("start"), "start"), clean_date(b.get("due"), "due")
    ref = text(b, "ref", 200) or None
    now = int(time.time())
    with tx(ctx.conn) as c:
        project = find_project(c, text(b, "project", 10, True).upper())
        status = b.get("status") or statuses_of(c, project["id"])[0]["slug"]
        check_status(c, project["id"], status)
        parent = find_item(c, b["parent"]) if b.get("parent") else None
        if parent is not None and parent["project_id"] != project["id"]:
            raise ApiError(400, "the parent is in another project")
        check_parent(kind, parent["type"] if parent is not None else None)
        num = project["next_num"]
        c.execute("UPDATE projects SET next_num = ? WHERE id = ?", (num + 1, project["id"]))
        try:
            item_id = c.execute("""INSERT INTO items (project_id, num, type, parent_id, title, body, status, priority, assignee_id, labels, position,
                                   start_date, due_date, ref, created_by, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (project["id"], num, kind, parent["id"] if parent is not None else None, title, body, status, priority,
                                 find_assignee(c, b.get("assignee")), json.dumps(labels), bottom_of(c, project["id"], status),
                                 start, due, ref, ctx.user["id"], now, now)).lastrowid
        except sqlite3.IntegrityError:
            raise ApiError(409, f"an item with ref {ref} already exists") from None
    ctx.status = 201
    return load_item(ctx.conn, item_id)


@route("GET", "/api/items/([^/]+)")
def get_item(ctx, key):
    row = find_item(ctx.conn, key)
    out = load_item(ctx.conn, row["id"])
    out["subitems"] = [item_json(r) for r in ctx.conn.execute(ITEM_SELECT + " WHERE i.parent_id = ? ORDER BY i.num", (row["id"],))]
    out["comments"] = [dict(r) for r in ctx.conn.execute(
        "SELECT c.id, u.name AS user, c.body, c.at FROM comments c LEFT JOIN users u ON u.id = c.user_id WHERE c.item_id = ? ORDER BY c.id", (row["id"],))]
    out["activity"] = [dict(r) for r in ctx.conn.execute(
        "SELECT u.name AS user, a.field, a.old, a.new, a.at FROM activity a LEFT JOIN users u ON u.id = a.user_id WHERE a.item_id = ? ORDER BY a.id DESC LIMIT 100", (row["id"],))]
    return out


@route("PATCH", "/api/items/([^/]+)", "member")
def edit_item(ctx, key):
    b = ctx.body
    with tx(ctx.conn) as c:
        row = find_item(c, key)
        new, changed = {}, []
        if "title" in b:
            new["title"] = text(b, "title", 300, True)
        if "body" in b:
            new["body"] = text(b, "body", 100_000)
        if "priority" in b:
            if b["priority"] not in PRIORITIES:
                raise ApiError(400, "bad priority")
            new["priority"] = b["priority"]
        if "labels" in b:
            new["labels"] = json.dumps(clean_labels(b["labels"]))
        if "start" in b:
            new["start_date"] = clean_date(b["start"], "start")
        if "due" in b:
            new["due_date"] = clean_date(b["due"], "due")
        if "assignee" in b:
            new["assignee_id"] = find_assignee(c, b["assignee"])
        if "status" in b and b["status"] != row["status"]:
            check_status(c, row["project_id"], b["status"])
            new["status"] = b["status"]
            new["position"] = bottom_of(c, row["project_id"], b["status"])
        kind = b.get("type", row["type"])
        if kind not in TYPES:
            raise ApiError(400, "bad type")
        parent_id = row["parent_id"]
        if "parent" in b:
            parent = find_item(c, b["parent"]) if b["parent"] else None
            if parent is not None and parent["project_id"] != row["project_id"]:
                raise ApiError(400, "the parent is in another project")
            parent_id = parent["id"] if parent is not None else None
            if parent_id == row["id"]:
                raise ApiError(400, "an item can't be its own parent")
        if kind != row["type"] or parent_id != row["parent_id"]:
            parent_row = c.execute("SELECT type FROM items WHERE id = ?", (parent_id,)).fetchone() if parent_id else None
            check_parent(kind, parent_row["type"] if parent_row else None)
            check_children(c, row["id"], kind)
            new["type"], new["parent_id"] = kind, parent_id
        for column, value in new.items():
            if value != row[column]:
                changed.append(column)
                if column != "position":
                    record(c, row["id"], ctx.user["id"], column, row[column] if column != "body" else None, value if column != "body" else None)
        if changed:
            sets = ", ".join(f"{col} = ?" for col in changed)
            c.execute(f"UPDATE items SET {sets}, updated = ? WHERE id = ?", [new[col] for col in changed] + [int(time.time()), row["id"]])
    return load_item(ctx.conn, row["id"])


@route("POST", "/api/items/([^/]+)/move", "member")
def move_item(ctx, key):
    with tx(ctx.conn) as c:
        row = find_item(c, key)
        status = ctx.body.get("status", row["status"])
        check_status(c, row["project_id"], status)
        position = position_before(c, row["project_id"], status, ctx.body.get("before"))
        if status != row["status"]:
            record(c, row["id"], ctx.user["id"], "status", row["status"], status)
        c.execute("UPDATE items SET status = ?, position = ?, updated = ? WHERE id = ?", (status, position, int(time.time()), row["id"]))
    return load_item(ctx.conn, row["id"])


@route("DELETE", "/api/items/([^/]+)", "member")
def del_item(ctx, key):
    with tx(ctx.conn) as c:
        row = find_item(c, key)
        # Deleting takes everything under it, so a member must have made all of it. Otherwise moving someone's task under your epic would delete it.
        others = c.execute("""WITH RECURSIVE tree(id, created_by) AS (SELECT id, created_by FROM items WHERE id = ?
                              UNION ALL SELECT i.id, i.created_by FROM items i JOIN tree t ON i.parent_id = t.id)
                              SELECT COUNT(*) AS n FROM tree WHERE created_by IS NOT ?""", (row["id"], ctx.user["id"])).fetchone()["n"]
        if ctx.user["role"] != "admin" and others:
            raise ApiError(403, "only an admin can delete something with other people's work in it")
        c.execute("DELETE FROM items WHERE id = ?", (row["id"],))
    log.info("item deleted: %s by %s", key, ctx.user["name"])
    return {"ok": True}


@route("POST", "/api/items/([^/]+)/comments", "member")
def add_comment(ctx, key):
    row = find_item(ctx.conn, key)
    body = text(ctx.body, "body", 20_000, True)
    now = int(time.time())
    with tx(ctx.conn) as c:
        cid = c.execute("INSERT INTO comments (item_id, user_id, body, at) VALUES (?,?,?,?)", (row["id"], ctx.user["id"], body, now)).lastrowid
        c.execute("UPDATE items SET updated = ? WHERE id = ?", (now, row["id"]))
    ctx.status = 201
    return {"id": cid, "user": ctx.user["name"], "body": body, "at": now}


@route("GET", "/api/export", "admin")
def export(ctx):
    """Everything except passwords and tokens, so nobody is stuck with Sugarbag."""
    out = {"version": VERSION, "users": [public_user(r) for r in ctx.conn.execute("SELECT * FROM users")], "projects": list_projects(ctx)}
    out["items"] = [item_json(r) for r in ctx.conn.execute(ITEM_SELECT + " ORDER BY i.project_id, i.num")]
    out["comments"] = [dict(r) for r in ctx.conn.execute(
        "SELECT p.key || '-' || i.num AS item, u.name AS user, c.body, c.at FROM comments c JOIN items i ON i.id = c.item_id JOIN projects p ON p.id = i.project_id LEFT JOIN users u ON u.id = c.user_id ORDER BY c.id")]
    return out


# --- The web server ---

class Ctx:
    """What a route needs to know about this request."""
    def __init__(self, handler, conn, query, body):
        self.handler, self.conn, self.query, self.body = handler, conn, query, body
        self.ip, self.user, self.session, self.status, self.cookie = handler.client_address[0], None, None, 200, None

    def set_cookie(self, value, age):
        secure = "; Secure" if os.environ.get("SUGARBAG_SECURE_COOKIE") == "1" else ""
        self.cookie = f"sugarbag_session={value}; Path=/; Max-Age={age}; HttpOnly; SameSite=Strict{secure}"


def role_allows(role, needed):
    return ROLES.index(role) <= ROLES.index(needed)


class Handler(BaseHTTPRequestHandler):
    server_version = "Sugarbag"
    sys_version = ""

    def log_message(self, *args):
        pass  # every request would drown the log; writes and logins are logged where they happen

    def send_bytes(self, status, data, kind, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-cache")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_json(self, status, value, cookie=None):
        self.send_bytes(status, json.dumps(value).encode(), "application/json", cookie)

    def authenticate(self, ctx):
        auth = self.headers.get("Authorization", "")
        now = int(time.time())
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            row = ctx.conn.execute("SELECT u.* FROM tokens t JOIN users u ON u.id = t.user_id WHERE t.hash = ? AND u.active = 1", (sha(token),)).fetchone()
            if row:
                ctx.conn.execute("UPDATE tokens SET last_used = ? WHERE hash = ?", (now, sha(token)))
            return row
        cookies = SimpleCookie(self.headers.get("Cookie", ""))
        if "sugarbag_session" not in cookies:
            return None
        ctx.session = cookies["sugarbag_session"].value
        return ctx.conn.execute("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.hash = ? AND s.expires > ? AND u.active = 1",
                                (sha(ctx.session), now)).fetchone()

    def same_site(self):
        """Stops another website's page using a signed-in browser. Tokens aren't sent automatically, so they skip this."""
        if self.headers.get("Authorization", "").startswith("Bearer "):
            return True
        if "application/json" not in self.headers.get("Content-Type", ""):
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            return False
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    def handle_request(self):
        url = urlparse(self.path)
        if self.command in ("GET", "HEAD") and url.path in PAGES:
            name = PAGES[url.path]
            return self.send_bytes(200, (STATIC / name).read_bytes(), mimetypes.guess_type(name)[0] or "text/plain")
        for method, pattern, role, fn in ROUTES:
            m = pattern.match(url.path)
            if m and method == ("GET" if self.command == "HEAD" else self.command):
                break
        else:
            return self.send_json(404, {"error": "Not found."})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self.close_connection = True
            return self.send_json(413, {"error": "That's too big."})
        raw = self.rfile.read(length) if length else b""
        if self.command not in ("GET", "HEAD") and not self.same_site():
            return self.send_json(403, {"error": "That request came from another site."})
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            return self.send_json(400, {"error": "That isn't valid JSON."})
        if not isinstance(body, dict):
            return self.send_json(400, {"error": "Send a JSON object."})
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        conn = connect()
        try:
            ctx = Ctx(self, conn, query, body)
            if role is not None or url.path == "/api/logout":
                ctx.user = self.authenticate(ctx)
                if not ctx.user:
                    raise ApiError(401, "Please sign in.")
                if not role_allows(ctx.user["role"], role):
                    raise ApiError(403, "Your role can't do that.")
            result = fn(ctx, *m.groups())
            self.send_json(ctx.status, result, ctx.cookie)
        except ApiError as e:
            self.send_json(e.status, {"error": e.message})
        finally:
            conn.close()

    def guarded(self):
        try:
            self.handle_request()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log.exception("%s %s failed", self.command, urlparse(self.path).path)
            self.send_json(500, {"error": "Something went wrong on the server."})

    do_GET = do_HEAD = do_POST = do_PATCH = do_PUT = do_DELETE = guarded


def add_user(name, role, password):
    init_db()
    conn = connect()
    conn.execute("INSERT INTO users (name, role, password, created) VALUES (?,?,?,?)", (name, role, hash_password(password), int(time.time())))
    conn.close()


def serve():
    init_db()
    bind, port = os.environ.get("SUGARBAG_BIND", "127.0.0.1"), int(os.environ.get("SUGARBAG_PORT", "8094"))
    server = ThreadingHTTPServer((bind, port), Handler)
    log.info("listening on %s:%d, data in %s", bind, port, db_path())
    server.serve_forever()


def main():
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sugarbag: a small issue tracker.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the web server (the default)")
    user = sub.add_parser("adduser", help="add a user; asks for the password")
    user.add_argument("name")
    user.add_argument("--role", choices=ROLES, default="admin")
    token = sub.add_parser("token", help="make an API token for a user and print it once")
    token.add_argument("name")
    token.add_argument("label")
    args = parser.parse_args()
    if args.command == "adduser":
        password = getpass.getpass("Password: ")
        if len(password) < 8:
            sys.exit("A password needs at least 8 characters.")
        try:
            add_user(args.name, args.role, password)
        except sqlite3.IntegrityError:
            sys.exit("That name is taken.")
        print(f"Added {args.name} ({args.role}).")
    elif args.command == "token":
        init_db()
        conn = connect()
        row = conn.execute("SELECT id FROM users WHERE name = ?", (args.name,)).fetchone()
        if not row:
            sys.exit("No such user.")
        value = "sugarbag_" + secrets.token_urlsafe(32)
        conn.execute("INSERT INTO tokens (hash, user_id, label, created) VALUES (?,?,?,?)", (sha(value), row["id"], args.label, int(time.time())))
        print(value)
    else:
        serve()


if __name__ == "__main__":
    main()
