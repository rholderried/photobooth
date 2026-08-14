# Network topology

**Status:** `current` — verified 2026-08-14
**Tracked by git:** ❌ No — this is physical/hardware setup plus router config.

## Shape

The booth contains its **own router**, which provides the access point. The Pi
does **not** run the AP itself.

```
       ┌──────────────────── booth enclosure ────────────────────┐
       │                                                         │
       │   ┌───────────┐   WiFi (AP)                             │
   ────┼───┤  Router   ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─►  customer / guest   │
 uplink│   │ .8.1      │                       phones            │
       │   └─────┬─────┘                                         │
       │         │ ethernet                                      │
       │   ┌─────┴─────┐                                         │
       │   │  Pi 5     │  eth0 192.168.8.2/24                    │
       │   │ Photobooth│  wlan0 DOWN (unused)                    │
       │   └───────────┘                                         │
       └─────────────────────────────────────────────────────────┘
```

Measured:

```
eth0     UP    192.168.8.2/24        ← DHCP-assigned
wlan0    DOWN                        ← unused
default via 192.168.8.1 dev eth0 proto dhcp
nameserver  192.168.8.1
internet: reachable
```

## Consequences

- **The Pi's `wlan0` and `hostapd` are irrelevant.** `hostapd` is masked and
  `dnsmasq` disabled *by design* — the router does that job. Do not "fix"
  this. (See [untracked-system-state.md](untracked-system-state.md) §11.)
- **The booth network is self-contained**, not a venue network. "Anyone on the
  WiFi" means anyone given the booth's WiFi credentials — a much smaller and
  more controlled set than a public venue SSID. This is the assumption the
  customer config screen's threat model rests on.
- **The router has a WAN uplink** (internet was reachable at time of test), so
  the booth network is not fully air-gapped.

## ⚠️ The Pi's address is DHCP-assigned

`proto dhcp` — `192.168.8.2` is a lease, not a static address. Anything that
hardcodes it (a QR code, a bookmarked config-screen URL, printed setup
instructions for the customer) can break after a lease expiry or a router
reboot.

Before the customer config screen ships, pick one:

1. **DHCP reservation** on the router for the Pi's MAC — simplest, keeps
   everything else unchanged.
2. **Static address** on `eth0` — robust, but must stay outside the router's
   DHCP pool.
3. **mDNS / hostname** (`photobooth.local`) so the customer never sees an IP
   at all. Best UX by far; needs Avahi working and the client device
   supporting mDNS (iOS/macOS yes, Android historically patchy).

Option 3 layered on 1 or 2 is the sensible target — a customer should be
typing a name, not four octets.

## Related subsystems on this network

- **Printer pipeline**: Pi → CUPS → SSH → Windows PC → DNP DS-RX1. The Windows
  PC sits on this same network. Out of scope here; noted so its addressing
  isn't forgotten when changing the Pi's.

## Open / unverified

- Router make, model and admin access — not recorded.
- Whether guests and the renting customer share one SSID, or the router
  provides a separate guest network. Matters for the config screen: if guests
  are on the same SSID, the rental PIN is the *only* thing separating a guest
  from the setup UI.
- Whether the uplink is venue-provided or a dedicated modem — affects whether
  the booth is usable at a venue with no internet.
