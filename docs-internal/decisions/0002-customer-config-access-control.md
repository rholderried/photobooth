# ADR 0002 — Customer config screen: reuse the `rental` tier

**Status:** `proposed` (2026-08-14) — design agreed in principle, not implemented

## Context

Customers renting the booth must set it up themselves: connect a phone to the
booth's WiFi, see a live camera view, and set focus. They must **not** be able
to reach the booth's main pages, which would give them remote control over a
live booth (trigger captures, browse the guest gallery, delete photos) —
unless they are the administrator.

## Decision

**Do not build a new authentication tier.** Extend the `rental` tier that
upstream already ships (see
[../architecture/auth-and-access.md](../architecture/auth-and-access.md)):
`$_SESSION['rental']`, gated by a separate 4-digit PIN, distinct from the
admin PIN, already understood by `api/shellCommand.php`.

Enforce the boundary in **three independent layers**:

1. **Session tier** — the config screen accepts `rental` *or* `auth`; booth
   pages and the admin panel accept `auth` only.
2. **`protect.*` config** — `protect.index = true` with
   `protect.localhost_index = false`, exploiting the fact that the kiosk
   browser runs on the Pi (`127.0.0.1`) while customer phones never do.
3. **Vhost rules** — already in place for non-application paths
   ([../operations/web-exposure-hardening.md](../operations/web-exposure-hardening.md)).

## Rationale

- Adding a parallel auth mechanism next to freshly-hardened auth code (CSRF,
  rate limiting, path-traversal fixes merged 2026-08-09) is exactly where
  security bugs get introduced. Reusing the existing tier keeps the audit
  surface small.
- The `localhost_*` split is already implemented and tested upstream, and this
  booth's topology fits it precisely. No new mechanism to get wrong.
- Defence in depth: UI hiding alone is worthless here, since every booth page
  is a plain URL under the DocumentRoot.

## Open questions

- ⚠️ **The Pi's address is DHCP-assigned** (`192.168.8.2` via the booth's
  built-in router). The config screen needs a stable address the customer can
  reach — a DHCP reservation or static IP, ideally fronted by an mDNS name so
  they type `photobooth.local` rather than an IP. See
  [../operations/network-topology.md](../operations/network-topology.md).
- **Is the customer on the same SSID as guests?** The booth's router provides
  the AP. If guests join the same network (e.g. for QR photo downloads), the
  rental PIN is the *only* barrier between a guest and the setup UI. A
  separate guest network on the router would be a cheap, strong improvement.
- **QR-code download flow.** If guests scan a QR to download photos, their
  phones need gallery/download endpoints — so `protect.index` cannot be a
  blanket lock. The per-route policy is **not yet mapped.**
- **The rental tier is unverified.** It defaults off and has never been
  exercised on this booth. Test it before building on it.
- **What else should the customer control?** Currently scoped to focus only.
  Framing guides, countdown duration and print copies are plausible
  neighbours — deliberately not assumed.
- **No HTTPS.** The rental PIN would cross the WiFi in plaintext. Acceptable
  for a low-value PIN on a private SSID; revisit before this gates anything
  more sensitive.

## Depends on

[ADR 0001](0001-preview-architecture.md) — without a preview stream reachable
from a phone, the config screen has nothing to show.
