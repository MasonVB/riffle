#!/usr/bin/env python3
"""More of the machine, chosen for what would explain a freeze.

    sudo cp telemetry_v2.py /opt/riffle/
    sudo python3 /opt/riffle/telemetry_v2.py
    sudo systemctl restart riffle-dash

WHAT WAS MISSING

The first version read every temperature sensor but only an AVERAGE clock and
a load average. That cannot tell thermal throttling from being busy, which is
the distinction the last four freezes turn on.

ADDED, IN ROUGHLY THE ORDER THEY WOULD EXPLAIN A FREEZE

  per-core usage        computed from /proc/stat between samples. One core
                        pinned while five idle is a stuck thread; six at 100%
                        is honest work.
  per-core MHz          six cores at 800 MHz under load is throttling. The
                        average hid exactly this.
  throttle counters     /sys/.../thermal_throttle — the CPU's own record of
                        having protected itself, monotonic since boot, so a
                        rising count between two samples is proof rather than
                        inference.
  fan RPM               hwmon fan*_input. A fan that stopped explains a freeze
                        with no software cause at all.
  process memory        RSS for llama-server and the python processes. The
                        difference between "the box ran out" and "one process
                        grew".
  disk I/O              /proc/diskstats deltas, including time spent in I/O.
                        With swap off this should be near zero during
                        generation; if it is not, something is paging.
  network               /proc/net/dev deltas. Least likely to explain a
                        freeze, but you asked, and it is four lines.

STILL NOT COLLECTED, AND WHY

  SMART / drive health  needs smartctl as root; the dashboard has no
                        privileges by design and I would rather leave that
                        than reopen it. Run `sudo smartctl -a /dev/nvme0n1`
                        by hand if the NVMe becomes a suspect.
  ECC error counts      the EDAC interface reports nothing on non-ECC memory,
                        which is what is in this machine. Silent corruption
                        would not appear here — memtest remains the only
                        instrument for that.
  peripherals           USB and PCI enumeration is static; it would be the
                        same string 1,440 times a day. If a device drops out,
                        the kernel says so in the journal, which the dump
                        already captures.

Backups written as .bak-telv2.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
TEL = f"{RIFFLE}/agent/telemetry.py"

ADDITIONS = '''

# --------------------------------------------------------------- more detail
# Everything below is a delta between samples, so each function keeps its last
# reading in a module global. A single reading of a monotonic counter says
# nothing; the difference between two says what happened in that minute.

_LAST = {}


def fans():
    """hwmon fan*_input. A fan that stopped explains a freeze with no software
    cause, and nothing else in this file would show it."""
    out = {}
    for p in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            name = open(os.path.join(p, "name")).read().strip()
        except OSError:
            continue
        for f in sorted(glob.glob(os.path.join(p, "fan*_input"))):
            try:
                rpm = int(open(f).read().strip())
            except (OSError, ValueError):
                continue
            lbl = f.replace("_input", "_label")
            try:
                key = open(lbl).read().strip()
            except OSError:
                key = os.path.basename(f).replace("_input", "")
            out[f"{name}.{key}"] = rpm
    return out


def cores():
    """Per-core usage and clock.

    Usage comes from /proc/stat, which is cumulative since boot — so it is
    only meaningful as a difference against the previous sample. The first
    call after a restart returns clocks but no percentages, and says so rather
    than reporting zero.
    """
    now, out = {}, {"usage": {}, "mhz": {}, "throttle": {}}
    try:
        for line in open("/proc/stat"):
            if not line.startswith("cpu") or line.startswith("cpu "):
                continue
            f = line.split()
            idle = int(f[4]) + int(f[5])
            total = sum(int(x) for x in f[1:11])
            now[f[0]] = (idle, total)
    except (OSError, ValueError, IndexError):
        return out

    prev = _LAST.get("cpustat")
    _LAST["cpustat"] = now
    if prev:
        for k, (idle, total) in now.items():
            if k not in prev:
                continue
            di, dt_ = idle - prev[k][0], total - prev[k][1]
            if dt_ > 0:
                out["usage"][k] = round(100.0 * (dt_ - di) / dt_, 1)
    else:
        out["usage"] = "first sample since restart; no interval to compare"

    for d in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*")):
        n = os.path.basename(d)
        try:
            khz = int(open(os.path.join(d, "cpufreq/scaling_cur_freq")).read())
            out["mhz"][n] = round(khz / 1000)
        except (OSError, ValueError):
            pass
        # Monotonic since boot. A count that RISES between two samples is the
        # CPU saying it protected itself, which is evidence rather than a guess.
        for kind in ("core_throttle_count", "package_throttle_count"):
            try:
                v = int(open(os.path.join(d, "thermal_throttle", kind)).read())
                if v:
                    out["throttle"][f"{n}.{kind}"] = v
            except (OSError, ValueError):
                pass
    return out


def processes(names=("llama-server", "python3")):
    """RSS per process. Tells "the box ran out" from "one process grew"."""
    out = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            comm = open(os.path.join(d, "comm")).read().strip()
            if comm not in names:
                continue
            rss = 0
            for line in open(os.path.join(d, "status")):
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) // 1024
                    break
            cmd = open(os.path.join(d, "cmdline"), "rb").read()
            cmd = cmd.replace(b"\\x00", b" ").decode("utf-8", "replace")[:70].strip()
            out[f"{comm}:{os.path.basename(d)}"] = {"rss_mb": rss, "cmd": cmd}
        except (OSError, ValueError, IndexError):
            continue
    return out


def diskio():
    """/proc/diskstats deltas. With swap off this should be near zero during
    generation; if it is not, something is paging and that is the finding."""
    now, out = {}, {}
    try:
        for line in open("/proc/diskstats"):
            f = line.split()
            if len(f) < 14:
                continue
            dev = f[2]
            if not (dev.startswith("nvme") or dev.startswith("sd")):
                continue
            if dev[-1].isdigit() and "nvme" not in dev:
                continue
            now[dev] = (int(f[5]), int(f[9]), int(f[12]))   # sectors r, w, io ms
    except (OSError, ValueError, IndexError):
        return out
    prev = _LAST.get("diskstats")
    _LAST["diskstats"] = now
    if not prev:
        return {"note": "first sample since restart"}
    for dev, (r, w, ms) in now.items():
        if dev not in prev:
            continue
        out[dev] = {"read_mb": round((r - prev[dev][0]) * 512 / 1e6, 1),
                    "write_mb": round((w - prev[dev][1]) * 512 / 1e6, 1),
                    "io_ms": ms - prev[dev][2]}
    return out


def network():
    now, out = {}, {}
    try:
        for line in open("/proc/net/dev").read().splitlines()[2:]:
            name, _, rest = line.partition(":")
            f = rest.split()
            name = name.strip()
            if name == "lo" or len(f) < 10:
                continue
            now[name] = (int(f[0]), int(f[8]), int(f[2]), int(f[10]))
    except (OSError, ValueError, IndexError):
        return out
    prev = _LAST.get("netdev")
    _LAST["netdev"] = now
    if not prev:
        return {"note": "first sample since restart"}
    for k, (rx, tx, rerr, terr) in now.items():
        if k not in prev:
            continue
        out[k] = {"rx_mb": round((rx - prev[k][0]) / 1e6, 2),
                  "tx_mb": round((tx - prev[k][1]) / 1e6, 2),
                  "errors": (rerr - prev[k][2]) + (terr - prev[k][3])}
    return out
'''


def main():
    s = open(TEL).read()
    if "def fans(" in s:
        print("  already present: the extra collectors")
    else:
        if "import glob" not in s:
            sys.exit("  FAILED: telemetry.py does not import glob as expected.")
        anchor = "def memory():"
        if anchor not in s:
            sys.exit("  FAILED: could not find memory() in telemetry.py.")
        shutil.copy(TEL, f"{TEL}.bak-telv2")
        s = s.replace(anchor, ADDITIONS.strip() + "\n\n\n" + anchor, 1)
        open(TEL, "w").write(s)
        print("  added fans(), cores(), processes(), diskio(), network()")

    # wire them into both the sample and the dump
    s = open(TEL).read()
    old = ('    payload = {"mem": memory(), "cpu": cpu(), "temps": temps(),\n'
           '               "disk": disks(), "services": services(),\n'
           '               "composer": model_health(), "agent": agent_state(state, cfg)}')
    new = ('    payload = {"mem": memory(), "cpu": cpu(), "temps": temps(),\n'
           '               "fans": fans(), "cores": cores(),\n'
           '               "procs": processes(), "diskio": diskio(),\n'
           '               "net": network(),\n'
           '               "disk": disks(), "services": services(),\n'
           '               "composer": model_health(), "agent": agent_state(state, cfg)}')
    if '"fans": fans()' in s:
        print("  already present: sample carries the new readings")
    elif old in s:
        open(TEL, "w").write(s.replace(old, new, 1))
        print("  sample() now carries fans, cores, procs, diskio, net")
    else:
        sys.exit("  FAILED: sample()'s payload is not what I expected.")

    s = open(TEL).read()
    old_d = ('    payload = {"note": note[:2000],\n'
             '               "mem": memory(), "cpu": cpu(), "temps": temps(),\n'
             '               "disk": disks(), "services": services(),\n'
             '               "composer": model_health(), "agent": agent_state(state, cfg)}')
    new_d = ('    payload = {"note": note[:2000],\n'
             '               "mem": memory(), "cpu": cpu(), "temps": temps(),\n'
             '               "fans": fans(), "cores": cores(),\n'
             '               "procs": processes(), "diskio": diskio(),\n'
             '               "net": network(),\n'
             '               "disk": disks(), "services": services(),\n'
             '               "composer": model_health(), "agent": agent_state(state, cfg)}')
    if old_d in s:
        open(TEL, "w").write(s.replace(old_d, new_d, 1))
        print("  dump() now carries them too")
    elif '"fans": fans(),\n               "cores": cores(),\n               "procs"' in s:
        print("  already present: dump carries the new readings")
    else:
        print("  NOTE: dump()'s payload differs; it keeps the original set")

    # richer one-line summary in the log panel
    dash = f"{RIFFLE}/agent/dash.py"
    d = open(dash).read()
    old_line = ('            line = (f"{mem.get(\'PctUsed\', \'?\')}% mem, "\n'
                '                    f"{mem.get(\'MemAvailable\', \'?\')}MiB free, "\n'
                '                    f"load {cp.get(\'load1\', \'?\')}, "\n'
                '                    f"{cp.get(\'mhz_avg\', \'?\')}MHz"\n'
                '                    + (f", {hot}\\u00b0C" if hot is not None else ""))')
    new_line = ('            co = body.get("cores") or {}\n'
                '            us = co.get("usage") if isinstance(co.get("usage"), dict) else {}\n'
                '            busy = round(sum(us.values()) / len(us), 0) if us else None\n'
                '            fan = max((body.get("fans") or {}).values(), default=None)\n'
                '            thr = len(co.get("throttle") or {})\n'
                '            line = (f"{mem.get(\'PctUsed\', \'?\')}% mem, "\n'
                '                    f"{mem.get(\'MemAvailable\', \'?\')}MiB free, "\n'
                '                    + (f"cpu {busy:.0f}%, " if busy is not None else "")\n'
                '                    + f"{cp.get(\'mhz_avg\', \'?\')}MHz"\n'
                '                    + (f", {hot}\\u00b0C" if hot is not None else "")\n'
                '                    + (f", fan {fan}" if fan else "")\n'
                '                    + (f", THROTTLED x{thr}" if thr else ""))')
    if "THROTTLED x" in d:
        print("  already present: richer summary line")
    elif old_line in d:
        shutil.copy(dash, f"{dash}.bak-telv2")
        open(dash, "w").write(d.replace(old_line, new_line, 1))
        print("  log panel summary now shows cpu%, fan and throttling")
    else:
        print("  NOTE: the summary line differs; the panel keeps the old one")

    import ast
    ast.parse(open(TEL).read())
    ast.parse(open(dash).read())
    print("\n  modules parse.")

    sys.path.insert(0, RIFFLE)
    from agent import telemetry
    import importlib
    importlib.reload(telemetry)
    print("\n  a live reading from this machine:")
    print("    fans:", telemetry.fans() or "(no fan sensors exposed)")
    c = telemetry.cores()
    print("    per-core MHz:", c["mhz"] or "(not exposed)")
    print("    throttle counters:", c["throttle"] or "none since boot")
    telemetry.cores()
    import time
    time.sleep(1.2)
    print("    per-core usage:", telemetry.cores()["usage"])
    print("    processes:", {k: v["rss_mb"] for k, v in
                             list(telemetry.processes().items())[:4]} or "(none)")
    print("""
  Next:
    sudo systemctl restart riffle-dash

    cd /opt/riffle && git add -A
    git commit -m "telemetry: fans, per-core usage and clocks, throttle counters, disk io, network, process rss"
    git push
""")


if __name__ == "__main__":
    main()
