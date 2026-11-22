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

### Security

Found by an audit before release, and fixed:

- A request with a negative body length is refused before anything is read. Before, it skipped the 1 MB limit, without a login.
- Wrong passwords are counted per address and name. Behind a proxy, where everyone shares one address, one person's wrong guesses no longer stop everyone signing in.
- Changing your password signs you out everywhere else.
- A connection that sends nothing is dropped after 30 seconds.

### Fixed

- People whose names have letters outside plain English (José) can have their role changed from the page.
- Higher contrast for epic and overdue labels, the days-in-column count, quiet text and placeholders, in light and dark.
- On a phone, the project menu uses the room beside it, so its name isn't cut short.
- Timeline rows show a title's Markdown the way the board does.

### Upgrading

Nothing to do for a first release. Later versions upgrade the database themselves when they start, and only ever add to it. Back up the database file first anyway: see the README.
