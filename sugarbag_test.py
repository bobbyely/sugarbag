#!/usr/bin/env python3
"""Checks Sugarbag's API against a real server on a spare port with a throwaway database. Run by hand or by GitHub.

  python3 services/sugarbag/sugarbag_test.py

Reads and writes only a temporary folder. Takes a few seconds, because passwords are slow to hash on purpose.
"""
import json
import os
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
ok(call("PATCH", f"/api/items/{sub['key']}", {"status": "done"}, cookie=mem))
ok(call("POST", "/api/items/AB-2/comments", {"body": "looks good"}, cookie=mem), 201)
full = ok(call("GET", "/api/items/AB-2", cookie=view))
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

# Too many wrong passwords.
for _ in range(10):
    call("POST", "/api/login", {"name": "ann", "password": "wrong"})
assert call("POST", "/api/login", {"name": "ann", "password": "password-1"})[0] == 429

server.shutdown()
print("sugarbag ok")
