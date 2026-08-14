# gphoto2 capabilities — Canon EOS RP (measured)

**Status:** `current` — measured 2026-08-14 on the actual booth camera
**Lens at time of measurement:** RF 14-35mm F4 L IS USM
**USB:** `Bus 003 Device 002: ID 04a9:32e2 Canon, Inc. Canon Digital Camera`

Everything here was measured on *this* body + lens, not read from a manual.
Re-verify after a lens change — the RF/EF distinction matters (see below).

> **Prerequisite:** nothing else may hold the camera. `go2rtc` spawns
> `gphoto2 --capture-movie` *on demand* when a client connects to the stream,
> so an idle `go2rtc` still leaves the camera free. Check with
> `pgrep -a gphoto2` before running any of these commands.

## Focus — the important finding

```bash
gphoto2 --list-config | grep -iE 'focus|lens'
```

```
/main/actions/autofocusdrive
/main/actions/manualfocusdrive
/main/actions/cancelautofocus
/main/settings/focusarea
/main/status/lensname
/main/capturesettings/focusmode
```

```bash
gphoto2 --get-config /main/actions/manualfocusdrive
```

```
Label: Drive Canon DSLR Manual focus
Type: RADIO
Current: None
Choice: 0 Near 1     Choice: 3 None
Choice: 1 Near 2     Choice: 4 Far 1
Choice: 2 Near 3     Choice: 5 Far 2
                     Choice: 6 Far 3
```

### What this means

**Focus control is relative and open-loop. There are no absolute focus ticks.**

- `Near 1/2/3` and `Far 1/2/3` are small/medium/large *nudges*. You cannot
  command an absolute position.
- **No position feedback exists anywhere in the config tree.** `Current: None`
  is the action's idle state, not a readout. There is no `focusdistance`, no
  `eosfocusinfo`.
- Consequence: a "focus distance in metres → ticks" lookup table has no
  destination to convert into. This is a libgphoto2/PTP limitation on Canon,
  not a gap in the Photobooth code. Canon's own EDSDK is relative-only too.

### Further constraints

- **`focusmode` currently offers only `Manual`** (`Current: Manual`, single
  choice) — the lens/body is in MF, so `autofocusdrive` is not usable in this
  state.
- **RF lenses are focus-by-wire.** Step size is not a fixed mechanical amount;
  it varies with position (much more travel per step near infinity) and on
  some lenses with drive speed. There is generally no hard end stop to "home"
  against, which undermines any startup-calibration scheme.
- **Focal length is not readable.** `eoszoom` / `eoszoomposition` are *liveview
  magnification* (punch-in), **not** the lens zoom ring. With a 14–35mm zoom,
  any distance↔step mapping would need a focal-length axis the system cannot
  observe.
- **`manualfocusdrive` requires liveview active** on Canon EOS. This couples
  focus control to the preview architecture — see
  [../architecture/camera-backends.md](../architecture/camera-backends.md).

### Useful for a focus UI

`eoszoom` / `eoszoomposition` give 5×/10× liveview punch-in — exactly what you
want for confirming critical sharpness on a small phone screen.

## Depth of field — why metric precision isn't needed

Full frame, f/4, CoC 0.03mm, subject at 2.5 m:

| Focal length | Near | Far | Depth |
|---|---|---|---|
| 14 mm | 1.0 m | ∞ | ∞ |
| 24 mm | 1.65 m | 5.14 m | 3.49 m |
| 35 mm | 2.02 m | 3.29 m | 1.27 m |

Even at the tight end there is a ~1.3 m in-focus zone. Someone eyeballing
sharpness on a phone lands inside that every time. A metric slider would be
false precision over a control that cannot hit it — hence the visual
nudge-based UI in
[../decisions/0001-preview-architecture.md](../decisions/0001-preview-architecture.md).

## Open question — worth measuring

Are the nudges **repeatable**? Test: drive `Near 3` ×10, then `Far 3` ×10, and
check whether focus returns to the same plane. If it does, a homing routine
becomes *conceivable* (though still fragile). If it doesn't, any
calibration-based approach is dead and visual-only is the sole option.

Not yet run — needs a working liveview to observe the result.
