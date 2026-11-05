#!/usr/bin/env python3
"""Refresh live figures for the site from Prometheus and the forge queue.

Writes site/figures.json. The site reads it at build time so the numbers on the
page are the same ones the chapters cite, not a stale snapshot.
"""
import json
import os
import urllib.parse
import urllib.request

PROM = "http://127.0.0.1:9090"
ROOT = os.path.dirname(os.path.abspath(__file__))

QUERIES = {
    "decode_tps": "rate(tensorfold:generation_tokens_total[5m])",
    "prefill_tps": "rate(tensorfold:prompt_tokens_total[5m])",
    "cache_hit": "rate(tensorfold:prefix_cache_hits_total[5m]) / clamp_min(rate(tensorfold:prefix_cache_queries_total[5m]),1e-9)",
    "mtp_accept": "rate(tensorfold:mtp_accepted_total[5m]) / clamp_min(rate(tensorfold:mtp_drafted_total[5m]),1e-9)",
    "running": "tensorfold:num_requests_running",
    "waiting": "tensorfold:num_requests_waiting",
    "kv_usage": "tensorfold:kv_cache_usage_perc",
    "device_mem": "tensorfold:device_memory_bytes",
    "mem_avail": "node_memory_MemAvailable_bytes",
    "gpu_temp": "spark_gpu_temperature_celsius",
    "gpu_power": "spark_gpu_power_watts",
    "sm_clock": "spark_gpu_sm_clock_mhz",
    "gpu_util": "spark_gpu_utilization_percent",
    "pair_stall_ms": "tensorfold:pair_stall_ms",
    "requests_total": "tensorfold:request_latency_seconds_count",
}

def q(expr):
    url = f"{PROM}/api/v1/query?query=" + urllib.parse.quote(expr)
    try:
        d = json.load(urllib.request.urlopen(url, timeout=10))
        r = d.get("data", {}).get("result", [])
        return float(r[0]["value"][1]) if r else None
    except Exception:
        return None

def main():
    out = {}
    for k, expr in QUERIES.items():
        out[k] = q(expr)

    # Cumulative cache ratio (more stable than a 5m rate on a quiet box).
    hits = q("tensorfold:prefix_cache_hits_total")
    queries = q("tensorfold:prefix_cache_queries_total")
    if hits is not None and queries:
        out["cache_hit_cumulative"] = hits / queries
    acc = q("tensorfold:mtp_accepted_total")
    dr = q("tensorfold:mtp_drafted_total")
    if acc is not None and dr:
        out["mtp_accept_cumulative"] = acc / dr

    q_path = os.path.join(ROOT, "state", "queue.json")
    if os.path.exists(q_path):
        qq = json.load(open(q_path, encoding="utf-8"))
        out["chapters_total"] = len(qq["chapters"])
        out["chapters_published"] = sum(1 for c in qq["chapters"] if c["status"] == "published")
        out["chapters_pending"] = sum(1 for c in qq["chapters"] if c["status"] in ("pending", "revising"))

    path = os.path.join(ROOT, "site", "figures.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(out, open(path, "w", encoding="utf-8"), indent=2)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
