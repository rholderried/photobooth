# Authentication & access control

**Status:** `partial` — verified 2026-08-14. Covers the session/tier model and
`protect.*`. Does not yet cover the CSRF implementation in depth.

## Two session tiers

The app has **two** independent privilege levels, both plain session flags:

| Flag | Meaning | Set by |
|---|---|---|
| `$_SESSION['auth']` | Full admin | password login, or admin PIN |
| `$_SESSION['rental']` | Restricted "renter/customer" tier | rental PIN only |

Set in [`src/Utility/AdminKeypad.php:9-19`](../../src/Utility/AdminKeypad.php#L9-L19):

```php
if (self::isValidPin($userPin, $login['pin'] ?? null)) {
    session_regenerate_id(true);
    $_SESSION['auth'] = true;
    return true;
} elseif (($login['rental_keypad'] ?? false) && self::isValidPin($userPin, $login['rental_pin'] ?? null)) {
    session_regenerate_id(true);
    $_SESSION['rental'] = true;
    return true;
}
```

> **PHP note:** `??` is the null-coalescing operator — `$a ?? $b` yields `$b`
> if `$a` is null *or not set at all*, without emitting a warning. It is the
> idiomatic guard for optional config keys, roughly Python's
> `d.get('k', default)`. See
> [../reference/php-for-python-devs.md](../reference/php-for-python-devs.md).

The **rental tier came from upstream** in the 2026-08-09 catch-up merge. Config
keys are `login.rental_keypad` (bool) and `login.rental_pin` (4 digits).
Upstream describes it as: *"Keypad for rental login. After logging in, Info and
some admin buttons are available."* It **defaults to off** and has never been
manually exercised on this booth.

This is the natural foundation for a customer-facing config screen — see
[../decisions/0002-customer-config-access-control.md](../decisions/0002-customer-config-access-control.md).

### PIN storage

PINs may be stored **plain or hashed**; `AdminKeypad::isValidPin()` detects
which via `password_get_info()` and dispatches to `password_verify()` or
`hash_equals()`. `api/admin.php` refuses to enable the rental keypad if its PIN
isn't 4 digits or collides with the admin PIN.

## Page protection: `protect.*`

[`src/Configuration/Section/ProtectConfiguration.php`](../../src/Configuration/Section/ProtectConfiguration.php):

| Key | Default | Effect |
|---|---|---|
| `admin` | `true` | Admin panel requires login |
| `localhost_admin` | `true` | …*also* when requested from localhost |
| `index` | `false` | Booth main page requires login |
| `localhost_index` | `false` | …also from localhost |
| `manual` | `false` | Manual page requires login |
| `localhost_manual` | `false` | …also from localhost |
| `index_redirect` | `'login'` | Where to send unauthenticated visitors |
| `ip_whitelist` | `[]` | Addresses exempt from protection |

The `localhost_*` variants are the key design lever here. Evaluated in
[`src/Utility/LoginMenuUtility.php:23-32`](../../src/Utility/LoginMenuUtility.php#L23-L32):
if the page is protected but `localhost_*` is false **and** the request comes
from the server's own address, access is granted without a session.

### Why that matters for this booth

**The kiosk browser runs on the Pi itself** (Chromium via
`~/.config/labwc/autostart`), so its requests originate from `127.0.0.1`.
Every customer or guest phone arrives from a *different* LAN address.

That maps exactly onto the access split we want:

```
protect.index           = true     → booth UI requires auth...
protect.localhost_index = false    → ...except from the kiosk itself
```

Result: the kiosk works untouched, while a phone on the WiFi cannot reach the
booth's remote-control surface.

**Caveat:** if the QR-code download flow is used, guests' phones must still
reach the gallery/download endpoints. So this is a per-route policy, not a
blanket lock. Not yet mapped — do that before relying on it.

## Login throttling

[`login/index.php`](../../login/index.php) rate-limits by IP *and* session:
10 attempts per 5-minute window, persisted to
`var/run/login_throttle.json` so that clearing cookies doesn't reset it, plus a
300 ms `usleep` on failure. Added in the 2026-08-09 hardening merge.

## ⚠️ UI hiding is not access control

`login/menu.php` hides links based on these flags, but the booth pages are
plain URLs under the DocumentRoot. Anyone on the WiFi can request
`/index.php` or `/api/*.php` directly and get full remote control — trigger
captures, browse the guest gallery, call `api/deletePhoto.php`. Any
customer-facing feature must be enforced **server-side** (session checks +
`protect.*` + vhost rules), never by hiding UI.

Related: [../operations/web-exposure-hardening.md](../operations/web-exposure-hardening.md).

## Not yet documented

- CSRF token lifecycle (`api/csrf.php`, `ajaxWithCsrf()` in `assets/js/tools.js`)
- Which `api/*.php` endpoints check which tier (`api/shellCommand.php:16-17`
  is the only one confirmed to distinguish `auth` from `rental`)
- No HTTPS: login POSTs and session cookies are plaintext on the WiFi
