# RFM-INT-0004.1 — Persistent Studio Sign-In

## Problem
Direct Studio links could return `{"detail":"Unauthorized"}` after the browser was closed because HTTP Basic credentials are only cached by the browser session.

## Decision
Keep Studio private, but add an explicit Studio sign-in page and a signed, HttpOnly, Secure cookie valid for seven days. Existing HTTP Basic credentials remain supported for compatibility.

## Expected behavior
- Opening any `/studio/...` URL without a valid Studio cookie redirects to `/studio-login` instead of exposing a JSON 401 page.
- After successful sign-in, the user returns to the exact Studio URL they requested.
- The cookie never contains the password; it contains a username, expiry, and HMAC signature derived from the configured lab password.
- The `next` destination is restricted to internal `/studio/` paths.
- Closing and reopening the browser should not require signing in again until the cookie expires.

## Security
The Studio remains private. This change does not make project sessions public and does not place OpenAI, Higgsfield, database, or RUINFORM API secrets in the browser.
