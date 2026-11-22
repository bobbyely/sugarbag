# AGENTS.md: Sugarbag

Guide for coding agents working on Sugarbag. If this folder sits inside a bigger repo, read that repo's `AGENTS.md` first.

Sugarbag is meant to stand alone, so anyone can run it:

- Nothing here may name one particular setup: no real names, email addresses, host names, IP addresses or home paths. Anything specific to one install is a setting (`SUGARBAG_*`), not code.
- Standard library only. No build step and no outside scripts in the page. `md.js` is a small Markdown reader of its own on purpose.
- Colours are tokens in `static/style.css`. Keep phone and desktop both working, in light and dark.
- The page's security rules forbid inline scripts and `style=""` attributes. Set styles from JavaScript properties or use classes.
- New API route: add it to the README table and to `sugarbag_test.py`.
- Everything typed by a person goes through `esc()` or `mdToHtml()` in `app.js`.
- The database only ever grows: a change to it is an `ALTER TABLE ... ADD` in `upgrade()`, never a drop, so people keep their data.
- A release bumps `VERSION` in `sugarbag.py` and adds a `CHANGELOG.md` entry.
- No new feature without someone missing it. See "Left out on purpose" in the README.
