#!/usr/bin/env python3
"""Check whether Logstash on this EC2 is using the compute that is available.

Samples the Logstash monitoring API (localhost:9600) and /proc twice, INTERVAL
seconds apart, then reports CPU, per-pipeline worker utilization, backpressure,
JVM heap/GC, and (on burstable t-family instances) CPU credits and steal time.
It also checks the OpenSearch side (cluster status, JVM heap, CPU, bulk write
rejections, circuit breakers, free disk) so that raising Logstash workers does
not just move the bottleneck. It ends with findings that say which limit is
being hit: CPU, workers, a blocked output, OpenSearch, heap, or throttling.

Run it while data is flowing (an S3 poll is active). EN polls every 900 seconds
and the other nodes every 7200 seconds, so a quiet window is normal between
polls; restart the service to force a poll.

Usage:
    python3 /opt/o11y-cloudfront-batch/scripts/logstash-capacity-check.py
    python3 /opt/o11y-cloudfront-batch/scripts/logstash-capacity-check.py --interval 60

The Logstash and CPU checks use only the Python standard library. Optional:
the aws CLI (CPU credit balance from CloudWatch) and boto3 (signed OpenSearch
queries with the instance role; use the same python3.13 that has boto3, as
os-doc-counts.sh does). OPENSEARCH_URL and AWS_REGION come from the environment
or /etc/logstash/env. Run as the same user as the Logstash service so
`systemctl --user` can find it.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Callable
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
OS_HEAP_HIGH = 80.0  # percent; sustained JVM heap at this level on OpenSearch is memory pressure
OS_CPU_HIGH = 85.0
OS_DISK_FREE_LOW = 15.0  # percent free; near OpenSearch's default low disk watermark

try:
    from botocore.exceptions import BotoCoreError

    OS_ERRORS: Tuple[type, ...] = (urllib.error.URLError, OSError, ValueError, BotoCoreError)
except ImportError:
    OS_ERRORS = (urllib.error.URLError, OSError, ValueError)


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


def env_value(key: str) -> Optional[str]:
    """A setting from the environment, else from the deployed /etc/logstash/env file."""
    if os.environ.get(key):
        return os.environ[key]
    try:
        with open("/etc/logstash/env") as f:
            for line in f:
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def opensearch_client() -> Tuple[Optional[Callable[[str], Dict[str, Any]]], str]:
    """A signed GET function for OpenSearch using the instance role, or (None, reason) if not possible."""
    url = env_value("OPENSEARCH_URL")
    if not url:
        return None, "OPENSEARCH_URL is not set (no environment value and no /etc/logstash/env)"
    try:
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
    except ImportError:
        return None, "boto3 is not available to this python; run with the python3.13 that has boto3"
    region = env_value("AWS_REGION") or "us-west-2"
    creds = boto3.Session(region_name=region).get_credentials()
    if creds is None:
        return None, "no AWS credentials found"

    def get(path: str) -> Dict[str, Any]:
        full = url.rstrip("/") + path
        req = AWSRequest(method="GET", url=full)
        SigV4Auth(creds.get_frozen_credentials(), "es", region).add_auth(req)
        http_req = urllib.request.Request(full, headers=dict(req.headers), method="GET")
        with urllib.request.urlopen(http_req, timeout=20) as resp:  # nosec B310 - https endpoint from env
            return json.load(resp)

    return get, ""


def opensearch_snapshot(get: Callable[[str], Dict[str, Any]]) -> Dict[str, Any]:
    """Cluster status plus per-node JVM heap, CPU, write thread pool, breaker trips and free disk."""
    # filter_path is percent-encoded because the request signature covers the exact query string.
    health_q = urllib.parse.urlencode({"filter_path": "status,number_of_nodes,unassigned_shards"})
    nodes_q = urllib.parse.urlencode(
        {
            "filter_path": ",".join(
                [
                    "nodes.*.name",
                    "nodes.*.jvm.mem.heap_used_percent",
                    "nodes.*.os.cpu.percent",
                    "nodes.*.thread_pool.write",
                    "nodes.*.breakers.parent.tripped",
                    "nodes.*.fs.total",
                ]
            )
        }
    )
    health = get(f"/_cluster/health?{health_q}")
    raw = get(f"/_nodes/stats?{nodes_q}").get("nodes", {})
    nodes: Dict[str, Dict[str, Any]] = {}
    for node_id, n in raw.items():
        fs = n.get("fs", {}).get("total", {})
        disk_total = fs.get("total_in_bytes") or 0
        write = n.get("thread_pool", {}).get("write", {})
        nodes[node_id] = {
            "name": n.get("name", node_id[:8]),
            "heap": n.get("jvm", {}).get("mem", {}).get("heap_used_percent"),
            "cpu": n.get("os", {}).get("cpu", {}).get("percent"),
            "queue": write.get("queue", 0),
            "rejected": write.get("rejected", 0),
            "tripped": n.get("breakers", {}).get("parent", {}).get("tripped", 0),
            "disk_free": 100.0 * fs.get("available_in_bytes", 0) / disk_total if disk_total else None,
        }
    return {"health": health, "nodes": nodes}


def pct(value: Optional[float]) -> str:
    """A percent for a table cell, or n/a."""
    return "n/a" if value is None else f"{value:.0f}%"


def main() -> int:
    """Sample, print the report, and return a process exit code (2 if the API is unreachable)."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--interval", type=int, default=30, help="seconds between the two samples (default 30)")
    parser.add_argument("--api", default="http://localhost:9600", help="Logstash monitoring API base URL")
    parser.add_argument("--skip-credits", action="store_true", help="do not query CloudWatch for CPU credits")
    parser.add_argument("--skip-opensearch", action="store_true", help="do not query OpenSearch")
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
    os_get, os_note = (None, "skipped (--skip-opensearch)") if args.skip_opensearch else opensearch_client()
    o1 = o2 = None
    if os_get:
        try:
            o1 = opensearch_snapshot(os_get)
        except OS_ERRORS as err:
            os_note = f"query failed: {err} (check IAM and fine-grained access control)"
    cpu1, tick1, t1 = cpu_times(), proc_ticks(pid), time.monotonic()

    print(
        f"Host: {itype or 'unknown type'}, {vcpus} vCPU, "
        f"{f'{ram:.1f} GiB RAM' if ram else 'RAM unknown'}; Logstash PID {pid or 'not found'}"
    )
    print(f"Sampling for {args.interval}s ...")
    time.sleep(args.interval)

    s2 = http_json(f"{args.api}/_node/stats")
    cpu2, tick2, t2 = cpu_times(), proc_ticks(pid), time.monotonic()
    if os_get and o1:
        try:
            o2 = opensearch_snapshot(os_get)
        except OS_ERRORS as err:
            os_note = f"query failed: {err} (check IAM and fine-grained access control)"
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

    # --- OpenSearch --------------------------------------------------------
    os_rows = []
    print("\nOpenSearch")
    if o1 and o2:
        health = o2["health"]
        print(
            f"  cluster {health.get('status', '?')}, {health.get('number_of_nodes', '?')} node(s), "
            f"{health.get('unassigned_shards', '?')} unassigned shard(s)"
        )
        print(f"  {'node':<24}{'heap':>6}{'cpu':>6}{'write queue':>13}{'rejected':>10}{'breaker trips':>15}{'disk free':>11}")
        for node_id, n2 in sorted(o2["nodes"].items(), key=lambda kv: kv[1]["name"]):
            n1 = o1["nodes"].get(node_id, n2)
            rejected = max(0, n2["rejected"] - n1["rejected"])
            tripped = max(0, n2["tripped"] - n1["tripped"])
            os_rows.append((n2, rejected, tripped))
            print(
                f"  {n2['name']:<24}{pct(n2['heap']):>6}{pct(n2['cpu']):>6}{n2['queue']:>13}"
                f"{rejected:>10}{tripped:>15}{pct(n2['disk_free']):>11}"
            )
    else:
        print(f"  not checked: {os_note}")
    # When OpenSearch is the limit, more Logstash workers only add load, so no worker increase is suggested.
    os_limited = any(
        rejected > 0 or tripped > 0 or (n["heap"] or 0) >= OS_HEAP_HIGH or (n["cpu"] or 0) >= OS_CPU_HIGH
        for n, rejected, tripped in os_rows
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
    elif active and not os_limited:
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
    if o2:
        status = o2["health"].get("status")
        if status == "red":
            findings.append("OpenSearch cluster status is red: some primary shards are unassigned, so writes can fail.")
        elif status == "yellow":
            findings.append(
                "OpenSearch cluster status is yellow (replica shards unassigned). Expected on a single data node; "
                "otherwise check shard allocation."
            )
        for n, rejected, tripped in os_rows:
            who = f"OpenSearch node '{n['name']}'"
            if rejected > 0:
                findings.append(
                    f"{who} rejected {rejected} bulk write(s) in the window (write queue {n['queue']}). OpenSearch "
                    "is the limit: more Logstash workers or a larger batch.size only add load. Lower them, or scale "
                    "the domain (more or larger data nodes)."
                )
            if tripped > 0:
                findings.append(
                    f"{who} tripped {tripped} circuit breaker(s) in the window: requests were refused for memory. "
                    "Lower Logstash batch.size or workers, or move to a larger instance type."
                )
            if n["heap"] is not None and n["heap"] >= OS_HEAP_HIGH:
                findings.append(
                    f"{who} JVM heap is {n['heap']}% used (memory pressure at {OS_HEAP_HIGH:.0f}%+). Indexing "
                    "faster will make it worse; scale up the domain or reduce Logstash load."
                )
            if n["cpu"] is not None and n["cpu"] >= OS_CPU_HIGH:
                findings.append(f"{who} CPU is {n['cpu']}%: the cluster is saturated; Logstash cannot push faster.")
            if n["disk_free"] is not None and n["disk_free"] < OS_DISK_FREE_LOW:
                findings.append(
                    f"{who} has {n['disk_free']:.0f}% disk free: near the allocation watermark, after which "
                    "OpenSearch blocks writes. Free space or add storage."
                )
    if active and sys_busy is None:
        findings.append("System CPU could not be read (no /proc/stat), so CPU saturation was not checked.")
    elif active and not findings:
        checked = "CPU, workers, heap, and OpenSearch" if o2 else "CPU, workers, and heap"
        findings.append(
            f"No limit hit: {checked} have headroom. If throughput is still lower than you want, the S3 input "
            "(mostly single-threaded per pipeline) is the likely limit; run more node pipelines in parallel."
            + ("" if o2 else f" OpenSearch was not checked ({os_note}).")
        )

    print("\nFindings")
    for item in findings:
        print(f"  - {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
