# AGENTS.md: Sugarbag

Guide for `services/sugarbag/`. Read root `AGENTS.md` first.

Sugarbag will become its own public repo, so this folder must stand alone:

- Nothing here may name the house: no real names, addresses or host paths. Deployment wiring belongs outside this folder.
- Standard library only. No build step and no outside scripts in the page. `md.js` is a separate copy from the wiki's on purpose.
- Colours are tokens in `static/style.css`. Keep phone and desktop both working, in light and dark.
- The page's security rules forbid inline scripts and `style=""` attributes. Set styles from JavaScript properties or use classes.
- New API route: add it to the README table and to `sugarbag_test.py`.
- Everything typed by a person goes through `esc()` or `mdToHtml()` in `app.js`.
- No new feature without someone missing it. See "Left out on purpose" in the README.
