# Boot and configuration

**Status:** `stub` — not yet written (2026-08-14)

## What's known

- `lib/boot.php` is included by nearly every page and makes `$config`
  available as a plain local variable (see the `require_once` note in
  [../reference/php-for-python-devs.md](../reference/php-for-python-devs.md)).
- Configuration is defined with **Symfony Config** component trees, one class
  per section under `src/Configuration/Section/` (e.g.
  `ProtectConfiguration.php`, which defines defaults declaratively).
- `lib/configsetup.inc.php` (~2800+ lines) describes the admin-panel form
  fields — labels, types, and names like `login[rental_pin]`.
- The **live** config is `config/my.config.inc.php`, which is gitignored and
  stores only values that differ from defaults. `config/config.inc.php` does
  not exist on this install.
- `config/` is denied at the vhost level and additionally carries an (inert)
  upstream `.htaccess`.

## Gotcha already burned us

PHP writes deprecation notices into the **response body**. With
`display_errors` on, a notice inside a JSON endpoint corrupts the payload —
this caused the collage-assembly bug under PHP 8.4. The fix's intent (never
let `display_errors` turn back on) lives in `lib/boot.php`; re-verify it if
that file is ever touched.

## To document

- Exact load order in `lib/boot.php`
- How Symfony Config defaults merge with `my.config.inc.php`
- How the admin panel writes config back (`api/admin.php`)
- Which config keys this fork actually depends on → `../reference/config-keys.md`
