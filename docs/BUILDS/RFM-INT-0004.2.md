# RFM-INT-0004.2 — Studio auth gateway fix

## Problem
`/studio-login` and `/studio/*` were still intercepted by the global API-token dependency before the Studio router could run its own sign-in/cookie logic. Closing the browser therefore produced `{"detail":"Unauthorized"}` even after RFM-INT-0004.1.

## Fix
- Exempt `/studio-login` and `/studio` routes from the global `RUINFORM_API_TOKEN` gateway.
- Keep Studio protected by its own `RUINFORM_LAB_USER` / `RUINFORM_LAB_PASSWORD` auth and signed cookie.
- Add regression coverage proving Studio auth routes are reachable without `x-ruinform-key`, while `/v1/*` remains protected.

## Trust boundary
This does **not** make Studio public. It only lets requests reach the Studio-specific authentication layer instead of being rejected by the API gateway first.
