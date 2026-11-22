# Security

## Reporting a problem

Please report security problems privately: open the **Security** tab of this repository and press **Report a vulnerability**. Do not open a public issue for them.

This is a personal project, maintained in spare time. Replies are best-effort, but every report gets read. Fixes go into the newest release only.

## How Sugarbag is meant to be run

Sugarbag is for one person or a small team who trust each other enough to share a board:

- It listens on `127.0.0.1` unless you set `SUGARBAG_BIND`. Keep it on your own machine or a private network (a VPN such as WireGuard or Tailscale), or put a proxy with https in front and set `SUGARBAG_SECURE_COOKIE=1`.
- It has no https of its own. Over plain http on an open network, passwords and session cookies can be read on the way.
- Every page of data needs a login. Passwords are hashed with scrypt; sessions and API tokens are stored only as fingerprints.
- A signed-in browser's write requests must come from Sugarbag's own page, so another website cannot act as you.
- The page's security rules (Content-Security-Policy) allow no inline or outside scripts, so text in an issue cannot run as code.

## In scope

- Getting in without a password or token, or keeping access after being switched off.
- A viewer changing anything, a member doing what only an admin may, or a member deleting other people's work.
- Reading another person's API tokens.
- Text in an issue, comment or name running as script in someone else's browser.
- Another website making a signed-in browser change the board.
- Losing or corrupting data through the API.

## Out of scope

- Anything that needs Sugarbag served over plain http on an untrusted network, against the advice above.
- An admin doing admin things: they can add people, change roles and delete anything.
- Someone who can already read the database file or the server's environment.
- Load from many requests at once: it is built for a small team, not the open internet.
