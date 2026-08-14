# Config keys this fork depends on

**Status:** `stub` — populated as we touch them (2026-08-14)

Only keys whose behaviour we've actually confirmed. The full schema is defined
in `src/Configuration/Section/*.php`; this file is the short list that matters
operationally.

| Key | Current value | Notes |
|---|---|---|
| `preview.mode` | `url` | `url` = HTTP stream; `device_cam` = `getUserMedia` (broken on this Pi) |
| `commands.take_picture` | `capture %s` | bash wrapper `/usr/local/bin/capture` |
| `commands.preview` | — | used in `device_cam` mode |
| `protect.index` | `false` | booth UI login requirement |
| `protect.localhost_index` | `false` | …also applies to requests from the Pi itself |
| `protect.admin` | `true` | |
| `protect.localhost_admin` | `true` | |
| `protect.ip_whitelist` | `[]` | addresses exempt from protection |
| `login.rental_keypad` | `false` | enables the restricted customer tier |
| `login.rental_pin` | unset | 4 digits, must differ from `login.pin` |

See [../architecture/auth-and-access.md](../architecture/auth-and-access.md)
for how the `protect.*` and `login.*` keys interact.
