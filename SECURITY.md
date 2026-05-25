# Security Policy

## Supported versions

Only the latest version on `main` is actively maintained.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Send a description to: **tides-mobile.human695@passmail.com**

Include:
- A description of the vulnerability and potential impact
- Steps to reproduce
- Any suggested fix if you have one

You can expect an acknowledgement within a few days.

## Scope

This app:
- Makes only outbound HTTPS requests to NOAA CO-OPS (`api.tidesandcurrents.noaa.gov`) and NWS (`api.weather.gov`) — both public APIs, no authentication
- Stores only station favorites in a local `~/.config/tides_favorites.json` file
- Contains no user accounts, no backend, and no analytics
- Has zero third-party dependencies

Areas of interest:
- Unsafe handling of API responses that could affect the local filesystem
- Argument parsing issues that could lead to unexpected behavior
