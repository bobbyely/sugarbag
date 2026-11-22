#!/usr/bin/env python3
"""Checks Sugarbag's API against a real server on a spare port with a throwaway database. Run by hand or by GitHub.

  python3 services/sugarbag/sugarbag_test.py

Reads and writes only a temporary folder. Takes a few seconds, because passwords are slow to hash on purpose.
"""
import argparse
import json
import os
import sqlite3
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

tmp = tempfile.TemporaryDirectory()
os.environ["SUGARBAG_DB"] = os.path.join(tmp.name, "t.db")
import sugarbag  # noqa: E402

sugarbag.init_db()
sugarbag.add_user("ann", "admin", "password-1")
sugarbag.add_user("mem", "member", "password-2")
sugarbag.add_user("view", "viewer", "password-3")
server = ThreadingHTTPServer(("127.0.0.1", 0), sugarbag.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"


def call(method, path, body=None, token=None, cookie=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None or method != "GET" else {}
    if token:
        h["Authorization"] = "Bearer " + token
    if cookie:
        h["Cookie"] = cookie
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"null"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null"), e.headers


def sign_in(name, password):
    status, _, headers = call("POST", "/api/login", {"name": name, "password": password})
    assert status == 200, status
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    return cookie.split(";")[0]


def ok(result, status=200):
    assert result[0] == status, result[:2]
    return result[1]


# Open pages and signing in.
assert ok(call("GET", "/health"))["ok"]
assert call("GET", "/api/items?project=AB")[0] == 401
assert call("POST", "/api/login", {"name": "ann", "password": "nope"})[0] == 401
assert call("POST", "/api/login", {"name": "ghost", "password": "nope"})[0] == 401
ann, mem, view = sign_in("ann", "password-1"), sign_in("mem", "password-2"), sign_in("view", "password-3")
assert ok(call("GET", "/api/me", cookie=ann))["role"] == "admin"

# Roles.
assert call("POST", "/api/projects", {"key": "AB", "name": "A"}, cookie=mem)[0] == 403
project = ok(call("POST", "/api/projects", {"key": "ab", "name": "Demo"}, cookie=ann))
assert project["key"] == "AB" and [s["slug"] for s in project["statuses"]][0] == "ideas" and project["statuses"][-1]["is_done"] == 1
assert call("POST", "/api/projects", {"key": "AB", "name": "Again"}, cookie=ann)[0] == 409
assert call("POST", "/api/items", {"project": "AB", "title": "x"}, cookie=view)[0] == 403
assert call("POST", "/api/users", {"name": "n", "password": "password-9"}, cookie=mem)[0] == 403

# A cross-site request from a signed-in browser is refused, whichever way it shows up.
assert call("POST", "/api/items", {"project": "AB", "title": "x"}, cookie=mem, headers={"Origin": "https://evil.example"})[0] == 403
assert call("POST", "/api/items", {"project": "AB", "title": "x"}, cookie=mem, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
assert call("POST", "/api/items", {"project": "AB", "title": "x"}, cookie=mem, headers={"Content-Type": "text/plain"})[0] == 403

# The hierarchy: epic > story, task or bug > sub-task.
epic = ok(call("POST", "/api/items", {"project": "AB", "type": "epic", "title": "Stage 1"}, cookie=mem), 201)
assert epic["key"] == "AB-1" and epic["status"] == "ideas"
story = ok(call("POST", "/api/items", {"project": "AB", "type": "story", "title": "Board <b>", "parent": "AB-1", "status": "selected", "labels": ["UI", "ui"], "assignee": "mem"}, cookie=mem), 201)
assert story["key"] == "AB-2" and story["parent"] == "AB-1" and story["labels"] == ["ui"] and story["assignee"] == "mem"
sub = ok(call("POST", "/api/items", {"project": "AB", "type": "subtask", "title": "Drag", "parent": "AB-2"}, cookie=mem), 201)
assert call("POST", "/api/items", {"project": "AB", "type": "subtask", "title": "bad"}, cookie=mem)[0] == 400
assert call("POST", "/api/items", {"project": "AB", "type": "subtask", "title": "bad", "parent": "AB-1"}, cookie=mem)[0] == 400
assert call("POST", "/api/items", {"project": "AB", "type": "epic", "title": "bad", "parent": "AB-1"}, cookie=mem)[0] == 400
assert call("POST", "/api/items", {"project": "AB", "type": "story", "title": "bad", "parent": sub["key"]}, cookie=mem)[0] == 400
assert call("PATCH", "/api/items/AB-2", {"type": "epic", "parent": None}, cookie=mem)[0] == 400  # its sub-task would be orphaned
assert call("PATCH", "/api/items/AB-1", {"type": "task"}, cookie=mem)[0] == 400  # it has a story under it

# Bad input.
assert call("PATCH", "/api/items/AB-1", {"type": "task", "parent": "AB-1"}, cookie=mem)[0] == 400  # its own parent
empty = ok(call("POST", "/api/items", {"project": "AB", "type": "epic", "title": "empty"}, cookie=mem), 201)["key"]
assert call("PATCH", f"/api/items/{empty}", {"type": "task", "parent": empty}, cookie=mem)[0] == 400
ok(call("DELETE", f"/api/items/{empty}", cookie=mem))
assert call("POST", "/api/items", {"project": "AB", "title": "  "}, cookie=mem)[0] == 400
assert call("POST", "/api/items", {"project": "AB", "title": "x", "status": "nope"}, cookie=mem)[0] == 400
assert call("POST", "/api/items", {"project": "AB", "title": "x", "due": "soon"}, cookie=mem)[0] == 400
assert call("POST", "/api/items", {"project": "AB", "title": "x", "assignee": "ghost"}, cookie=mem)[0] == 400
assert call("GET", "/api/items/AB-999", cookie=mem)[0] == 404

# Editing, history, comments and progress.
edited = ok(call("PATCH", "/api/items/AB-2", {"title": "Board", "priority": "high", "due": "2026-12-01"}, cookie=mem))
assert edited["priority"] == "high" and edited["due"] == "2026-12-01"
assert story["next"] == "" and ok(call("PATCH", "/api/items/AB-2", {"next": "  Ann checks the <b>draft</b> "}, cookie=mem))["next"] == "Ann checks the <b>draft</b>"
assert call("PATCH", "/api/items/AB-2", {"next": "x" * 201}, cookie=mem)[0] == 400
assert ok(call("PATCH", "/api/items/AB-2", {"next": "Ann tests\r\n\n  then Bo"}, cookie=mem))["next"] == "Ann tests then Bo"
assert ok(call("POST", "/api/items", {"project": "AB", "title": "m", "next": "a\nb"}, cookie=mem), 201)["next"] == "a b"
assert ok(call("POST", "/api/items", {"project": "AB", "title": "n", "next": "Bo reviews"}, cookie=mem), 201)["next"] == "Bo reviews"
assert any(a["field"] == "next" for a in ok(call("GET", "/api/items/AB-2", cookie=mem))["activity"])
ok(call("PATCH", f"/api/items/{sub['key']}", {"status": "done"}, cookie=mem))
ok(call("POST", "/api/items/AB-2/comments", {"body": "looks good"}, cookie=mem), 201)
full = ok(call("GET", "/api/items/AB-2", cookie=view))
assert full["comment_count"] == 1
assert full["children"] == 1 and full["children_done"] == 1 and full["subitems"][0]["key"] == sub["key"]
assert full["comments"][0]["user"] == "mem" and {a["field"] for a in full["activity"]} >= {"title", "priority", "due_date"}

# Card order on the board.
for title in ("one", "two", "three"):
    ok(call("POST", "/api/items", {"project": "AB", "title": title, "status": "review"}, cookie=mem), 201)
order = lambda: [i["title"] for i in ok(call("GET", "/api/items?project=AB&status=review", cookie=mem))]  # noqa: E731
keys = {i["title"]: i["key"] for i in ok(call("GET", "/api/items?project=AB&status=review", cookie=mem))}
assert order() == ["one", "two", "three"]
ok(call("POST", f"/api/items/{keys['three']}/move", {"before": keys["one"]}, cookie=mem))
assert order() == ["three", "one", "two"]
ok(call("POST", f"/api/items/{keys['two']}/move", {"before": keys["one"]}, cookie=mem))
assert order() == ["three", "two", "one"]
ok(call("POST", f"/api/items/{keys['three']}/move", {"status": "review"}, cookie=mem))
assert order() == ["two", "one", "three"]
ok(call("POST", f"/api/items/{keys['one']}/move", {"status": "done"}, cookie=mem))
assert order() == ["two", "three"]
assert call("POST", f"/api/items/{keys['two']}/move", {"status": "done", "before": keys["three"]}, cookie=mem)[0] == 400

# Moving into one gap again and again keeps the order right, even past the limit of decimal places.
anchor = ok(call("POST", "/api/items", {"project": "AB", "title": "anchor", "status": "review"}, cookie=mem), 201)["key"]
for n in range(60):
    mover = keys["two" if n % 2 else "three"]
    ok(call("POST", f"/api/items/{mover}/move", {"before": anchor}, cookie=mem))
    assert order().index(ok(call("GET", f"/api/items/{mover}", cookie=mem))["title"]) < order().index("anchor")
    assert order()[-1] == "anchor" and order()[-2] == ok(call("GET", f"/api/items/{mover}", cookie=mem))["title"]

# Columns of your own.
CO = lambda body: call("PUT", "/api/projects/CO/columns", body, cookie=ann)  # noqa: E731
ok(call("POST", "/api/projects", {"key": "CO", "name": "Columns"}, cookie=ann))
assert call("PUT", "/api/projects/CO/columns", {"columns": [{"name": "A"}]}, cookie=mem)[0] == 403
start = ok(call("GET", "/api/projects", cookie=ann))
start = next(p for p in start if p["key"] == "CO")["statuses"]
card = ok(call("POST", "/api/items", {"project": "CO", "title": "c", "status": "review"}, cookie=mem), 201)["key"]
keep = [{"slug": s["slug"], "name": s["name"], "is_done": s["is_done"]} for s in start]
no_review = [c for c in keep if c["slug"] != "review"]
assert CO({"columns": []})[0] == 400 and CO({"columns": [{"name": " "}]})[0] == 400
assert CO({"columns": [{"name": "Same"}, {"name": "same"}]})[0] == 400
assert CO({"columns": [{"slug": "ghost", "name": "G"}]})[0] == 400
assert CO({"columns": [{"slug": [], "name": "G"}]})[0] == 400
assert CO({"columns": [{"slug": "ideas", "name": "G"}, {"slug": "ideas", "name": "H"}]})[0] == 400
assert CO({"columns": no_review})[0] == 400  # review still has a card, with nowhere to go
assert CO({"columns": no_review, "move": {"review": "review"}})[0] == 400
made = ok(CO({"columns": [{"name": "Testing & QA"}] + list(reversed(no_review)), "move": {"review": "testing_qa"}}))
assert made["statuses"][0]["slug"] == "testing_qa" and made["statuses"][-1]["slug"] == "ideas" and len(made["statuses"]) == 6
assert ok(call("GET", f"/api/items/{card}", cookie=mem))["status"] == "testing_qa"
assert ok(call("GET", f"/api/items/{card}", cookie=mem))["activity"][0]["new"] == "testing_qa"
assert next(s for s in made["statuses"] if s["slug"] == "done")["is_done"] == 1
assert CO({"columns": made["statuses"] + [{"name": "Testing  QA"}]})[0] == 200  # same words again gets a new slug
assert call("POST", "/api/items", {"project": "CO", "title": "x", "status": "review"}, cookie=mem)[0] == 400  # gone
renamed = [dict(s, name="Finished") if s["slug"] == "done" else s for s in ok(call("GET", "/api/projects", cookie=ann))[0]["statuses"]]
assert next(s for s in ok(call("PUT", "/api/projects/CO/columns", {"columns": renamed}, cookie=ann))["statuses"] if s["slug"] == "done")["name"] == "Finished"

# Days in a column: set when made, changed only by moving to another column.
aged = ok(call("POST", "/api/items", {"project": "AB", "title": "aged", "status": "review"}, cookie=mem), 201)
assert aged["status_since"] and abs(aged["status_since"] - aged["created"]) < 5
conn = sugarbag.connect()
conn.execute("UPDATE items SET status_since = 1000 WHERE num = ?", (int(aged["key"].split("-")[1]),))
assert ok(call("POST", f"/api/items/{aged['key']}/move", {"status": "review"}, cookie=mem))["status_since"] == 1000  # same column
assert ok(call("PATCH", f"/api/items/{aged['key']}", {"title": "older"}, cookie=mem))["status_since"] == 1000
assert ok(call("POST", f"/api/items/{aged['key']}/move", {"status": "done"}, cookie=mem))["status_since"] > 1000
conn.execute("UPDATE items SET status_since = 1000 WHERE num = ?", (int(aged["key"].split("-")[1]),))
assert ok(call("PATCH", f"/api/items/{aged['key']}", {"status": "review"}, cookie=mem))["status_since"] > 1000
conn.close()
ok(call("DELETE", f"/api/items/{aged['key']}", cookie=mem))

# An older database gets the new columns, with sensible dates.
old_path = os.path.join(tmp.name, "old.db")
old_schema = sugarbag.SCHEMA.replace(", hidden_columns TEXT NOT NULL DEFAULT '{}'", "").replace(" status_since INTEGER,", "").replace(" next TEXT NOT NULL DEFAULT '',", "")
old = sqlite3.connect(old_path)
old.executescript(old_schema)
old.execute("INSERT INTO projects (key, name) VALUES ('OL', 'Old')")
old.execute("INSERT INTO items (project_id, num, type, title, status, position, created, updated) VALUES (1, 1, 'task', 'a', 'ideas', 1, 500, 500)")
old.execute("INSERT INTO items (project_id, num, type, title, status, position, created, updated) VALUES (1, 2, 'task', 'b', 'ideas', 2, 500, 500)")
old.execute("INSERT INTO activity (item_id, field, old, new, at) VALUES (2, 'status', 'x', 'ideas', 700)")
old.commit()
old.close()
saved = os.environ["SUGARBAG_DB"]
os.environ["SUGARBAG_DB"] = old_path
sugarbag.init_db()
sugarbag.init_db()  # and again, harmlessly
check = sugarbag.connect()
assert [r["status_since"] for r in check.execute("SELECT status_since FROM items ORDER BY id")] == [500, 700]
assert [r["next"] for r in check.execute("SELECT next FROM items ORDER BY id")] == ["", ""]  # old rows keep working, with no next step
check.close()
os.environ["SUGARBAG_DB"] = saved

# Your own name, and your own view of the columns.
assert ok(call("GET", "/api/me", cookie=view))["hidden"] == {}
assert ok(call("PUT", "/api/me/hidden/AB", {"columns": ["done", "ghost"]}, cookie=view)) == ["done"]  # a viewer may tidy their own view
assert ok(call("GET", "/api/me", cookie=view))["hidden"] == {"AB": ["done"]}
assert ok(call("GET", "/api/me", cookie=mem))["hidden"] == {}  # nobody else's board changes
assert call("PUT", "/api/me/hidden/AB", {"columns": "done"}, cookie=view)[0] == 400
assert call("PUT", "/api/me/hidden/NOPE", {"columns": []}, cookie=view)[0] == 404
assert call("PATCH", "/api/me", {"name": "ann"}, cookie=view)[0] == 409
assert call("PATCH", "/api/me", {"name": "bad name!"}, cookie=view)[0] == 400
assert ok(call("PATCH", "/api/me", {"name": "viewer2"}, cookie=view))["name"] == "viewer2"
assert ok(call("GET", "/api/me", cookie=view))["name"] == "viewer2"  # still signed in
ok(call("PATCH", "/api/me", {"name": "view"}, cookie=view))

# Search and filters.
assert [i["key"] for i in ok(call("GET", "/api/items?project=AB&q=Board", cookie=mem))] == ["AB-2"]
assert ok(call("GET", "/api/items?project=AB&q=%25", cookie=mem)) == []  # a % is a character, not a wildcard
assert [i["key"] for i in ok(call("GET", "/api/items?project=AB&label=ui", cookie=mem))] == ["AB-2"]
assert [i["key"] for i in ok(call("GET", "/api/items?project=AB&assignee=mem", cookie=mem))] == ["AB-2"]
assert [i["key"] for i in ok(call("GET", "/api/items?project=AB&parent=AB-1", cookie=mem))] == ["AB-2"]

# Importing the same thing twice makes one item.
ok(call("POST", "/api/items", {"project": "AB", "title": "t", "ref": "ticket:a"}, cookie=mem), 201)
assert call("POST", "/api/items", {"project": "AB", "title": "t", "ref": "ticket:a"}, cookie=mem)[0] == 409

# Tokens: shown once, work without a cookie, and stop when removed.
made = ok(call("POST", "/api/tokens", {"label": "agent"}, cookie=mem))
assert made["token"].startswith("sugarbag_")
assert "token" not in ok(call("GET", "/api/tokens", cookie=mem))[0] and "hash" not in ok(call("GET", "/api/tokens", cookie=mem))[0]
assert ok(call("POST", "/api/items", {"project": "AB", "title": "from an agent"}, token=made["token"], headers={"Origin": "https://anywhere.example"}), 201)["created_by"] == "mem"
assert call("GET", "/api/me", token="sugarbag_wrong")[0] == 401
token_id = ok(call("GET", "/api/tokens", cookie=mem))[0]["id"]
assert call("DELETE", f"/api/tokens/{token_id}", cookie=ann)[0] == 404  # someone else's token
ok(call("DELETE", f"/api/tokens/{token_id}", cookie=mem))
assert call("GET", "/api/me", token=made["token"])[0] == 401

# Deleting, and who may.
other = ok(call("POST", "/api/items", {"project": "AB", "title": "ann's"}, cookie=ann), 201)
assert call("DELETE", f"/api/items/{other['key']}", cookie=mem)[0] == 403
# Moving someone's task under your own epic doesn't let you delete it.
mine = ok(call("POST", "/api/items", {"project": "AB", "type": "epic", "title": "mine"}, cookie=mem), 201)
ok(call("PATCH", f"/api/items/{other['key']}", {"parent": mine["key"]}, cookie=mem))
assert call("DELETE", f"/api/items/{mine['key']}", cookie=mem)[0] == 403
assert call("GET", f"/api/items/{other['key']}", cookie=mem)[0] == 200
ok(call("PATCH", f"/api/items/{other['key']}", {"parent": None}, cookie=mem))
ok(call("DELETE", f"/api/items/{mine['key']}", cookie=mem))
ok(call("DELETE", f"/api/items/{other['key']}", cookie=ann))
ok(call("DELETE", "/api/items/AB-2", cookie=ann))
assert call("GET", f"/api/items/{sub['key']}", cookie=mem)[0] == 404  # its sub-task went with it

# Users: the last admin stays, and a switched-off user stops at once.
assert call("PATCH", "/api/users/ann", {"role": "member"}, cookie=ann)[0] == 400
tok = ok(call("POST", "/api/tokens", {"label": "x"}, cookie=mem))["token"]
ok(call("PATCH", "/api/users/mem", {"active": False}, cookie=ann))
assert call("GET", "/api/me", cookie=mem)[0] == 401 and call("GET", "/api/me", token=tok)[0] == 401

# The export never holds passwords or tokens.
dump = json.dumps(ok(call("GET", "/api/export", cookie=ann)))
assert "password" not in dump and "sugarbag_" not in dump

# The command line, as an agent uses it. A real run, with no settings file.
import subprocess  # noqa: E402
import sys  # noqa: E402

agent = ok(call("POST", "/api/tokens", {"label": "cli"}, cookie=ann))["token"]
env = dict(os.environ, SUGARBAG_URL=BASE, SUGARBAG_TOKEN=agent, SUGARBAG_PROJECT="AB", SUGARBAG_ENV=os.path.join(tmp.name, "none"))


def sb(*args, stdin=""):
    r = subprocess.run([sys.executable, "-B", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sb.py"), *args], capture_output=True, text=True, env=env, input=stdin, timeout=30)
    assert agent not in r.stdout + r.stderr  # a token must never be printed
    return r.returncode, r.stdout, r.stderr


code, key, _ = sb("new", "From the command line", "--type", "bug", "--status", "selected", "--label", "cli", "--body-file", "-", stdin="Long text")
assert code == 0 and key.startswith("AB-")
key = key.strip()
# Between a merge and a rebuild the server has no next field; sb.py must still work.
import sb as sb_module  # noqa: E402
fake = {"key": "AB-9", "title": "t", "type": "task", "status": "ideas", "priority": "medium", "assignee": None, "parent": None, "body": "", "subitems": [], "comments": [], "children": 0}
sb_module.call = lambda *a, **k: fake
sb_module.do_show({}, argparse.Namespace(key="AB-9"))
assert "next" not in fake
assert "selected" in sb("columns")[1] and key in sb("list")[1] and "@" not in sb("list", "--q", "From the command")[1]
assert sb("move", key, "in_progress")[0] == 0 and "in_progress" in sb("show", key)[1]
assert sb("comment", key, "-", stdin="Did the thing")[0] == 0 and "Did the thing" in sb("show", key)[1]
assert sb("edit", key, "--title", "Renamed", "--assignee", "ann")[0] == 0 and "Renamed" in sb("show", key)[1]
assert key in sb("list", "--mine")[1]
assert sb("edit", key, "--next", "Ann writes the test")[0] == 0 and "Next: Ann writes the test" in sb("show", key)[1]
assert "-> Ann writes the test" in sb("list", "--who", "ann")[1] and key not in sb("list", "--who", "mem")[1]
assert sb("watch", key, "--every", "0.1", "--timeout", "0.3")[0] == 3  # nothing new
watcher = subprocess.Popen([sys.executable, "-B", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sb.py"), "watch", key, "--every", "0.2", "--timeout", "20"], stdout=subprocess.PIPE, text=True, env=env)
import time  # noqa: E402
time.sleep(1)  # let it read the ticket first
ok(call("POST", f"/api/items/{key}/comments", {"body": "To worker: fix the title"}, cookie=ann), 201)
out, _ = watcher.communicate(timeout=25)
assert watcher.returncode == 0 and "To worker: fix the title" in out, out
epic_key = ok(call("POST", "/api/items", {"project": "AB", "type": "epic", "title": "An epic for finding"}, cookie=ann), 201)["key"]
assert epic_key not in sb("list")[1] and epic_key in sb("list", "--all", "--q", "An epic for")[1]  # so an agent can find it before making a duplicate
ok(call("DELETE", f"/api/items/{epic_key}", cookie=ann))
assert sb("move", key, "nope")[0] != 0 and "Sugarbag said no" in sb("move", key, "nope")[2]
assert sb("show", "AB-99999")[0] != 0
env["SUGARBAG_TOKEN"] = ""
assert "No token" in sb("list")[2]

# Too many wrong passwords. Only that name is locked: behind a proxy everyone shares one address.
for _ in range(10):
    call("POST", "/api/login", {"name": "ann", "password": "wrong"})
assert call("POST", "/api/login", {"name": "ann", "password": "password-1"})[0] == 429
assert call("POST", "/api/login", {"name": "Ann", "password": "password-1"})[0] == 429  # same name in other letters
sign_in("view", "password-3")

# Changing your password signs you out everywhere else.
other = sign_in("view", "password-3")
ok(call("POST", "/api/password", {"old": "password-3", "new": "password-33"}, cookie=view))
assert ok(call("GET", "/api/me", cookie=view))["name"] == "view"  # the session that changed it stays
assert call("GET", "/api/me", cookie=other)[0] == 401

# A login whose password check was already running when the password changed gets no session.
real_check = sugarbag.check_password


def change_midway(password, stored):
    good = real_check(password, stored)
    sugarbag.check_password = real_check
    db = sugarbag.connect()
    db.execute("UPDATE users SET password = ? WHERE name = 'view'", (sugarbag.hash_password("password-34"),))
    db.execute("DELETE FROM sessions WHERE user_id = (SELECT id FROM users WHERE name = 'view')")
    db.close()
    return good


sugarbag.check_password = change_midway
assert call("POST", "/api/login", {"name": "view", "password": "password-33"})[0] == 401
assert sugarbag.check_password is real_check
view = sign_in("view", "password-34")

# Markdown is read in one pass: 100,000 characters shaped to make a careless pattern rescan the line render quickly.
import shutil  # noqa: E402
import subprocess  # noqa: E402
if shutil.which("node"):
    md = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "md.js")
    check = """require(process.argv[1]); const N = 100000;
    if (!mdInline("[here](http://[::1]:8094/)").includes('href="http://[::1]:8094/"')) { console.log("IPv6 link lost"); process.exit(1); }
    for (const piece of ["[", "[<", "[&", "[a](http://x", "[a](http://[::", "[a](http://[::1]x[", "**a", "`a", "~~a", "&", "- a\\n", "|a|\\n"]) {
      const t = Date.now(); mdToHtml(piece.repeat(N / piece.length)); const ms = Date.now() - t;
      if (ms > 200) { console.log(JSON.stringify(piece) + " took " + ms + " ms"); process.exit(1); } }"""
    slow = subprocess.run(["node", "-e", check, md], capture_output=True, text=True)
    assert slow.returncode == 0, slow.stdout + slow.stderr
else:
    print("node not found: skipped the Markdown speed check")

# Old wrong guesses drop out of a key that's still in use, so one a minute doesn't keep them all.
import time  # noqa: E402
sugarbag.failed_logins[("9.9.9.9", "x")] = [time.time() - 700] * 50 + [time.time()]
assert not sugarbag.too_many_failures(("9.9.9.9", "x")) and len(sugarbag.failed_logins[("9.9.9.9", "x")]) == 1

# A new password is hashed before the write lock is taken, so other writers aren't held up for it.
real_hash = sugarbag.hash_password


def hash_while_unlocked(password):
    probe = sugarbag.sqlite3.connect(os.environ["SUGARBAG_DB"], timeout=0)
    probe.execute("BEGIN IMMEDIATE")  # fails with "database is locked" if the lock is held
    probe.execute("ROLLBACK")
    probe.close()
    return real_hash(password)


sugarbag.hash_password = hash_while_unlocked
ok(call("POST", "/api/password", {"old": "password-34", "new": "password-35"}, cookie=view))
sugarbag.hash_password = real_hash

# Two password changes at once: the one that checked the old password before the other landed must not overwrite it.
def other_change_lands(password, stored):
    sugarbag.check_password = real_check
    db = sugarbag.connect()
    db.execute("UPDATE users SET password = ? WHERE name = 'view'", (real_hash("password-36"),))
    db.close()
    return real_check(password, stored)


sugarbag.check_password = other_change_lands
assert call("POST", "/api/password", {"old": "password-35", "new": "password-99"}, cookie=view)[0] == 409
assert sugarbag.check_password is real_check
view = sign_in("view", "password-36")

# A token being made while an admin switches the user off is refused, and nothing is left to work after switching back on.
ok(call("POST", "/api/users", {"name": "tok", "password": "password-7", "role": "member"}, cookie=ann))
tok = sign_in("tok", "password-7")
real_urlsafe = sugarbag.secrets.token_urlsafe


def switched_off_meanwhile(n):
    sugarbag.secrets.token_urlsafe = real_urlsafe
    ok(call("PATCH", "/api/users/tok", {"active": False}, cookie=ann))
    return real_urlsafe(n)


sugarbag.secrets.token_urlsafe = switched_off_meanwhile
assert call("POST", "/api/tokens", {"label": "race"}, cookie=tok)[0] == 401
assert sugarbag.secrets.token_urlsafe is real_urlsafe
ok(call("PATCH", "/api/users/tok", {"active": True}, cookie=ann))
assert not sugarbag.connect().execute("SELECT 1 FROM tokens t JOIN users u ON u.id = t.user_id WHERE u.name = 'tok'").fetchone()

# A token revoked while a request signed in with it is making a new one: refused, and no new token is left.
tok = sign_in("tok", "password-7")  # switching off signed it out
token_a = ok(call("POST", "/api/tokens", {"label": "A"}, cookie=tok))["token"]
a_id = ok(call("GET", "/api/tokens", cookie=tok))[-1]["id"]


def revoked_meanwhile(n):
    sugarbag.secrets.token_urlsafe = real_urlsafe
    ok(call("DELETE", f"/api/tokens/{a_id}", cookie=tok))
    return real_urlsafe(n)


sugarbag.secrets.token_urlsafe = revoked_meanwhile
assert call("POST", "/api/tokens", {"label": "B"}, token=token_a)[0] == 401
assert sugarbag.secrets.token_urlsafe is real_urlsafe and ok(call("GET", "/api/tokens", cookie=tok)) == []

# The same for an admin's token while it adds a person.
token_admin = ok(call("POST", "/api/tokens", {"label": "admin"}, cookie=ann))["token"]
admin_id = ok(call("GET", "/api/tokens", cookie=ann))[-1]["id"]


def admin_token_revoked(password):
    sugarbag.hash_password = real_hash
    ok(call("DELETE", f"/api/tokens/{admin_id}", cookie=ann))
    return real_hash(password)


sugarbag.hash_password = admin_token_revoked
assert call("POST", "/api/users", {"name": "late", "password": "password-8"}, token=token_admin)[0] == 401
assert sugarbag.hash_password is real_hash and "late" not in [u["name"] for u in ok(call("GET", "/api/users", cookie=ann))]

# A user name outside plain ASCII can still be managed from the page, which sends it percent-encoded.
ok(call("POST", "/api/users", {"name": "José", "password": "password-5"}, cookie=ann))
assert ok(call("PATCH", "/api/users/Jos%C3%A9", {"role": "viewer"}, cookie=ann))["role"] == "viewer"

# A body length the server can't trust is refused before anything is read, and a silent connection is let go.
import socket  # noqa: E402
for length in (b"-1", b"lots"):
    with socket.create_connection(("127.0.0.1", server.server_address[1])) as s:
        s.sendall(b"POST /api/login HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: " + length + b"\r\n\r\n{}")
        assert s.recv(100).split(b" ")[1] == b"400"
assert sugarbag.Handler.timeout

server.shutdown()
print("sugarbag ok")
