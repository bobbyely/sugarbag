# Changelog

All notable changes to Sugarbag are written down here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - unreleased

The first public release: a small issue tracker with a Kanban board, for one person or a small team. One Python file, one SQLite database and one page, with nothing to install but Python.

### What's in it

- A board with columns each project can set, drag and drop, and cards that show how long they have sat in a column.
- Epics, stories, tasks, bugs and sub-tasks; priority, assignee, a one-line next step, labels, dates, Markdown descriptions, comments and history.
- List, roadmap and timeline views, search and filters.
- Light and dark, and a layout that works on a phone.
- Admin, member and viewer roles; API tokens; a JSON API and `sb.py`, a command-line client for scripts and agents.
- `GET /api/export` for everything as JSON.

### Upgrading

Nothing to do for a first release. Later versions upgrade the database themselves when they start, and only ever add to it. Back up the database file first anyway: see the README.
