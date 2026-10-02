# Print pipeline — Pi → CUPS → SSH → Windows → DNP DS-RX1

Status: current — verified 2026-10-02 (repo HEAD deployed on Pi and Windows;
test plan T1–T6 passed)

⚠️ **None of this is in the photobooth repo.** The installed files live outside
git on the Pi and the Windows PC. Since 2026-10-02 their source of truth is a
**separate repository, `~/Git/fotobox-printserver`** (local only, no remote
yet). It holds `linux/` (backend, `install.sh`, `printserver.conf`) and
`windows/` (`print-job.ps1`, `install.ps1`). After a reimage, set the chain
up from its README rather than by hand. See also
[untracked-system-state.md](untracked-system-state.md).

**Deployment state 2026-10-02 14:00:** the Pi and Windows both run repo HEAD
(`153be9f`), installed with `linux/install.sh`. The Windows `print-job.ps1` was
copied with scp; `windows/install.ps1` has never been run. The queue URI is now
`sshprint://roman@dnp-ds-rx1-pc/DS-RX1`: print server, user and Windows
printer name all come from the URI, so a different printer model only needs
a change in `linux/printserver.conf`. `JobRetryInterval 30` /
`JobRetryLimit 40` are set in `cupsd.conf`. T1 (job 636): backend start to
"Job completed" in 4 s.

## Chain

```
Photobooth api/print.php (www-data) --lp--> cupsd queue Printserver_DNP-DS-RX1 (raw)
  --> /usr/lib/cups/backend/sshprint   (runs as lp, because it is 0755 root:root)
  --scp--> roman@dnp-ds-rx1-pc:C:/temp/printjob-XXXXXX.jpg   (Windows 11 OpenSSH)
  --ssh--> powershell -File C:\Scripts\print-job.ps1 -file <remote file>
  --> Windows spooler + DNP driver --USB--> DNP DS-RX1 HS
```

| Item | Value (measured 2026-10-02) |
|---|---|
| Queue | `Printserver_DNP-DS-RX1`, `DeviceURI sshprint://roman@dnp-ds-rx1-pc/DS-RX1` (`lpstat -v` hides the `roman@`; check `printers.conf`) |
| Backend | `/usr/lib/cups/backend/sshprint`, `0755 root:root` |
| SSH key | `/var/spool/lpd/.ssh/fotobox_print` (owner `lp`, no passphrase), `known_hosts` alongside |
| Print server | `dnp-ds-rx1-pc` → `dnp-ds-rx1-pc.lan` → `192.168.8.206` (router DNS, DHCP) |
| Error policy | `ErrorPolicy retry-job` — set **both** as server default in `/etc/cups/cupsd.conf:5` and per queue in `/etc/cups/printers.conf:73` |
| Retry settings | `JobRetryInterval 30`, `JobRetryLimit 40` (since 2026-10-02; before: unset → defaults 30 s / 5) |
| Log | `LogLevel debug`, `MaxLogSize 0` (no size-based rotation) → `/var/log/cups/error_log*` |

Why the backend must stay `0755`: CUPS runs world-executable backends as the
unprivileged `lp` user, and `0700` ones as root. As root, `ssh` would look in
`/root/.ssh/` and not find the key or `known_hosts`.

## Known weakness (incident 2026-09-26)

The installed backend has no timeouts on `scp`/`ssh` and ends with an
unconditional `exit 0`:

- A half-open SSH connection (print server power-cycled mid-job) made `ssh`
  wait forever → the whole queue blocked behind job 520 until the Pi was
  rebooted.
- After the reboot, `scp`/`ssh` failed instantly (network not up yet), but the
  backend reported success → jobs 520–524 marked completed, **none printed**.

Because `retry-job` is already the policy, the only missing piece is the
backend reporting failure (exit 1) and bounding its own runtime.

## Hardened backend (installed 2026-10-02)

- `ConnectTimeout=10`, `ServerAliveInterval=5` × `ServerAliveCountMax=3`
  (dead peer detected after ~15 s), plus `timeout 60` on `scp` / `timeout 90`
  on `ssh` as a hard upper bound. `BatchMode=yes` so nothing waits on a prompt.
- Exits 1 (`CUPS_BACKEND_FAILED`) on any failure, so `retry-job` takes over.
  Never use exit 4 (`CUPS_BACKEND_STOP`) — it stops the queue whatever the
  policy says.
- `ERROR:`/`INFO:` lines on stderr appear in `error_log` and as the
  printer-state-message.
- Smoke test as `lp`, run directly without CUPS: exit 0 in 5.0 s, temp file removed.

Backups: `/usr/lib/cups/backend/sshprint.bak-2026-10-02` (set to `0644` so
CUPS device discovery doesn't run it), `/etc/cups/cupsd.conf.bak-2026-10-02`,
`/etc/cups/printers.conf.bak-2026-10-02`. Rollback: reinstall the backup with
`install -o root -g root -m 0755`. **Do not** set
`printer-error-policy=stop-printer` as part of a rollback — `retry-job` was
already the original setting.

## Windows side — `C:\Scripts\print-job.ps1` (as found 2026-10-02)

Loads the JPEG with `System.Drawing`, draws it to `PageBounds` (borderless)
on printer `DS-RX1`, sleeps 3 s, then deletes the file. It has no error
handling and never sets an exit code, so a failure on the Windows side
usually still reaches the Pi as success (weak point F6). "Success" means
*handed to the Windows spooler*; it says nothing about whether paper or
ribbon problems stopped the actual print.

## Test results (2026-10-02)

| Test | Result |
|---|---|
| T1 normal print (job 636) | completed in 4 s |
| T3 dead peer mid-upload (job 637) | incoming packets from the PC dropped with nftables during a ~10 s upload of a padded 100 MB JPEG (the image plus random bytes after the JPEG end marker, which GDI+ ignores). Backend gave up after **21 s** (`scp … rc=1`, ServerAlive). Job held 30 s, queue stayed enabled, retry after unblocking printed it once. No orphaned processes. |
| T5 retry limit (job 638, limit temporarily 2) | after the initial attempt plus 2 retries: `Job aborted after 2 unsuccessful attempts`, `job-state=aborted`, not printed, **stays aborted** after the PC comes back. Queue stays enabled. Spool file `d00638-001` kept (PreserveJobFiles default, one day), so `lp -i <id> -H restart` should rescue it. Not tested. |
| T2 PC shut down (jobs 639/640) | with the PC off, attempts fail in **1–3 s** (`scp … rc=255`: connection refused or host unreachable, faster than ConnectTimeout). Job held 30 s, queue stayed enabled. When the PC came back, A's retry fell in the same second the second job B was sent, so A printed first and B waited ~5 s behind A's attempt. Both printed, nothing lost. A new job overtaking a *held* one was **not** observed in this run. |
| T4 boot race (job 641) | ProDesk off, job queued, Pi rebooted, ProDesk switched on. A retry was running when the Pi shut down: cupsd's SIGTERM hit the backend's TERM trap (logged as "Job cancelled"), exit 1, job **kept** (not completed). Pi booted 14:21:34; first attempt 14:21:40 failed cleanly (`rc=255`) and was held. This is exactly where the wedding jobs "exited with no errors". Retried until the ProDesk was up, then printed at 14:23:06 after 5 attempts. |
| T6 queue health | after all tests: enabled, idle, nothing pending. |

Check any job's history with
`sudo ~/Git/fotobox-printserver/linux/job-log.sh <job-id>`. It flags a job
that completed without "Job handed to print server" (silently lost).

Still open (2026-10-02): cleanup of partial uploads in `C:\temp` (below);
the "new job overtakes a held job" case was never observed directly; the
backend's "Job cancelled" message also appears when cupsd is merely shutting
down; stale `Listen 192.168.178.53:631` in `cupsd.conf`.

Finding from T3: a failed upload leaves a **partial `printjob-*.jpg` in
`C:\temp`** (10 MB in the test), because `print-job.ps1` never runs for it.
Not fixed yet.

## Gotchas found while preparing the fix

- ⚠️ **`cupsd -t` is not a read-only syntax check. Never run it.** It does
  a full reload, including the queued jobs from `/var/cache/cups/job.cache`,
  and treats the directory of the `-c` file as ServerRoot. On 2026-10-02:
  - Run as `cupsd -t -c /tmp/tmp.XXXX`, it reset **`/tmp` to `0755 root:lp`**
    and created `/tmp/ppd`. After that, no user except root could create
    temp files, so the backend's `mktemp` failed and job 635 went into the
    retry loop. The harness's own `/tmp/claude-*-cwd` writes failed too.
    Repaired with `chown root:root /tmp && chmod 1777 /tmp` and by removing
    `/tmp/ppd`. If temp files fail mysteriously, check `stat -c '%a %U:%G' /tmp`
    (should be `1777 root:root`).
  - A second run, from a scratch directory without `printers.conf`, almost
    certainly purged job 635's spool file `/var/spool/cups/d00635-001`.
    The job stayed in the queue with `cannot copy job file` and had to be
    cancelled.
  `install.sh` now restarts cupsd with the new config and restores the
  backup if it does not come back.

- **Cancel orphans the transfer.** CUPS cancels a job by sending SIGTERM to the
  backend. Bash runs its `EXIT` trap on SIGTERM, but a foreground child
  (`timeout … ssh …`) is *not* killed and keeps running — a cancelled job can
  still print. Fix: run the child in the background, `wait` on it, and kill it
  from a `TERM` trap (measured with mocks 2026-10-02: orphan without the trap,
  none with it).
- **Stale CUPS listen address.** `/etc/cups/cupsd.conf:7` has
  `Listen 192.168.178.53:631` — an address from a previous network; the Pi is
  now `192.168.8.2`. Harmless for local printing (`127.0.0.1` and the socket
  are also listened on), not yet changed.
- **`powershell -Command -` runs stdin line by line**, so multi-line
  blocks (`if {…}` across lines, here-strings) silently do nothing. To send a
  whole script over SSH, use `-EncodedCommand <base64 of UTF-16LE>`, and set
  `$ProgressPreference = 'SilentlyContinue'`, or progress records arrive on
  stderr as CLIXML. The remote default shell is `cmd.exe`, which also cuts
  multi-line command strings.
- **Windows PC facts (measured 2026-10-02):** Windows 11 in German (group
  names are localized, e.g. `VORDEFINIERT\Administratoren`, so ACLs must use
  SIDs), PowerShell 5.1, LocalMachine execution policy `RemoteSigned`,
  firewall rule `OpenSSH-Server-In-TCP` on the *Private* profile only,
  `roman` is an administrator (key in
  `C:\ProgramData\ssh\administrators_authorized_keys`), printer `DS-RX1` on
  `USB001`.
- **CUPS warns raw queues are deprecated** (`cupsd -t`). Our queue has no
  PPD, so it is raw. It works on CUPS 2.4.2; it will matter on a future CUPS 3.
- **`lpoptions -p … | grep error-policy` shows nothing** for this queue — read
  `printers.conf` instead.
