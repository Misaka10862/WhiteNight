"""Synthetic stability probes must not turn missing evidence into acceptance."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from scripts.run_72h import HealthProbe, MonitorConfig, run_monitor


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def monotonic(self):
        return self.seconds

    def now(self):
        return datetime(2026, 9, 4, tzinfo=UTC) + timedelta(seconds=self.seconds)

    def sleep(self, seconds):
        self.seconds += seconds


def _probe(*, model=None, onebot=None, tasks=None, rss=100, include_monitor=True):
    def transport(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, text="ok")
        if request.url.path == "/api/v1/status":
            data = {"version": "0.1.0"}
            if include_monitor:
                data["monitor"] = {"pid": 123, "tasks": tasks or [], "tasks_complete": True}
            return httpx.Response(200, json=data)
        if request.url.path == "/api/v1/system/health":
            return httpx.Response(
                200,
                json={
                    "database": {"reachable": True},
                    "model": model or {"model_available": True},
                    "delegates": {"hermes": {"enabled": False}},
                    "onebot": onebot or {"enabled": False},
                },
            )
        raise AssertionError(f"Unexpected endpoint: {request.url.path}")

    return HealthProbe(
        httpx.Client(base_url="http://127.0.0.1:8765", transport=httpx.MockTransport(transport)),
        rss_reader=lambda pid: rss,
    )


@pytest.mark.parametrize("hours,interval", [(0, 1), (-1, 1), (1, 0), (1, -1), (float("nan"), 1)])
def test_positive_monitor_inputs(hours, interval):
    with pytest.raises(ValueError):
        MonitorConfig(hours=hours, interval=interval)


def test_healthz_cannot_hide_enabled_provider_failure():
    probe = _probe(model={"configured": True, "reachable": False})
    result = probe.sample(datetime(2026, 9, 4, tzinfo=UTC))
    assert result.components["model"] == "unhealthy"
    assert not result.ok


def test_only_enabled_qq_is_required():
    probe = _probe(onebot={"enabled": True, "health": {"logged_in": False}})
    assert probe.sample(datetime(2026, 9, 4, tzinfo=UTC)).components["onebot"] == "unhealthy"


def test_stalled_task_and_rss_are_measured_without_private_endpoints():
    probe = _probe(
        tasks=[{"id": "synthetic", "status": "running", "updated_at": "2026-09-03T00:00:00Z"}]
    )
    result = probe.sample(datetime(2026, 9, 4, tzinfo=UTC))
    assert result.stalled_tasks == 1
    assert result.rss_bytes == 100
    assert not result.ok


def test_complete_short_monitor_records_window_and_revision():
    clock = Clock()
    records = []
    report = run_monitor(
        MonitorConfig(hours=0.001, interval=1),
        _probe(),
        monotonic=clock.monotonic,
        utcnow=clock.now,
        sleep=clock.sleep,
        emit=records.append,
        revision=lambda: "synthetic-revision",
    )
    assert report["outcome"] == "passed"
    assert report["samples"] == report["expected_samples"] == 5
    assert report["valid_samples"] == 5
    assert report["start_revision"] == report["end_revision"] == "synthetic-revision"
    assert report["rss_peak_bytes"] == 100
    assert records[0]["kind"] == "start" and records[-1]["kind"] == "summary"


def test_sampling_gap_prevents_success():
    clock = Clock()

    def sleeping(seconds):
        clock.seconds += seconds + 4

    report = run_monitor(
        MonitorConfig(hours=0.001, interval=1),
        _probe(),
        monotonic=clock.monotonic,
        utcnow=clock.now,
        sleep=sleeping,
        emit=lambda record: None,
        revision=lambda: "test",
    )
    assert report["outcome"] == "inconclusive"
    assert report["sampling_gaps"] > 0


def test_missing_resource_task_or_provider_evidence_is_inconclusive():
    clock = Clock()
    report = run_monitor(
        MonitorConfig(hours=0.001, interval=1),
        _probe(model={"configured": True}, include_monitor=False, rss=None),
        monotonic=clock.monotonic,
        utcnow=clock.now,
        sleep=clock.sleep,
        emit=lambda record: None,
        revision=lambda: "test",
    )
    assert report["outcome"] == "inconclusive"
    assert report["valid_samples"] == 0
