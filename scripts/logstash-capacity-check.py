#!/usr/bin/env python3
"""Check whether Logstash on this EC2 is using the compute that is available.

Samples the Logstash monitoring API (localhost:9600) and /proc twice, INTERVAL
seconds apart, then reports CPU, per-pipeline worker utilization, backpressure,
JVM heap/GC, and (on burstable t-family instances) CPU credits and steal time.
It ends with findings that say which limit is being hit: CPU, workers, a
blocked output, heap, or throttling.

Run it while data is flowing (an S3 poll is active). EN polls every 900 seconds
and the other nodes every 7200 seconds, so a quiet window is normal between
polls; restart the service to force a poll.

Usage:
    python3 /opt/o11y-cloudfront-batch/scripts/logstash-capacity-check.py
    python3 /opt/o11y-cloudfront-batch/scripts/logstash-capacity-check.py --interval 60

Only the Python standard library is used. Optional: the aws CLI (CPU credit
balance from CloudWatch). Run as the same user as the Logstash service so
`systemctl --user` can find it.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

BUSY_HIGH = 85.0  # percent; at or above this a resource counts as saturated
CORE_HOT = 90.0  # percent; a single core at or above this counts as pegged
HEAP_HIGH = 85.0
GC_HIGH = 10.0  # percent of wall time spent in garbage collection
STEAL_HIGH = 10.0
STEAL_CAPPED_BUSY = 70.0  # percent busy; with steal at or above STEAL_HIGH, CPU counts as saturated
IO_BOUND_CPU = 30.0  # percent; busy workers with system CPU below this are waiting, not computing
IO_CPU_TARGET = 0.7  # fraction of the cores Logstash may use after adding workers to an I/O-bound pipeline
IO_MAX_SCALE = 4.0  # largest worker multiplier suggested in one step
PUSH_BLOCKED_HIGH = 0.5  # fraction of the window the inputs spent blocked on a full queue
LOW_CREDITS = 10.0


def http_json(url: str, timeout: float = 10.0) -> Dict[str, Any]:
    """GET a URL and parse the JSON body."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310 - fixed http URL
        return json.load(resp)


def imds(path: str) -> Optional[str]:
    """Read one EC2 instance metadata value (IMDSv2); None when unavailable."""
    base = "http://169.254.169.254/latest"
    try:
        tok_req = urllib.request.Request(
            f"{base}/api/token", method="PUT", headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"}
        )
        with urllib.request.urlopen(tok_req, timeout=2) as resp:  # nosec B310
            token = resp.read().decode()
        req = urllib.request.Request(f"{base}/meta-data/{path}", headers={"X-aws-ec2-metadata-token": token})
        with urllib.request.urlopen(req, timeout=2) as resp:  # nosec B310
            return resp.read().decode()
    except (urllib.error.URLError, OSError):
        return None


def run(cmd: List[str]) -> Optional[str]:
    """Run a command and return stripped stdout; None if it is missing or fails."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def logstash_pid() -> Optional[int]:
    """PID of the Logstash JVM, from the user service or by process name."""
    pid = run(["systemctl", "--user", "show", "logstash", "--property=MainPID", "--value"])
    if pid and pid.isdigit() and int(pid) > 0:
        return int(pid)
    found = run(["pgrep", "-f", "org.logstash.Logstash"])
    if found:
        return int(found.splitlines()[0])
    return None


def mem_total_gib() -> Optional[float]:
    """Total system RAM in GiB from /proc/meminfo."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return None


def cpu_times() -> Optional[Dict[str, List[int]]]:
    """Per-CPU jiffy counters from /proc/stat, keyed 'cpu' (all) and 'cpu0'...; None off Linux."""
    try:
        with open("/proc/stat") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    return {ln.split()[0]: [int(x) for x in ln.split()[1:9]] for ln in lines if ln.startswith("cpu")}


def proc_ticks(pid: Optional[int]) -> Optional[int]:
    """utime + stime jiffies for a process; None if unavailable."""
    if pid is None:
        return None
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None
    return int(fields[11]) + int(fields[12])


def pct_breakdown(before: List[int], after: List[int]) -> Dict[str, float]:
    """Busy, iowait and steal percent between two /proc/stat samples (user nice sys idle iowait irq sirq steal)."""
    delta = [a - b for a, b in zip(after, before)]
    total = sum(delta) or 1
    idle, iowait, steal = delta[3], delta[4], delta[7]
    return {
        "busy": 100.0 * (total - idle - iowait) / total,
        "iowait": 100.0 * iowait / total,
        "steal": 100.0 * steal / total,
    }


def plugin_ms(pipe: Dict[str, Any]) -> float:
    """Total milliseconds spent in filter and output plugins (summed across workers)."""
    total = 0.0
    for kind in ("filters", "outputs"):
        for plugin in pipe.get("plugins", {}).get(kind, []):
            total += plugin.get("events", {}).get("duration_in_millis", 0)
    return total


def plugin_deltas(first: Dict[str, Any], second: Dict[str, Any]) -> List[Tuple[float, str, str]]:
    """Time each filter/output plugin used in the window, as (ms, plugin name, label), largest first."""
    before = {}
    for kind in ("filters", "outputs"):
        for p in first.get("plugins", {}).get(kind, []):
            before[(kind, p["id"])] = p.get("events", {}).get("duration_in_millis", 0)
    rows = []
    for kind in ("filters", "outputs"):
        for p in second.get("plugins", {}).get(kind, []):
            ms = p.get("events", {}).get("duration_in_millis", 0) - before.get((kind, p["id"]), 0)
            if ms > 0:
                name = p.get("name", "?")
                rows.append((float(ms), name, f"{name}({p['id'][:8]})"))
    rows.sort(reverse=True)
    return rows


def gc_ms(stats: Dict[str, Any]) -> float:
    """Total GC collection time in milliseconds across all collectors."""
    collectors = stats.get("jvm", {}).get("gc", {}).get("collectors", {})
    return float(sum(c.get("collection_time_in_millis", 0) for c in collectors.values()))


def credit_balance(instance_id: str, region: str) -> Optional[float]:
    """Latest CPUCreditBalance from CloudWatch via the aws CLI; None if unavailable."""
    end = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    out = run(
        [
            "aws", "cloudwatch", "get-metric-statistics", "--region", region,
            "--namespace", "AWS/EC2", "--metric-name", "CPUCreditBalance",
            "--dimensions", f"Name=InstanceId,Value={instance_id}",
            "--start-time", (end - timedelta(minutes=30)).strftime(fmt), "--end-time", end.strftime(fmt),
            "--period", "300", "--statistics", "Minimum", "--output", "json",
        ]
    )  # fmt: skip
    if not out:
        return None
    points = sorted(json.loads(out).get("Datapoints", []), key=lambda d: d["Timestamp"])
    return float(points[-1]["Minimum"]) if points else None


def main() -> int:
    """Sample, print the report, and return a process exit code (2 if the API is unreachable)."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--interval", type=int, default=30, help="seconds between the two samples (default 30)")
    parser.add_argument("--api", default="http://localhost:9600", help="Logstash monitoring API base URL")
    parser.add_argument("--skip-credits", action="store_true", help="do not query CloudWatch for CPU credits")
    args = parser.parse_args()

    vcpus = os.cpu_count() or 1
    ram = mem_total_gib()
    itype = imds("instance-type")
    pid = logstash_pid()
    try:
        settings = http_json(f"{args.api}/_node/pipelines").get("pipelines", {})
        s1 = http_json(f"{args.api}/_node/stats")
    except (urllib.error.URLError, OSError) as err:
        print(f"Cannot reach the Logstash API at {args.api}: {err}", file=sys.stderr)
        print("Is the service running? systemctl --user status logstash", file=sys.stderr)
        return 2
    cpu1, tick1, t1 = cpu_times(), proc_ticks(pid), time.monotonic()

    print(
        f"Host: {itype or 'unknown type'}, {vcpus} vCPU, "
        f"{f'{ram:.1f} GiB RAM' if ram else 'RAM unknown'}; Logstash PID {pid or 'not found'}"
    )
    print(f"Sampling for {args.interval}s ...")
    time.sleep(args.interval)

    s2 = http_json(f"{args.api}/_node/stats")
    cpu2, tick2, t2 = cpu_times(), proc_ticks(pid), time.monotonic()
    elapsed = t2 - t1
    findings: List[str] = []

    # --- CPU ---------------------------------------------------------------
    sys_busy = steal = None
    hot_cores = None
    if cpu1 and cpu2:
        total = pct_breakdown(cpu1["cpu"], cpu2["cpu"])
        sys_busy, steal = total["busy"], total["steal"]
        cores = [pct_breakdown(cpu1[k], cpu2[k])["busy"] for k in cpu1 if k != "cpu"]
        hot_cores = sum(1 for c in cores if c >= CORE_HOT)
    ls_cores = None
    if tick1 is not None and tick2 is not None:
        ls_cores = (tick2 - tick1) / os.sysconf("SC_CLK_TCK") / elapsed
    print("\nCPU")
    if sys_busy is not None:
        print(
            f"  system {sys_busy:.0f}% busy, iowait {total['iowait']:.1f}%, steal {steal:.1f}%; "
            f"cores >= {CORE_HOT:.0f}% busy: {hot_cores}/{vcpus}"
        )
    else:
        print("  system CPU: n/a (no /proc/stat; run this on the EC2)")
    if ls_cores is not None:
        print(f"  Logstash used {ls_cores:.1f} of {vcpus} cores ({100 * ls_cores / vcpus:.0f}%)")

    # --- JVM ---------------------------------------------------------------
    heap = s2.get("jvm", {}).get("mem", {}).get("heap_used_percent")
    gc_pct = (gc_ms(s2) - gc_ms(s1)) / (elapsed * 1000) * 100
    print("\nJVM")
    print(f"  heap {heap}% used, GC {gc_pct:.1f}% of wall time")

    # --- pipelines ---------------------------------------------------------
    print("\nPipelines")
    print(f"  {'id':<8}{'workers':>8}{'batch':>7}{'in/s':>9}{'out/s':>9}{'worker util':>13}{'inputs blocked':>16}{'queue':>8}")
    active = []
    rows = {}
    for pid_name, p2 in sorted(s2.get("pipelines", {}).items()):
        p1 = s1.get("pipelines", {}).get(pid_name)
        if not p1:
            continue
        workers = settings.get(pid_name, {}).get("workers", 1)
        batch = settings.get(pid_name, {}).get("batch_size", "?")
        ev1, ev2 = p1.get("events", {}), p2.get("events", {})
        d_in = ev2.get("in", 0) - ev1.get("in", 0)
        d_out = ev2.get("out", 0) - ev1.get("out", 0)
        busy_workers = (plugin_ms(p2) - plugin_ms(p1)) / (elapsed * 1000)
        util = 100.0 * busy_workers / workers
        # Push time is summed over every input thread, so divide by the input count to get a 0-100% share.
        n_inputs = max(1, len(p2.get("plugins", {}).get("inputs", [])))
        blocked = (ev2.get("queue_push_duration_in_millis", 0) - ev1.get("queue_push_duration_in_millis", 0)) / (
            elapsed * 1000 * n_inputs
        )
        qlen = p2.get("queue", {}).get("events_count", 0)
        is_active = d_in > 0 or d_out > 0 or qlen > 0
        rows[pid_name] = (workers, util, blocked, qlen, d_in, d_out, p1, p2)
        if is_active:
            active.append(pid_name)
        state = "" if is_active else "  (idle)"
        print(
            f"  {pid_name:<8}{workers:>8}{batch:>7}{d_in / elapsed:>9.0f}{d_out / elapsed:>9.0f}"
            f"{util:>12.0f}%{100 * blocked:>15.0f}%{qlen:>8}{state}"
        )

    # --- CPU credits (burstable instances) ---------------------------------
    credits = None
    if itype and itype.startswith("t") and not args.skip_credits:
        instance_id, region = imds("instance-id"), imds("placement/region")
        if instance_id and region:
            credits = credit_balance(instance_id, region)
        print("\nCPU credits (burstable instance)")
        print(f"  CPUCreditBalance: {'unavailable (no aws CLI or CloudWatch access)' if credits is None else f'{credits:.0f}'}")

    # --- findings ----------------------------------------------------------
    if not active:
        findings.append(
            "No pipeline processed events in this window, so nothing can be concluded. S3 inputs poll every "
            "900 s (EN) or 7200 s (others). Restart the service (systemctl --user restart logstash) to force "
            "a poll, then rerun this script once events/s is nonzero."
        )
    if steal is not None and steal >= STEAL_HIGH:
        findings.append(
            f"Steal time is {steal:.0f}%: the hypervisor is withholding CPU, so part of the idle CPU cannot be "
            "used. On a t-family instance in standard credit mode this means the credit balance is exhausted "
            "(enable unlimited mode); in unlimited mode or on any other type it is host contention or the "
            "surplus-credit limit, and a non-burstable type (m6i/c6i) is the fix. Check "
            "aws ec2 describe-instance-credit-specifications."
        )
    if credits is not None and credits <= LOW_CREDITS:
        findings.append(
            f"CPU credit balance is {credits:.0f}: the instance is throttled to its baseline. Enable unlimited "
            "mode (aws ec2 modify-instance-credit-specification) or use a non-burstable type for re-ingests."
        )
    # Busy time includes steal, and stolen CPU cannot be used, so high steal means the box is effectively full.
    capped = sys_busy is not None and steal is not None and steal >= STEAL_HIGH and sys_busy >= STEAL_CAPPED_BUSY
    if active and sys_busy is not None and (sys_busy >= BUSY_HIGH or capped):
        findings.append(
            f"CPU is effectively saturated ({sys_busy:.0f}% busy, {steal:.0f}% of it steal). You are using all "
            "the compute you have; more workers will not help. Get more or non-throttled vCPUs, or make the "
            "filters cheaper (see the slowest plugins below)."
        )
    elif active:
        n_active = len(active)
        for name in active:
            workers, util, blocked, qlen, d_in, d_out, p1, p2 = rows[name]
            if util >= BUSY_HIGH:
                deltas = plugin_deltas(p1, p2)
                top_ms, top_name, top_label = deltas[0] if deltas else (0.0, "", "")
                share = top_ms / (sum(d[0] for d in deltas) or 1)
                if sys_busy is not None and sys_busy < IO_BOUND_CPU and share >= 0.5:
                    # Workers are blocked inside one plugin, not computing: waiting threads cost no CPU.
                    # Scale workers by the CPU headroom (at most 4x), keeping Logstash under IO_CPU_TARGET of the cores.
                    scale = IO_MAX_SCALE if not ls_cores else min(IO_MAX_SCALE, IO_CPU_TARGET * vcpus / ls_cores)
                    target = min(4 * vcpus, max(workers + 1, round(workers * scale)))
                    findings.append(
                        f"Pipeline '{name}': I/O-bound. {top_label} holds {100 * share:.0f}% of worker time "
                        f"({top_ms / 1000:.0f}s in a {elapsed:.0f}s window) while the system is only "
                        f"{sys_busy:.0f}% busy, so the workers are waiting on '{top_name}', not computing. "
                        f"Waiting threads use no CPU, so raise pipeline.workers from {workers} to about {target} "
                        f"to keep more '{top_name}' calls in flight. Also cut the wait per call "
                        "(caching, shorter timeouts, fewer retries)."
                    )
                    continue
                target = min(vcpus, max(workers + 1, vcpus // n_active))
                if target > workers:
                    if sys_busy is not None:
                        why = f"while the system is only {sys_busy:.0f}% busy. It is worker-bound with spare CPU"
                    else:
                        why = "and system CPU is unknown. If CPU is not saturated it is worker-bound"
                    findings.append(
                        f"Pipeline '{name}': workers are {util:.0f}% busy {why}: raise pipeline.workers from "
                        f"{workers} to about {target}."
                    )
                else:
                    findings.append(f"Pipeline '{name}': workers are {util:.0f}% busy but already at the core limit.")
    for name in active:
        workers, util, blocked, qlen, d_in, d_out, p1, p2 = rows[name]
        if blocked >= PUSH_BLOCKED_HIGH and util < BUSY_HIGH:
            findings.append(
                f"Pipeline '{name}': inputs are blocked {100 * blocked:.0f}% of the time but its workers are only "
                f"{util:.0f}% busy. The output is the bottleneck (OpenSearch slow or rejecting bulk writes), so "
                "more workers will not help. Check _cat/thread_pool/write on OpenSearch."
            )
        slow = [f"{label} {ms / 1000:.1f}s" for ms, _, label in plugin_deltas(p1, p2)[:3]]
        if slow and util >= BUSY_HIGH:
            findings.append(f"Pipeline '{name}': slowest plugins in the window: {', '.join(slow)}.")
    total_workers = sum(rows[n][0] for n in active)
    cpu_pressure = sys_busy is not None and (sys_busy >= BUSY_HIGH or capped)
    if total_workers > 2 * vcpus and cpu_pressure:
        findings.append(
            f"Active pipelines have {total_workers} workers in total on {vcpus} vCPUs and the CPU is under "
            "pressure, so workers compete for cores. Lower per-pipeline workers or run fewer nodes at once "
            "(ENABLED_NODES)."
        )
    if heap is not None and heap >= HEAP_HIGH:
        findings.append(f"Heap is {heap}% used: raise -Xmx (up to half of RAM) or lower pipeline.batch.size.")
    if gc_pct >= GC_HIGH:
        findings.append(f"GC took {gc_pct:.0f}% of wall time, stealing CPU from the workers. Heap is too small.")
    if active and sys_busy is None:
        findings.append("System CPU could not be read (no /proc/stat), so CPU saturation was not checked.")
    elif active and not findings:
        findings.append(
            "No limit hit: CPU, workers, heap, and the output all have headroom. If throughput is still lower "
            "than you want, the S3 input (mostly single-threaded per pipeline) is the likely limit; run more "
            "node pipelines in parallel."
        )

    print("\nFindings")
    for item in findings:
        print(f"  - {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
