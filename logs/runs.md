# Wendy Foils run log

2026-07-04 | daily | FAILED - forecast fetch blocked | Open-Meteo (api.open-meteo.com, ensemble-api.open-meteo.com, marine-api.open-meteo.com) all returned 403 via the sandbox egress proxy (org policy denial, not a transient error - confirmed on 2 consecutive runs). All 4 spots returned zero data; wendy.py's own "no foil window" output is a false negative, not a real forecast. No calendar invite sent. Needs proxy allowlist fix for open-meteo.com hosts before next scheduled run.
