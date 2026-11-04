# Sugarbag

A small issue tracker with a Kanban board, for one person or a small team: issue tracking without the sting. Sugarbag is the common name of Australia's native stingless bee, which is small, busy and lives in a tidy hive.

One Python file, one SQLite database, one page. Nothing to install except Python 3.11 or newer, and no outside scripts.

## Try it

```bash
python3 sugarbag.py adduser yourname   # asks for a password; the first user should be an admin
python3 sugarbag.py                    # then open http://127.0.0.1:8094
```

Or with Docker: see `compose.example.yml`.

## What's in it

- **Board:** starts with Ideas (the backlog), Selected for development, In progress, Blocked, Review and Done. Each project can have its own columns. Drag with a mouse. On a phone, rest a finger on a card first, so a swipe still scrolls.
- **Levels:** Epic > Story, Task or Bug > Sub-task. Stories and tasks sit level, so nobody has to decide which contains which.
- **Issues:** keys such as `ABO-12`, priority, assignee, labels, start and due dates, Markdown description, comments, history. An issue opens in the middle of the screen (`/#ABO-12`) or as its own page (`/?issue=ABO-12`).
- **List:** everything, nested, including epics and sub-tasks.
- **Your view:** hide or show columns for yourself. Light, dark, or following the device. Change your own name.
- **Cards show age:** days in the current column, turning amber after 14 days in a working column.
- **Search and filters:** by words, assignee and epic.
- **Roles:** admin (people, projects, delete anything), member (make and change issues, delete their own), viewer (read only).
- **API tokens:** for agents and scripts.

**Left out on purpose:** sprints, story points, velocity charts, custom fields, workflow editors, permission schemes and plugins.

**Not yet:** timeline view (dates are already stored), blocking links.

## Settings

All from the environment. See the top of `sugarbag.py`: `SUGARBAG_DB`, `SUGARBAG_BIND`, `SUGARBAG_PORT`, `SUGARBAG_NAME`, `SUGARBAG_SECURE_COOKIE`.

## The API

JSON. Sign in with `Authorization: Bearer <token>`. Make a token in the page's settings, or with `python3 sugarbag.py token <user> <label>`.

| Call | What it does |
| --- | --- |
| `GET /health`, `GET /info` | Is it working; name and version. No login. |
| `GET /api/projects` | Projects and their columns. |
| `POST /api/projects` | `{key, name}`. Admin. |
| `PUT /api/projects/ABO/columns` | `{columns: [{slug, name, is_done}], move: {old_slug: new_slug}}`: the whole list, in order. Leave out `slug` for a new column. A removed column with items in it needs a `move`. Admin. |
| `GET /api/items?project=ABO` | Items. Also `status`, `type`, `assignee`, `label`, `parent`, `ref`, `q`. |
| `POST /api/items` | `{project, title, type, parent, status, priority, assignee, labels, start, due, body, ref}`. `ref` is your own unique name for it: sending the same one twice gets a 409, so a script is safe to rerun. |
| `GET /api/items/ABO-12` | One item, with its sub-items, comments and history. |
| `PATCH /api/items/ABO-12` | Change any of those fields. |
| `POST /api/items/ABO-12/move` | `{status, before}`: to a column, above the card `before`, or at the bottom. |
| `DELETE /api/items/ABO-12` | Creator or admin. Takes its sub-items too. |
| `POST /api/items/ABO-12/comments` | `{body}`. |
| `GET /api/me`, `PATCH /api/me`, `PUT /api/me/hidden/ABO` | You. Change your name with `{name}`. Set columns you hide on a project's board with `{columns: [slug]}`. |
| `GET /api/users`, `POST /api/users`, `PATCH /api/users/<name>` | People. Changes need an admin. |
| `GET /api/tokens`, `POST /api/tokens`, `DELETE /api/tokens/<id>` | Your own tokens. |
| `GET /api/export` | Everything except passwords and tokens. Admin. |

```bash
curl -H "Authorization: Bearer $SUGARBAG_TOKEN" -H "Content-Type: application/json" \
  -d '{"project":"ABO","type":"task","title":"Check the backups","status":"selected"}' \
  http://127.0.0.1:8094/api/items
```

## Security

Passwords are hashed with scrypt, and tokens and sessions are stored only as fingerprints. A signed-in browser's write requests must come from Sugarbag's own page. Text from issues is escaped before it reaches the page. There's no https of its own: to host Sugarbag beyond your own machine or private network, put a proxy with https in front and set `SUGARBAG_SECURE_COOKIE=1`.

## Backup

Copy the database file. To copy it while Sugarbag runs, use `sqlite3 sugarbag.db ".backup copy.db"`. `GET /api/export` also gives you everything as JSON.

## Checks

`python3 sugarbag_test.py` runs the API against a real server with a throwaway database.
