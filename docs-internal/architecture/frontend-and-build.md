# Frontend and build

**Status:** `stub` — not yet written (2026-08-14)

## The one thing you must not forget

`resources/css/` and `resources/js/` are **gitignored build output**. Editing
`assets/sass/` or `assets/js/` changes nothing on the live site until:

```bash
npx gulp        # full build
```

Also required after any branch switch in a worktree that changes sources.

## Layout

- `assets/js/` — JS sources (`core.js`, `preview.js`, `gallery.js`,
  `tools.js`, `remotebuzzer-*.js`, …)
- `assets/sass/` — SCSS sources
- `resources/{css,js}/` — build output, served
- `resources/{img,lang}/` — static assets and translations, served
- `resources/template/` — **denied** at vhost level
- `gulpfile.mjs` — build definition

## Served from `node_modules/` at runtime

jQuery, PhotoSwipe, socket.io-client, FontAwesome, material-icons,
normalize.css. These are injected by PHP asset helpers, so grepping sources
for `src="...node_modules"` finds nothing. Never block this directory —
see [../operations/web-exposure-hardening.md](../operations/web-exposure-hardening.md).

## Known frontend gotcha (fixed 2026-08-09)

`html { touch-action: none }` in `assets/sass/components/_base.scss` blocked
touch panning for the entire document — `touch-action` is computed as the
intersection across the whole ancestor chain, so no descendant override can
undo `none` set at `html`. Combined with a labwc `mouseEmulation="yes"`
compositor setting, this made gallery touch-scroll impossible. Both had to be
fixed together.

## The `HEAD` file in the repo root (build artifact, stale)

A plain-text file literally named `HEAD` sits in the repo root. It is **not**
git metadata: it is written by `npm run build:head`
(`git log --format="%h %s" -n 20 > HEAD`, `package.json:12`), is
gitignored (`.gitignore:8`), and is read by the admin debug panel's
"latest commits" view — `api/serverInfo.php:63-66` **prefers this file over
live `git log`** when it exists.

The one on the booth was created 2025-03-29 23:40 by `www-data` (the
original install) and never regenerated, so the debug panel shows upstream
commits from March 2025, not the fork's real state. Side effect: it makes
`git show HEAD` / `git diff HEAD` ambiguous ("both revision and filename") —
use `git show HEAD --` or a hash. Web access is denied (`/HEAD` → 403,
measured 2026-09-29). **Deleted 2026-09-29**; the debug panel now falls back
to live `git log`. If it reappears (e.g. after running upstream's build/pack
scripts), it is safe to remove again with `npm run clean:head`.

## To document

- What `npx gulp` actually produces and how cache-busting `?v=` hashes work
- `ajaxWithCsrf()` in `tools.js` and the CSRF client flow
- How `assets/js/admin/` differs from the main bundle
