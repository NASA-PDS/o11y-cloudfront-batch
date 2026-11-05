"""Unit tests for scripts/logstash-capacity-check.py."""
import contextlib
import importlib.util
import io
import sys
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest.mock import mock_open
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "logstash-capacity-check.py"
SPEC = importlib.util.spec_from_file_location("logstash_capacity_check", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cc)

INTERVAL = 10  # seconds between the two samples in the main() scenarios


def plugin(plugin_id: str, name: str, ms: int) -> Dict[str, Any]:
    """A filter or output plugin entry from the Logstash node stats API."""
    return {"id": plugin_id, "name": name, "events": {"duration_in_millis": ms}}


def pipeline_stats(
    events: int, plugins: List[Dict[str, Any]], push_ms: int = 0, outputs: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """One pipeline's entry in /_node/stats: event counters, queue push time and plugin durations."""
    return {
        "events": {"in": events, "out": events, "queue_push_duration_in_millis": push_ms},
        "plugins": {"inputs": [{"id": "in"}], "filters": plugins, "outputs": outputs or []},
        "queue": {"events_count": 0},
    }


def node_stats(pipelines: Dict[str, Dict[str, Any]], heap: int = 40) -> Dict[str, Any]:
    """A /_node/stats response with JVM heap, no GC time and the given pipelines."""
    return {
        "jvm": {"mem": {"heap_used_percent": heap}, "gc": {"collectors": {"old": {"collection_time_in_millis": 0}}}},
        "pipelines": pipelines,
    }


class TestHelpers(unittest.TestCase):
    """The pure helpers that turn /proc and Logstash API samples into numbers."""

    def test_pct_breakdown(self):
        """Busy, iowait and steal are shares of the jiffies elapsed between the samples."""
        before = [0, 0, 0, 0, 0, 0, 0, 0]
        after = [50, 0, 10, 20, 10, 0, 0, 10]  # user nice sys idle iowait irq sirq steal
        result = cc.pct_breakdown(before, after)
        self.assertAlmostEqual(result["busy"], 70.0)
        self.assertAlmostEqual(result["iowait"], 10.0)
        self.assertAlmostEqual(result["steal"], 10.0)

    def test_proc_ticks_sums_utime_and_stime(self):
        """The process CPU ticks are the sum of the two fields after the command name, which may contain spaces."""
        stat = "4242 (java -jar) S " + " ".join(["0"] * 10) + " 100 25 0 0"
        with patch("builtins.open", mock_open(read_data=stat)):
            self.assertEqual(cc.proc_ticks(4242), 125)

    def test_proc_ticks_unavailable(self):
        """No PID, or no /proc entry, gives None."""
        self.assertIsNone(cc.proc_ticks(None))
        with patch("builtins.open", side_effect=OSError):
            self.assertIsNone(cc.proc_ticks(4242))

    def test_plugin_ms_sums_filters_and_outputs(self):
        """Time in filters and outputs counts; inputs do not."""
        pipe = {
            "plugins": {
                "inputs": [plugin("i", "s3", 999)],
                "filters": [plugin("f1", "grok", 100), plugin("f2", "dns", 300)],
                "outputs": [plugin("o1", "opensearch", 50)],
            }
        }
        self.assertEqual(cc.plugin_ms(pipe), 450.0)
        self.assertEqual(cc.plugin_ms({}), 0.0)

    def test_plugin_deltas_largest_first(self):
        """Only time added in the window counts, sorted largest first, and idle plugins are left out."""
        first = {"plugins": {"filters": [plugin("aaaaaaaaaa", "dns", 100), plugin("bbbbbbbbbb", "grok", 10)]}}
        second = {
            "plugins": {
                "filters": [plugin("aaaaaaaaaa", "dns", 700), plugin("bbbbbbbbbb", "grok", 10)],
                "outputs": [plugin("cccccccccc", "opensearch", 40)],
            }
        }
        self.assertEqual(
            cc.plugin_deltas(first, second),
            [(600.0, "dns", "dns(aaaaaaaa)"), (40.0, "opensearch", "opensearch(cccccccc)")],
        )

    def test_gc_ms_sums_collectors(self):
        """GC time is summed across collectors."""
        stats = {
            "jvm": {
                "gc": {
                    "collectors": {"young": {"collection_time_in_millis": 30}, "old": {"collection_time_in_millis": 70}}
                }
            }
        }
        self.assertEqual(cc.gc_ms(stats), 100.0)
        self.assertEqual(cc.gc_ms({}), 0.0)

    def test_io_bound_advice_raises_workers_below_the_cap(self):
        """While the target is above the current workers, the advice is to raise them."""
        advice = cc.io_bound_advice(workers=4, target=16, cap=16, plugin="dns")
        self.assertIn("raise pipeline.workers from 4 to about 16", advice)

    def test_io_bound_advice_never_lowers_workers(self):
        """At or above the cap, the advice does not say to raise workers to a lower number."""
        for workers in (8, 24):
            advice = cc.io_bound_advice(workers=workers, target=8, cap=8, plugin="dns")
            self.assertNotIn("raise pipeline.workers", advice)
            self.assertIn("already at the cap of 8", advice)


class TestMain(unittest.TestCase):
    """The findings printed by main() for sampled Logstash, CPU and OpenSearch data."""

    def run_main(
        self,
        pipelines_first: Dict[str, Dict[str, Any]],
        pipelines_second: Dict[str, Dict[str, Any]],
        workers: Dict[str, int],
        cpu_after: List[int],
        vcpus: int = 4,
        itype: str = "m6i.xlarge",
        credits: Optional[float] = None,
        events: Optional[List[str]] = None,
    ) -> str:
        """Run main() against fixed samples and return what it printed."""
        calls = events if events is not None else []
        stats = iter([node_stats(pipelines_first), node_stats(pipelines_second)])

        def fake_http_json(url: str, timeout: float = 10.0) -> Dict[str, Any]:
            if url.endswith("/_node/pipelines"):
                calls.append("pipelines")
                return {"pipelines": {name: {"workers": n, "batch_size": 125} for name, n in workers.items()}}
            calls.append("stats")
            return next(stats)

        def fake_snapshot(get: Any) -> Dict[str, Any]:
            calls.append("opensearch")
            return {"health": {"status": "green"}, "nodes": {}}

        cpu_samples = iter([{"cpu": [0] * 8}, {"cpu": cpu_after}])
        tick_samples = iter([0, 100])
        argv = ["capacity-check", "--interval", str(INTERVAL)]
        argv += [] if credits is not None else ["--skip-credits"]
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(patch.object(cc, "http_json", fake_http_json))
            stack.enter_context(patch.object(cc, "logstash_pid", return_value=1234))
            stack.enter_context(patch.object(cc, "mem_total_gib", return_value=16.0))
            stack.enter_context(
                patch.object(cc, "imds", side_effect=lambda key: {"instance-type": itype}.get(key, "x"))
            )
            stack.enter_context(patch.object(cc, "cpu_times", side_effect=lambda: next(cpu_samples)))
            stack.enter_context(patch.object(cc, "proc_ticks", side_effect=lambda pid: next(tick_samples)))
            stack.enter_context(patch.object(cc, "opensearch_client", return_value=(lambda path: {}, "")))
            stack.enter_context(patch.object(cc, "opensearch_snapshot", fake_snapshot))
            stack.enter_context(patch.object(cc, "credit_balance", return_value=credits))
            stack.enter_context(patch.object(cc.time, "sleep"))
            stack.enter_context(patch.object(cc.time, "monotonic", side_effect=[0.0, float(INTERVAL)]))
            stack.enter_context(patch.object(cc.os, "cpu_count", return_value=vcpus))
            stack.enter_context(patch.object(cc.os, "sysconf", return_value=100))
            stack.enter_context(contextlib.redirect_stdout(out))
            self.assertEqual(cc.main(), 0)
        return out.getvalue()

    def test_findings_io_bound_pipeline(self):
        """Busy workers inside the dns filter on an idle system are I/O-bound; the advice is to add workers."""
        first = {"en": pipeline_stats(0, [plugin("dns-filter-id", "dns", 0), plugin("grok-filter-id", "grok", 0)])}
        second = {
            "en": pipeline_stats(5000, [plugin("dns-filter-id", "dns", 36000), plugin("grok-filter-id", "grok", 2000)])
        }
        output = self.run_main(first, second, {"en": 4}, cpu_after=[100, 0, 0, 900, 0, 0, 0, 0])
        self.assertIn("Pipeline 'en': I/O-bound", output)
        self.assertIn("raise pipeline.workers from 4 to about 16", output)

    def test_findings_io_bound_pipeline_over_the_cap(self):
        """A pipeline already above 4 workers per vCPU is not told to lower its workers by 'raising' them."""
        first = {"en": pipeline_stats(0, [plugin("dns-filter-id", "dns", 0), plugin("grok-filter-id", "grok", 0)])}
        second = {
            "en": pipeline_stats(5000, [plugin("dns-filter-id", "dns", 220000), plugin("grok-filter-id", "grok", 8000)])
        }
        output = self.run_main(first, second, {"en": 24}, cpu_after=[100, 0, 0, 900, 0, 0, 0, 0], vcpus=2)
        self.assertIn("Pipeline 'en': I/O-bound", output)
        self.assertIn("already at the cap of 8", output)
        self.assertNotIn("raise pipeline.workers from 24", output)

    def test_findings_worker_bound_pipeline(self):
        """Busy workers spread over several plugins with spare CPU are worker-bound."""
        plugins_first = [plugin(f"filter-{i}", "grok", 0) for i in range(4)]
        plugins_second = [plugin(f"filter-{i}", "grok", 4750) for i in range(4)]
        output = self.run_main(
            {"en": pipeline_stats(0, plugins_first)},
            {"en": pipeline_stats(5000, plugins_second)},
            {"en": 2},
            cpu_after=[400, 0, 0, 600, 0, 0, 0, 0],
            vcpus=8,
        )
        self.assertIn("It is worker-bound with spare CPU", output)
        self.assertIn("raise pipeline.workers from 2 to about 8", output)

    def test_findings_output_blocked(self):
        """Inputs blocked on a full queue while workers are not busy point at the output."""
        first = {"en": pipeline_stats(0, [plugin("grok-filter-id", "grok", 0)], push_ms=0)}
        second = {"en": pipeline_stats(5000, [plugin("grok-filter-id", "grok", 1000)], push_ms=8000)}
        output = self.run_main(first, second, {"en": 4}, cpu_after=[100, 0, 0, 900, 0, 0, 0, 0])
        self.assertIn("The output is the bottleneck", output)
        self.assertNotIn("I/O-bound", output)

    def test_findings_credit_throttling(self):
        """A burstable instance with a low CPU credit balance is reported as throttled."""
        first = {"en": pipeline_stats(0, [plugin("grok-filter-id", "grok", 0)])}
        second = {"en": pipeline_stats(5000, [plugin("grok-filter-id", "grok", 1000)])}
        output = self.run_main(
            first, second, {"en": 4}, cpu_after=[100, 0, 0, 900, 0, 0, 0, 0], itype="t3.xlarge", credits=5.0
        )
        self.assertIn("CPU credit balance is 5: the instance is throttled to its baseline", output)

    def test_no_active_pipeline(self):
        """With no events in the window, the report says nothing can be concluded."""
        idle = {"en": pipeline_stats(0, [plugin("grok-filter-id", "grok", 0)])}
        output = self.run_main(idle, idle, {"en": 4}, cpu_after=[100, 0, 0, 900, 0, 0, 0, 0])
        self.assertIn("No pipeline processed events in this window", output)

    def test_logstash_stats_are_sampled_after_the_opensearch_query(self):
        """The first Logstash counters are read after the slow OpenSearch query, next to the CPU and clock samples."""
        calls: List[str] = []
        idle = {"en": pipeline_stats(0, [plugin("grok-filter-id", "grok", 0)])}
        self.run_main(idle, idle, {"en": 4}, cpu_after=[100, 0, 0, 900, 0, 0, 0, 0], events=calls)
        self.assertEqual(calls, ["pipelines", "opensearch", "stats", "stats", "opensearch"])

    def test_unreachable_api(self):
        """An unreachable Logstash API ends the run with exit code 2."""
        err = io.StringIO()
        with patch.object(sys, "argv", ["capacity-check", "--skip-credits"]), patch.object(
            cc, "http_json", side_effect=urllib.error.URLError("refused")
        ), patch.object(cc, "imds", return_value=None), patch.object(
            cc, "logstash_pid", return_value=None
        ), patch.object(
            cc, "mem_total_gib", return_value=None
        ), contextlib.redirect_stderr(
            err
        ):
            self.assertEqual(cc.main(), 2)
        self.assertIn("Cannot reach the Logstash API", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
