# PHP idioms for a Python developer

**Status:** `partial` — grows as we hit things. Seeded 2026-08-14.

Collected as they come up in *this* codebase. Not a PHP tutorial — just the
places where a Python mental model quietly gives the wrong answer.

## `??` — null coalescing

```php
$pin = $login['rental_pin'] ?? null;
```

Yields the right operand if the left is `null` **or undefined**, without
emitting a notice. Closest to `d.get('k', default)`.

Distinct from `?:` (Elvis), which falls back on any *falsy* value — so `0`,
`''` and `'0'` trigger the fallback. For config flags that can legitimately be
`0`, `??` is correct and `?:` is a bug.

## `empty()` vs `isset()` vs truthiness

- `isset($x)` — set and not null.
- `empty($x)` — unset, null, `false`, `0`, `0.0`, `''`, `'0'`, or `[]`.

Note **`'0'` is falsy in PHP** — a string that Python considers truthy. Real
consequence: a config value of `'0'` read from a form submission is `empty()`.

`!empty($_SESSION['rental'])` (as in `api/shellCommand.php:17`) is the safe
"is this flag on" idiom, because it doesn't warn when the key is absent.

## `===` vs `==`

`==` does type juggling; `===` compares type *and* value. This codebase uses
`$_SESSION['auth'] === true` deliberately — with `==`, any truthy value
(`1`, `"yes"`) would authenticate. **Always `===` for auth checks.**

## Arrays are ordered hash maps

One type covers both list and dict:

```php
['a', 'b']              // keys 0, 1
['login' => ['pin' => …]]  // string keys
```

Nested config is just nested arrays — hence `$config['login']['rental_pin']`.

## `password_verify()` / `hash_equals()`

- `password_verify($plain, $hash)` — bcrypt/argon comparison, constant-time.
- `hash_equals($known, $user)` — constant-time string compare, used for
  plaintext PINs to avoid timing leaks.
- `password_get_info($s)` returns `algo => 0` for a non-hash, which is how
  `AdminKeypad::isHashedPin()` distinguishes stored plain PINs from hashed
  ones.

Never compare secrets with `==`/`===` — both short-circuit and leak timing.

## Superglobals

`$_SESSION`, `$_POST`, `$_GET`, `$_SERVER` are implicit globals available in
any scope without declaration — no import, no parameter passing. `$_SERVER`
holds request metadata (`REMOTE_ADDR`, `SERVER_ADDR`), which is how the
localhost-vs-LAN distinction in `protect.localhost_*` is made.

## `require_once` executes, it does not import

```php
require_once '../lib/boot.php';
```

Runs the file top-to-bottom *in the current scope*. Variables it defines
(notably `$config`) simply appear as locals afterwards. There is no namespace
or explicit export — this is why `$config` seems to materialise from nowhere
at the top of nearly every page.

## Namespaces vs autoloading

`use Photobooth\Service\ApplicationService;` is a compile-time alias, not an
import — it does **not** load anything. Loading is Composer's PSR-4
autoloader, mapping `Photobooth\Utility\AdminKeypad` → `src/Utility/AdminKeypad.php`.
Adding a class to `src/` requires the directory layout to match the namespace,
or the autoloader won't find it.

## Deprecation notices can corrupt output

PHP writes notices into the **response body**. If `display_errors` is on, a
deprecation notice inside a JSON endpoint prepends HTML to the payload and
breaks `JSON.parse` client-side — the exact cause of the previously-fixed
collage-assembly bug under PHP 8.4. Guard: never let `display_errors` turn on
in `lib/boot.php`.

There is no Python equivalent; a `DeprecationWarning` goes to stderr and is
invisible to the caller. In PHP it is part of the response.
