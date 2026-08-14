# Web exposure hardening (Apache vhost)

**Status:** `current` — verified 2026-08-14
**Tracked by git:** ❌ **NO.** Lives at `/etc/apache2/sites-available/000-default.conf`.
Will **not** survive a Pi reimage. Reapply from this document.

> One of ~12 pieces of system state outside this repo — full inventory in
> [untracked-system-state.md](untracked-system-state.md).

---

## The problem

`/var/www/html` is the live Apache DocumentRoot, not just a checkout. Before
2026-08-14, everything in it was public to anyone on the booth's WiFi:

```
200  /.git/config          ← entire repo + history reconstructable
200  /.git/HEAD
200  /CLAUDE.md            ← infra layout, sudo status, debug ports
200  /config/my.config.inc.php
200  /var/log/main.log
200  /private/             ← directory listing
200  /var/                 ← directory listing
```

### Root cause

Upstream **does** ship protection — seven deny-all `.htaccess` files:

```
bin/  config/  lib/  src/  template/  tools/  resources/template/
```

All of them were **inert**, because `/etc/apache2/apache2.conf` has:

```apache
<Directory /var/www/>
	Options Indexes FollowSymLinks
	AllowOverride None          ← .htaccess files are ignored entirely
	Require all granted
</Directory>
```

`AllowOverride None` means Apache never reads `.htaccess` at all. Upstream's
whole directory-protection layer was silently disabled on this install, and
`Options Indexes` additionally enabled directory listings.

This is a **packaging mismatch, not an upstream bug** — Debian/Ubuntu Apache
defaults to `AllowOverride None`, while upstream's `.htaccess` files assume
it is `All`. Any Debian-family install of this project has the same hole.

> They also use Apache **2.2** syntax (`order deny,allow` / `deny from all`),
> which on 2.4 additionally requires `mod_access_compat`. Two reasons they
> were never going to work reliably here.

## The fix

Reimplemented at **vhost level**, which does not depend on `AllowOverride`
and cannot be disabled by deleting a `.htaccess` file. Appended inside
`<VirtualHost *:80>` in `/etc/apache2/sites-available/000-default.conf`:

```apache
	# No directory listings (apache2.conf enables "Options Indexes").
	<Directory /var/www/html>
		Options -Indexes
	</Directory>

	# Source, config, tooling, state and docs: never web-reachable.
	<DirectoryMatch "^/var/www/html/(\.git|bin|config|lib|src|template|tools|var|vendor|tests?|docs|docs-internal|resources/template)(/|$)">
		Require all denied
	</DirectoryMatch>

	# Dotfiles (.git*, .env, ...) plus notes and build/dev metadata, anywhere.
	<FilesMatch "^\.|\.(md|bak|dist|neon|lock|mjs)$">
		Require all denied
	</FilesMatch>

	# Repo / build manifests at the document root.
	<FilesMatch "^(composer\.json|package\.json|package-lock\.json|phpunit\.xml|docker-compose\.yml|Dockerfile|HEAD|crowdin_config\.yml|mkdocs_remote\.yml|install-photobooth\.sh)$">
		Require all denied
	</FilesMatch>
```

Apply with:

```bash
sudo cp /etc/apache2/sites-available/000-default.conf \
        /etc/apache2/sites-available/000-default.conf.bak-$(date +%Y%m%d-%H%M%S)
# ...edit...
sudo apache2ctl configtest && sudo systemctl reload apache2
```

Backup from the original change: `000-default.conf.bak-20260814-141235`.

## ⚠️ Do NOT deny `node_modules/`

It looks like a build directory. **It is served at runtime.** The booth loads
jQuery, PhotoSwipe, socket.io, FontAwesome, material-icons and normalize.css
directly from it. Denying it breaks the entire UI.

This is easy to get wrong: those references are emitted by PHP asset helpers,
so grepping the source for `src="...node_modules"` finds **nothing**. Always
verify against the *rendered* page instead:

```bash
curl -s http://localhost/index.php | grep -oE '(src|href)="/[^"]+"'
```

Also keep served: `data/`, `resources/{css,js,img,lang}/`, `api/`, `private/`
(fonts/images/themes — the name is misleading, it holds runtime assets).

## Verification

Regression sweep — every asset the live page references must return 200:

```bash
for u in $(curl -s http://localhost/index.php \
           | grep -oE '(src|href)="/[^"]+"' \
           | sed -E 's/^(src|href)="//; s/"$//' | sed 's/?.*//' | sort -u); do
  c=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost$u")
  [ "$c" = "200" ] || echo "BROKEN: $c $u"
done
```

Result on 2026-08-14: **0 broken**, and all paths in the table above now
return 403.

## Known remaining gaps

- **No HTTPS.** All booth traffic, including the admin login POST and its
  session cookie, is plaintext on the WiFi. Relevant to the customer config
  screen and to event use generally — see
  [../decisions/0002-customer-config-access-control.md](../decisions/0002-customer-config-access-control.md).
- `data/` (guest photos) remains world-readable to anyone on the WiFi by
  design — the gallery and QR-download flows need it.
- Not audited: whether any `api/*.php` endpoint leaks configuration in its
  JSON response.
