#!/usr/bin/env python3
"""Summarize Phase 2 Quest transport logs without external dependencies."""

import argparse
import json
import math
import statistics
import sys
from pathlib import Path


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def device_valid(sample, name):
    value = sample.get(name)
    if name == "head":
        return value is not None
    return isinstance(value, dict) and bool(value.get("grip") or value.get("ray"))


def input_active(sample, name):
    controller = sample.get(name)
    if not isinstance(controller, dict):
        return False, False
    buttons = controller.get("buttons")
    button_active = isinstance(buttons, list) and any(
        isinstance(button, dict) and (
            button.get("pressed") is True or button.get("touched") is True or
            (isinstance(button.get("value"), (int, float)) and abs(button["value"]) > 0.05)
        ) for button in buttons
    )
    axes = controller.get("axes")
    axis_active = isinstance(axes, list) and any(
        isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) > 0.05
        for value in axes
    )
    return button_active, axis_active


def analyze(path):
    records = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("{}:{}: invalid JSON: {}".format(path, line_number, exc))
            if isinstance(record, dict):
                records.append(record)

    samples = []
    rtts = []
    clock_offsets = []
    remote_addresses = set()
    for record in records:
        remote = record.get("remote")
        if isinstance(remote, str):
            remote_addresses.add(remote)
        batch = record.get("samples")
        if isinstance(batch, list):
            samples.extend(sample for sample in batch if isinstance(sample, dict))
        client_metrics = record.get("clientMetrics")
        if isinstance(client_metrics, dict):
            rtt = client_metrics.get("lastRttMs")
            if isinstance(rtt, (int, float)) and not isinstance(rtt, bool) and math.isfinite(rtt):
                rtts.append(float(rtt))
            offset = client_metrics.get("clockOffsetMs")
            if isinstance(offset, (int, float)) and not isinstance(offset, bool) and math.isfinite(offset):
                clock_offsets.append(float(offset))

    sequences = [sample.get("sequence") for sample in samples]
    sequences = [value for value in sequences if isinstance(value, int) and not isinstance(value, bool)]
    estimated_lost = 0
    duplicates = 0
    out_of_order = 0
    for previous, current in zip(sequences, sequences[1:]):
        if current == previous:
            duplicates += 1
        elif current < previous:
            out_of_order += 1
        elif current > previous + 1:
            estimated_lost += current - previous - 1

    client_times = [float(sample["clientTime"]) for sample in samples
                    if isinstance(sample.get("clientTime"), (int, float))
                    and not isinstance(sample.get("clientTime"), bool)
                    and math.isfinite(sample["clientTime"])]
    intervals = [current - previous for previous, current in zip(client_times, client_times[1:])
                 if current >= previous]
    duration_s = (client_times[-1] - client_times[0]) / 1000 if len(client_times) > 1 else 0.0
    expected = len(sequences) + estimated_lost

    validity = {}
    input_activity = {}
    for name in ("head", "left", "right"):
        valid = sum(1 for sample in samples if device_valid(sample, name))
        validity[name] = round(100 * valid / len(samples), 3) if samples else 0.0
    for name in ("left", "right"):
        activity = [input_active(sample, name) for sample in samples]
        input_activity[name] = {
            "buttonActiveSamples": sum(button for button, _ in activity),
            "axisActiveSamples": sum(axis for _, axis in activity),
        }

    return {
        "file": str(path),
        "sessionId": records[0].get("sessionId") if records else None,
        "remoteAddresses": sorted(remote_addresses),
        "batches": len(records),
        "samples": len(samples),
        "durationSeconds": round(duration_s, 3),
        "sampleRateHz": round((len(client_times) - 1) / duration_s, 2) if duration_s > 0 else 0.0,
        "jitterStdMs": round(statistics.pstdev(intervals), 3) if intervals else 0.0,
        "intervalP95Ms": round(percentile(intervals, 0.95), 3) if intervals else None,
        "intervalMaxMs": round(max(intervals), 3) if intervals else None,
        "stallsOver25Ms": sum(interval > 25 for interval in intervals),
        "stallsOver100Ms": sum(interval > 100 for interval in intervals),
        "rttMeanMs": round(statistics.mean(rtts), 3) if rtts else None,
        "rttP95Ms": round(percentile(rtts, 0.95), 3) if rtts else None,
        "clockOffsetMeanMs": round(statistics.mean(clock_offsets), 3) if clock_offsets else None,
        "estimatedLost": estimated_lost,
        "lossPercent": round(100 * estimated_lost / expected, 4) if expected else 0.0,
        "duplicates": duplicates,
        "outOfOrder": out_of_order,
        "trackingValidPercent": validity,
        "inputActivity": input_activity,
    }


def acceptance_failures(result):
    failures = []
    checks = (
        (result["durationSeconds"] >= 30, "duration < 30 s"),
        (result["sampleRateHz"] >= 60, "sample rate < 60 Hz"),
        (result["jitterStdMs"] <= 5, "jitter > 5 ms"),
        (result["lossPercent"] <= 1, "loss > 1%"),
        (result["duplicates"] == 0, "duplicate sequences detected"),
        (result["outOfOrder"] == 0, "out-of-order sequences detected"),
        (result["trackingValidPercent"]["head"] >= 99, "head tracking < 99%"),
        (result["trackingValidPercent"]["left"] >= 95, "left controller tracking < 95%"),
        (result["trackingValidPercent"]["right"] >= 95, "right controller tracking < 95%"),
        (result["inputActivity"]["left"]["buttonActiveSamples"] > 0, "no left button activity"),
        (result["inputActivity"]["left"]["axisActiveSamples"] > 0, "no left stick activity"),
        (result["inputActivity"]["right"]["buttonActiveSamples"] > 0, "no right button activity"),
        (result["inputActivity"]["right"]["axisActiveSamples"] > 0, "no right stick activity"),
        (result["rttP95Ms"] is not None, "RTT data missing"),
        (result["rttP95Ms"] is None or result["rttP95Ms"] <= 100, "RTT p95 > 100 ms"),
    )
    for passed, message in checks:
        if not passed:
            failures.append(message)
    return failures


def print_human(result, failures=None):
    print("Session: {}".format(result["sessionId"] or "unknown"))
    print("File: {}".format(result["file"]))
    print("Samples: {} in {:.3f} s ({:.2f} Hz)".format(
        result["samples"], result["durationSeconds"], result["sampleRateHz"]))
    print("Jitter: {:.3f} ms stddev | interval p95: {} ms | max: {} ms".format(
        result["jitterStdMs"], result["intervalP95Ms"], result["intervalMaxMs"]))
    print("WebXR stalls: >25 ms {} | >100 ms {}".format(
        result["stallsOver25Ms"], result["stallsOver100Ms"]))
    print("RTT: mean {} ms | p95 {} ms".format(result["rttMeanMs"], result["rttP95Ms"]))
    print("Estimated server clock offset: {} ms".format(result["clockOffsetMeanMs"]))
    print("Sequence: lost {} ({:.4f}%) | duplicate {} | out-of-order {}".format(
        result["estimatedLost"], result["lossPercent"], result["duplicates"], result["outOfOrder"]))
    tracking = result["trackingValidPercent"]
    print("Tracking valid: head {:.3f}% | left {:.3f}% | right {:.3f}%".format(
        tracking["head"], tracking["left"], tracking["right"]))
    activity = result["inputActivity"]
    print("Input activity: left buttons {} / axes {} | right buttons {} / axes {}".format(
        activity["left"]["buttonActiveSamples"], activity["left"]["axisActiveSamples"],
        activity["right"]["buttonActiveSamples"], activity["right"]["axisActiveSamples"]))
    if failures is not None:
        if failures:
            print("Acceptance: FAIL — {}".format("; ".join(failures)))
        else:
            print("Acceptance: PASS")


def main():
    parser = argparse.ArgumentParser(description="Analyze a Quest Phase 2 NDJSON log")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--check", action="store_true", help="apply conservative Phase 2 thresholds")
    args = parser.parse_args()
    failed = False
    results = []
    for path in args.paths:
        result = analyze(path)
        failures = acceptance_failures(result) if args.check else None
        failed = failed or bool(failures)
        if args.json:
            result["acceptanceFailures"] = failures
            results.append(result)
        else:
            if len(args.paths) > 1:
                print("=== {} ===".format(path))
            print_human(result, failures)
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
