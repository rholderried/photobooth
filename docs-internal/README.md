# Fork-internal documentation

Working knowledge of *this fork* of the Photobooth Project, written for the
person maintaining it — not end-user docs.

> **Why not `docs/`?** That directory is upstream's (mkdocs, actively
> maintained at `PhotoboothProject/photobooth`). Anything we put there
> conflicts on every upstream catch-up merge. `docs-internal/` is ours;
> upstream will never touch it.

> **Not web-served.** `/var/www/html` is the live Apache DocumentRoot, so
> files here would otherwise be public to anyone on the booth's WiFi. A vhost
> rule denies this directory — see
> [operations/web-exposure-hardening.md](operations/web-exposure-hardening.md).
> That rule is what makes it safe to write real infrastructure detail here.

## Reading order

New to the codebase? Go in this order — it follows the layer-by-layer
debugging approach used throughout this project (OS/driver → camera comms →
PHP backend → JS frontend):

1. [architecture/00-overview.md](architecture/00-overview.md) — how a request becomes a page
2. [architecture/boot-and-config.md](architecture/boot-and-config.md) — where settings come from
3. [architecture/camera-backends.md](architecture/camera-backends.md) — the one-PTP-session rule that constrains everything
4. [architecture/capture-pipeline.md](architecture/capture-pipeline.md) — trigger → photo on disk
5. [architecture/preview-architecture.md](architecture/preview-architecture.md) — live view, and why it's hard here
6. [architecture/auth-and-access.md](architecture/auth-and-access.md) — who can reach what
7. [architecture/frontend-and-build.md](architecture/frontend-and-build.md) — JS/SCSS and the gulp build

Keep [reference/php-for-python-devs.md](reference/php-for-python-devs.md) open
alongside — it collects the PHP idioms that don't map cleanly from Python.

**Rebuilding this booth from scratch?** Start instead with
[operations/untracked-system-state.md](operations/untracked-system-state.md) —
the complete inventory of configuration that lives *outside* this repo
(Apache, sudoers, systemd units, kiosk dotfiles, group memberships). None of
it survives a fresh Pi image, and the booth does not function without it.

## Layout

| Directory | Contents |
|---|---|
| `architecture/` | How subsystems work. One file per layer. |
| `reference/` | Measured facts and lookup material. Prefer *measured over documented*. |
| `decisions/` | ADRs: what we chose, what we rejected, **why**. Numbered, append-only. |
| `operations/` | Live-system state that is **not** in git (Apache, systemd, dotfiles). |
| `research/` | Session notes from open investigations. |

## Conventions

- **Status banner on every file.** Each doc starts with `Status:` — one of
  `stub`, `partial`, `current`, or `superseded`, plus the date last verified.
  A stub that pretends to be complete is worse than no file.
- **Cite the code.** Link `path/to/file.php:123` rather than paraphrasing, so
  a reader can always check the source of truth.
- **Measured beats documented.** Where a manual and the actual hardware
  disagree, record what the hardware did and the command used to prove it.
- **ADRs are append-only.** Superseding a decision means a *new* ADR that
  links back, never editing the old one.
- **Flag untracked state.** Anything living outside this git repo (Apache
  vhost, systemd units, `~/.config/labwc/rc.xml`) must be marked as such —
  it will not survive a Pi reimage on its own.

## How this stays current

These docs are updated *in the same session as the work they describe*, as a
standing instruction in `CLAUDE.md`. There is no background process — nothing
updates itself between sessions. If a doc looks stale, check its `Status:`
date against recent git history.
