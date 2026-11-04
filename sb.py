#!/usr/bin/env python3
"""Sugarbag from the command line, for agents and scripts. Run by hand; talks to a Sugarbag server through its API.

Settings come from the environment, or from ~/.config/sugarbag/env as KEY=value lines:
  SUGARBAG_URL      the server (default http://127.0.0.1:8094)
  SUGARBAG_TOKEN    an API token. Keep that file private (chmod 600)
  SUGARBAG_PROJECT  the project key, so you needn't type it each time

  sb.py list                          what's open, by column. --all adds everything: finished work, epics, waiting sub-tasks. --mine, --q WORDS filter it
  sb.py show AB-12                    one ticket, with its sub-tasks, comments and history
  sb.py new "Title" --body-file -     make a ticket. Also --type --parent --status --priority --assignee --label
  sb.py move AB-12 in_progress        move to a column, by its short name; sb.py columns lists them
  sb.py comment AB-12 "What I did"    add a comment. Use - to read it from standard input
  sb.py edit AB-12 --title "New"      change a field. Also --body-file --priority --assignee --label --parent --due --start
  sb.py watch AB-12 AB-13             wait until any of these gets a new comment or changes column, print it, and end.
                                      Run it in the background. Ends with code 3 after --timeout seconds (default 1500)

Standard library only. Prints no secrets. Checked by sugarbag_test.py.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def settings():
    conf = {}
    path = Path(os.environ.get("SUGARBAG_ENV", Path.home() / ".config/sugarbag/env"))
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                conf[key.strip()] = value.strip().strip("\"'")
    for key in ("SUGARBAG_URL", "SUGARBAG_TOKEN", "SUGARBAG_PROJECT"):
        if os.environ.get(key):
            conf[key] = os.environ[key]
    conf.setdefault("SUGARBAG_URL", "http://127.0.0.1:8094")
    return conf


def call(conf, method, path, body=None):
    if not conf.get("SUGARBAG_TOKEN"):
        sys.exit("No token. Set SUGARBAG_TOKEN, or add it to ~/.config/sugarbag/env.")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(conf["SUGARBAG_URL"].rstrip("/") + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + conf["SUGARBAG_TOKEN"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            reason = json.load(e)["error"]
        except (ValueError, KeyError):
            reason = str(e.code)
        sys.exit(f"Sugarbag said no: {reason}")
    except urllib.error.URLError as e:
        sys.exit(f"Can't reach Sugarbag at {conf['SUGARBAG_URL']}: {e.reason}")


def project_of(conf, args):
    project = getattr(args, "project", None) or conf.get("SUGARBAG_PROJECT")
    if not project:
        sys.exit("Which project? Use --project, or set SUGARBAG_PROJECT.")
    return project.upper()


def columns_of(conf, project):
    for p in call(conf, "GET", "/api/projects"):
        if p["key"] == project:
            return p["statuses"]
    sys.exit(f"No project {project}.")


def read_text(value):
    return sys.stdin.read() if value == "-" else value


def fields(args):
    out = {}
    for name in ("type", "status", "priority", "assignee", "parent", "start", "due", "title"):
        value = getattr(args, name, None)
        if value is not None:
            out[name] = value or None
    if getattr(args, "label", None) is not None:
        out["labels"] = args.label
    if getattr(args, "body_file", None):
        out["body"] = sys.stdin.read() if args.body_file == "-" else Path(args.body_file).read_text()
    return out


def do_list(conf, args):
    project = project_of(conf, args)
    query = {"project": project}
    if args.q:
        query["q"] = args.q
    items = call(conf, "GET", "/api/items?" + urllib.parse.urlencode(query))
    me = call(conf, "GET", "/api/me")["name"] if args.mine else None
    for column in columns_of(conf, project):
        if column["is_done"] and not args.all:
            continue
        working = column["position"] >= 2 and not column["is_done"]  # the same rule as the board: a sub-task shows only while being worked on
        rows = [i for i in items if i["status"] == column["slug"] and (args.all or (i["type"] != "epic" and (working or i["type"] != "subtask"))) and (not me or i["assignee"] == me)]
        if rows:
            print(f"\n{column['name']} ({column['slug']})")
        for i in rows:
            steps = f" [{i['children_done']}/{i['children']}]" if i["children"] else ""
            print(f"  {i['key']:<9}{i['title']}{steps}" + (f"  @{i['assignee']}" if i["assignee"] else ""))


def do_show(conf, args):
    i = call(conf, "GET", "/api/items/" + args.key)
    print(f"{i['key']} {i['title']}\n{i['type']}, {i['status']}, {i['priority']}" + (f", {i['assignee']}" if i["assignee"] else "") +
          (f", under {i['parent']}" if i["parent"] else ""))
    if i["body"]:
        print("\n" + i["body"])
    if i["subitems"]:
        print("\nUnder this:")
        for k in i["subitems"]:
            print(f"  {k['key']:<9}{k['status']:<14}{k['title']}")
    if i["comments"]:
        print("\nComments:")
        for c in i["comments"]:
            print(f"  {c['user']}: {c['body']}")


def do_new(conf, args):
    i = call(conf, "POST", "/api/items", dict(fields(args), project=project_of(conf, args), title=args.title))
    print(i["key"])


def do_move(conf, args):
    print(f"{call(conf, 'POST', f'/api/items/{args.key}/move', {'status': args.status})['key']} is now in {args.status}")


def do_comment(conf, args):
    call(conf, "POST", f"/api/items/{args.key}/comments", {"body": read_text(args.text)})
    print(f"Comment added to {args.key}")


def do_edit(conf, args):
    change = fields(args)
    if not change:
        sys.exit("Nothing to change.")
    print(f"{call(conf, 'PATCH', '/api/items/' + args.key, change)['key']} changed")


def do_watch(conf, args):
    # shortcut: a comment made just before this starts isn't counted as new, so read the ticket again after starting if it matters.
    seen = {k: call(conf, "GET", "/api/items/" + k) for k in args.keys}
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        time.sleep(args.every)
        changed = False
        for key, old in seen.items():
            now = call(conf, "GET", "/api/items/" + key)
            for c in now["comments"][len(old["comments"]):]:
                print(f"{key} {c['user']}: {c['body']}")
                changed = True
            if now["status"] != old["status"]:
                print(f"{key} moved to {now['status']}")
                changed = True
        if changed:
            return
    print("Nothing new yet.")
    sys.exit(3)


def do_columns(conf, args):
    for c in columns_of(conf, project_of(conf, args)):
        print(f"{c['slug']:<16}{c['name']}" + ("  (finished)" if c["is_done"] else ""))


def main():
    parser = argparse.ArgumentParser(description="Sugarbag from the command line.")
    parser.add_argument("--project")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--mine", action="store_true")
    listing.add_argument("--q")
    listing.set_defaults(fn=do_list)
    sub.add_parser("columns").set_defaults(fn=do_columns)
    show = sub.add_parser("show")
    show.add_argument("key")
    show.set_defaults(fn=do_show)
    move = sub.add_parser("move")
    move.add_argument("key")
    move.add_argument("status")
    move.set_defaults(fn=do_move)
    watch = sub.add_parser("watch")
    watch.add_argument("keys", nargs="+")
    watch.add_argument("--every", type=float, default=30)
    watch.add_argument("--timeout", type=float, default=1500)
    watch.set_defaults(fn=do_watch)
    comment = sub.add_parser("comment")
    comment.add_argument("key")
    comment.add_argument("text")
    comment.set_defaults(fn=do_comment)
    for name, fn in (("new", do_new), ("edit", do_edit)):
        p = sub.add_parser(name)
        if name == "new":
            p.add_argument("title")
        else:
            p.add_argument("key")
            p.add_argument("--title")
        for flag in ("type", "status", "priority", "assignee", "parent", "start", "due"):
            if name == "edit" and flag == "status":
                continue  # moving has its own command, which keeps the card's place in the column right
            p.add_argument("--" + flag)
        p.add_argument("--label", action="append")
        p.add_argument("--body-file", help="a file, or - for standard input")
        p.set_defaults(fn=fn)
    args = parser.parse_args()
    args.fn(settings(), args)


if __name__ == "__main__":
    main()
