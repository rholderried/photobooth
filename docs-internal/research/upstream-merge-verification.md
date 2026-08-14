---
title: Upstream merge verification — real-hardware smoke test
date: 2026-08-09
tags: [photobooth, upstream-merge, testing-methodology, csrf, collage]
outcome: merged to production, verified working
---

# Upstream merge verification (2026-08-09)

## Goal

Merge 685 commits from `upstream/dev` (PhotoboothProject/photobooth) into
`production` — bringing in a large security-hardening pass (CSRF, path
traversal, shell injection fixes, session hardening) — **without** touching
the live Apache-served booth until the merge was proven safe, and without
reintroducing the PHP-error/JSON-corruption bug that was already fixed and
merged earlier (`536bdc2f`).

The core risk: `/var/www/html` *is* the live docroot. Apache/mod_php reads
PHP files directly off disk on every request — there's no build/deploy step
separating "checked out" from "live." Anything landing on `production` in
that directory is live immediately.

---

## Setup: isolated git worktree

```bash
git worktree add /home/roman/photobooth-upstream-catchup -b upstream-catchup production
```

A worktree gives a second working directory sharing the same `.git` object
store, checked out on its own branch — so the merge, `composer install`,
`npm install`, and build could all happen without ever touching the files
Apache was actively serving out of `/var/www/html`. `production` kept
serving normally throughout.

## Merge conflicts (3 files) and how each was resolved

```bash
cd /home/roman/photobooth-upstream-catchup
git merge upstream/dev --no-edit
```

| File | Nature of conflict | Resolution |
|---|---|---|
| `.gitignore` | Both sides added different entries at the same location | Kept both blocks (additive, no real conflict of intent) |
| `lib/boot.php` | Upstream's version still sets `display_errors=1` when `dev.loglevel > 0` — the exact pattern that caused the original JSON-corruption bug. Our fix had removed that entirely. | Kept our fix's intent (`display_errors` forced off unconditionally) while adopting upstream's `else`-branch structure for `error_reporting()` |
| `src/Collage.php` | Not a real textual conflict so much as two completely different implementations colliding — production still had the old hardcoded per-layout `switch` statement; upstream had fully replaced it with a dynamic JSON-driven layout system (`getCollageConfigPath()`, layouts loaded from `template/collage/{orientation}/*.json`) | Took upstream's version wholesale, after confirming: (a) collage mode wasn't configured/active in production's `my.config.inc.php` at all, (b) `getPictureOptions()` (the old function) had exactly one caller — itself — so nothing else depended on it, and (c) upstream ships equivalent JSON layouts for every named layout production had (verified `3+1-1.json`'s ratios byte-for-byte match the old hardcoded `'3+1'` case) |

The `Collage.php` situation was the actual scope-defining moment — it looked
like a 3-line conflict but was hiding a full subsystem rewrite. Worth calling
out because a "just take theirs" resolution without checking for active
usage first could have silently broken collage generation the moment anyone
enabled it.

## Build parity with the real deployment

```bash
composer install --no-interaction        # main app: 36/36 packages, clean
# nested `tools:install` post-install script failed — pre-existing quirk in
# the system-wide `composer` binary recursing under PHP 8.4, unrelated to
# the merge (reproduced identically on a standalone run inside tools/php-cs-fixer)
for tool in php-cs-fixer phplint phpunit phpstan; do
  (cd tools/$tool && composer install --no-interaction)
done
npm install
npx gulp                                  # sass + Tailwind + JS bundle
```

To make the smoke test reflect reality rather than bare defaults, the real
(untracked, gitignored) config was copied into the worktree:

```bash
cp /var/www/html/config/my.config.inc.php  <worktree>/config/
cp /var/www/html/welcome/.skip_welcome     <worktree>/welcome/
```

(The second file just prevents the Setup Wizard's first-run redirect from
firing in a fresh checkout — otherwise every request bounces to `/welcome`.)

## Permission-faithful test server

Rather than standing up a temporary Apache vhost (higher blast radius — touches
shared system config and requires a service reload), the app was run via
PHP's built-in dev server on loopback:

```bash
php -S 127.0.0.1:8899
```

This is only representative if the invoking user has the same access the
real request path has. Checked first:

```bash
groups www-data   # www-data video plugdev lpadmin ...
groups roman       # ... video plugdev ...        (already overlaps)
sudo -n -u www-data true && echo ok   # passwordless sudo also available
```

`roman` already shares `video`/`plugdev` group membership with `www-data`
(the groups that actually gate USB camera access), so running the dev server
as `roman` was permission-equivalent to the real deployment — no `sudo -u
www-data` wrapper needed, though it was available as a fallback.

## The actual "smoking gun": a real capture through the real pipeline

The definitive test wasn't page-load checks — it was reproducing the exact
request shape that caused the original bug, with the new CSRF layer now
sitting in front of it, against the real camera:

```bash
COOKIEJAR=/tmp/cookies.txt
CSRF=$(curl -s -c $COOKIEJAR http://127.0.0.1:8899/api/csrf.php \
  | grep -oP '"token":"\K[^"]+')
curl -s -b $COOKIEJAR -X POST -d "style=photo&csrf=$CSRF" \
  http://127.0.0.1:8899/api/capture.php
```

This exercises, in one shot:
- CSRF token issuance and validation (new, from the merge)
- `PhotoboothCapture` → the `capture` bash wrapper → `systemctl stop go2rtc`
  → `gphoto2 --capture-image-and-download` → `systemctl start go2rtc`
- JSON response formatting under a real (not synthetic) code path — the
  exact surface the original bug corrupted

**Result:**
```json
{"success":"image","file":"20260809_113805.jpg"}
```
Clean JSON, no HTML/notice text mixed in. Verified further:
- Output file: real JPEG, 4160×2768, EXIF confirms `Canon EOS RP`
- `systemctl is-active go2rtc` → `active` (clean stop/restart cycle)
- `pgrep -af gphoto2` → nothing lingering (no orphaned process, though this
  is a separate known-unfixed issue — not something this merge touches
  either way)
- Repeated once more back-to-back (~1.8s) to rule out a first-capture-only
  fluke — same clean result

This single test collapsed three separate risk questions into one
real-world result: *did the CSRF layer break normal capture flow*, *did the
Collage.php swap or any other merged change destabilize the capture path
it's adjacent to*, and *did the original display_errors fix survive being
merged with upstream's differently-structured version of the same file*.
All three: no regression.

## Promotion to production

Because the worktree's branch (`upstream-catchup`) was created directly from
`production`'s tip and then had `upstream/dev` merged on top, merging it back
was a guaranteed fast-forward — no new conflicts possible:

```bash
git merge-base --is-ancestor production upstream-catchup && echo "fast-forward safe"
cd /var/www/html && git merge upstream-catchup   # fast-forward
composer install / npm install / npx gulp         # same build steps, live tree
```

Then the exact same CSRF-token-fetch → capture POST sequence was repeated
against `http://127.0.0.1/api/capture.php` (real Apache, port 80, not the
dev server) for a final live confirmation before calling it done.

## Cleanup

```bash
git worktree remove /home/roman/photobooth-upstream-catchup
git branch -d upstream-catchup   # fully merged, safe to delete
npm audit fix                    # 3 high-severity dev-tooling vulns → 0
```

---

## Why this methodology, in short

1. **Never let a live-served checkout be the experiment.** Worktree first,
   fast-forward into place only once proven.
2. **A clean `git merge` isn't proof of compatibility** — only proof of no
   *textual* overlap. The Collage.php rewrite merged with zero conflict
   markers in most of its surrounding code; the real risk was found by
   checking whether anything still called the old code path and whether the
   data files the new path expects actually exist on this Pi.
3. **Match the real permission path, not just "does it boot."** Running as
   `roman` only worked as a faithful test because his group memberships were
   verified to overlap with `www-data`'s first.
4. **Re-create the specific historical failure, not just a generic smoke
   test.** The capture-with-CSRF test was chosen because it's the exact
   request shape that broke before (JSON response, error-prone code path) —
   a generic "does the homepage load" check would not have caught a
   regression here.
