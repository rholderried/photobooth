# Overview — how a request becomes a page

**Status:** `stub` — not yet written (2026-08-14)

Intended contents: the request lifecycle from URL to rendered HTML, and the
map of which directory does what.

## Known entry points

| Path | Role |
|---|---|
| `index.php` | Booth main UI (the kiosk page) |
| `admin/` | Admin panel — `admin/admin_boot.php` gates it |
| `login/` | Login, keypad, logout, menu |
| `gallery/`, `slideshow/`, `chroma/`, `manual/`, `welcome/` | Secondary UIs |
| `api/*.php` | JSON/AJAX endpoints (one file per operation) |
| `lib/boot.php` | Bootstrap — included by nearly every page |
| `src/` | PSR-4 classes, namespace `Photobooth\` |
| `assets/` → `resources/` | JS/SCSS sources → gulp build output |

## Directory-level facts already established

- `/var/www/html` **is** the live Apache DocumentRoot, not just a checkout.
  Never `git checkout` another branch here; use `git worktree`.
- `resources/css/` and `resources/js/` are **gitignored build output**.
  Rebuild with `npx gulp` after editing `assets/`.
- `node_modules/` is served at runtime — see
  [../operations/web-exposure-hardening.md](../operations/web-exposure-hardening.md).

## To document

- What `lib/boot.php` actually sets up, and in what order
- How `api/*.php` endpoints are dispatched and what they share
- Where templates live and how views are rendered
- Request flow diagram
