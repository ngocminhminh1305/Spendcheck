"""Measure the selected local service and an isolated offline Docker container."""

import argparse
import json
import os
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

from app.hybrid import categorise_merchant, load_bundle
from app.model import file_hash
from app.settings import ROOT
from scripts.common import write_json

SAMPLES = ["NTUC FairPrice", "Chagee", "Watsons", "Octobox",
           "ABC Dental Clinic", "Happy Noodle House", "zzzzzzzzzzz", "Unknown Merchant"]

# Only stdlib is used by the in-container driver. It talks to loopback with external networking disabled.
DOCKER_DRIVER = r'''
import json, statistics, time, urllib.request, urllib.error
from pathlib import Path
samples = SAMPLES_PLACEHOLDER
started = time.perf_counter()
peak_rss = 0
peak_cgroup = 0
def memory():
    """Sample server RSS and the whole-container memory counter."""
    global peak_rss, peak_cgroup
    status = dict(line.split(":", 1) for line in Path("/proc/1/status").read_text().splitlines() if ":" in line)
    rss = int(status["VmRSS"].split()[0]) * 1024
    peak_rss = max(peak_rss, rss, int(status["VmHWM"].split()[0]) * 1024)
    current = int(Path("/sys/fs/cgroup/memory.current").read_text())
    peak_cgroup = max(peak_cgroup, current)
    return rss, current
def request(path, body=None):
    """Return HTTP status and parsed JSON, including validation errors."""
    req = urllib.request.Request("http://127.0.0.1:8000" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)
while True:
    memory()
    try:
        code, health = request("/health")
        if code == 200: break
    except (OSError, TimeoutError): pass
    if time.perf_counter() - started > 120: raise RuntimeError("Readiness timeout")
    time.sleep(.1)
ready = time.perf_counter() - started
checks = 1
predictions = {}
for text in samples:
    status, result = request("/classify", {"merchant":text})
    assert status == 200, result
    predictions[text] = result
    memory()
    checks += 1
for body in [{}, {"merchant":None}, {"merchant":4}, {"merchant":" "}, {"merchant":"!!!"},
             {"merchant":"x" * 501}, {"merchant":"Grab"}, {"merchant":"Apple"}]:
    assert request("/classify", body)[0] == 422
    checks += 1
for _ in range(3):
    for text in samples: request("/classify", {"merchant":text})
times = {"lookup":[], "model":[], "all":[]}
for _ in range(20):
    for text in samples:
        tick = time.perf_counter()
        status, result = request("/classify", {"merchant":text})
        elapsed = (time.perf_counter() - tick)*1000
        assert status == 200
        times[result["source"]].append(elapsed)
        times["all"].append(elapsed)
        memory()
rss, current = memory()
def summary(values):
    """Summarise warm per-request timings with a nearest-rank p95."""
    return {"requests":len(values), "p50_ms":statistics.median(values),
            "p95_ms":sorted(values)[int(.95 * (len(values)-1))]}
print(json.dumps({"health":health, "readiness_after_driver_start_seconds":ready, "http_checks":checks,
    "predictions":predictions, "warm_http_latency":{k:summary(v) for k,v in times.items()},
    "server_rss_bytes":rss, "server_peak_rss_bytes":peak_rss, "sampled_cgroup_peak_bytes":peak_cgroup,
    "cgroup_memory_peak_bytes":int(Path("/sys/fs/cgroup/memory.peak").read_text()),
    "server_uid":Path("/proc/1/status").read_text().split("Uid:")[1].splitlines()[0].strip()}))
'''


def docker(*arguments: str, input_text: str | None = None) -> str:
    """Run explicit Docker arguments, retaining stderr on any failure."""
    return subprocess.run(["docker", *arguments], input=input_text, text=True,
                          capture_output=True, check=True).stdout.strip()


def request(base: str, text: str | None = None) -> dict:
    """Issue a sequential localhost HTTP request without additional dependencies."""
    url = base + ("/classify" if text is not None else "/health")
    body = json.dumps({"merchant": text}).encode() if text is not None else None
    with urllib.request.urlopen(urllib.request.Request(url, data=body,
                                headers={"Content-Type": "application/json"}), timeout=10) as response:
        return json.load(response)


def local_benchmark(bundle: Path, output: Path) -> dict:
    """Start one local Uvicorn worker, measure HTTP latency/RSS, then stop only that worker."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {**os.environ, "CLASSIFIER_BUNDLE": str(bundle.resolve()), "HF_HUB_OFFLINE": "1",
           "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false",
           "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    log_path = output.parent / (output.stem + "_local_server.log")
    with log_path.open("x") as log:
        started = time.perf_counter()
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                    "--port", str(port), "--workers", "1"], cwd=ROOT, env=env, stdout=log, stderr=log)
        peak = 0
        def rss() -> int:
            """Read OS process resident memory, with KiB units on this macOS host."""
            value = subprocess.run(["ps", "-o", "rss=", "-p", str(process.pid)],
                                   capture_output=True, text=True, check=True).stdout.strip()
            return int(value or 0) * 1024
        try:
            base = f"http://127.0.0.1:{port}"
            while True:
                peak = max(peak, rss())
                if process.poll() is not None:
                    raise RuntimeError(f"Local API exited; inspect {log_path}")
                try:
                    if request(base)["status"] == "ready":
                        break
                except (OSError, TimeoutError):
                    pass
                if time.perf_counter() - started > 120:
                    raise RuntimeError("Local startup timeout")
                time.sleep(.1)
            startup = time.perf_counter() - started
            predictions = {text: request(base, text) for text in SAMPLES}
            for _ in range(3):
                for text in SAMPLES:
                    request(base, text)
            times = {"lookup": [], "model": [], "all": []}
            for _ in range(20):
                for text in SAMPLES:
                    tick = time.perf_counter()
                    result = request(base, text)
                    elapsed = (time.perf_counter() - tick) * 1000
                    times[result["source"]].append(elapsed)
                    times["all"].append(elapsed)
                peak = max(peak, rss())
            return {"startup_to_readiness_seconds": startup, "server_rss_bytes": rss(),
                    "sampled_peak_rss_bytes": peak, "predictions": predictions,
                    "warm_http_latency": {key: {"requests": len(values), "p50_ms": statistics.median(values),
                       "p95_ms": sorted(values)[int(.95 * (len(values)-1))]} for key, values in times.items()}}
        finally:
            process.terminate()
            process.wait(timeout=20)


def benchmark(image: str, bundle: Path, output: Path) -> dict:
    """Compare actual local/container predictions with no external container network."""
    if output.exists():
        raise ValueError("Resource report exists; use a new output filename")
    output.parent.mkdir(exist_ok=True, parents=True)
    # Model assets/checksums load once for parity; no fitting or final-input scoring occurs here.
    model, catalogue, manifest = load_bundle(bundle)
    expected = {text: categorise_merchant(text, model, catalogue, manifest["model_version"]) for text in SAMPLES}
    del model
    local = local_benchmark(bundle, output)
    name = f"spendcheck-hybrid-check-{os.getpid()}"
    started = time.perf_counter()
    docker("run", "--detach", "--network", "none", "--cpus", "1", "--name", name, image)
    try:
        created = time.perf_counter() - started
        driver_started = time.perf_counter()
        container = json.loads(docker("exec", "-i", name, "python", "-",
                              input_text=DOCKER_DRIVER.replace("SAMPLES_PLACEHOLDER", repr(SAMPLES))))
        container["startup_to_readiness_seconds_approx"] = (driver_started - started) + container["readiness_after_driver_start_seconds"]
        container["docker_create_start_seconds"] = created
        container["docker_stats_after_warmup"] = json.loads(docker("stats", "--no-stream", "--format", "{{json .}}", name))
        # Wait for the image's own HEALTHCHECK, not only the driver's readiness poll.
        for _ in range(30):
            state = json.loads(docker("inspect", name))[0]["State"]
            if state.get("Health", {}).get("Status") == "healthy":
                break
            time.sleep(1)
        assert state["Health"]["Status"] == "healthy", state
        container["healthcheck"] = state["Health"]["Status"]
        assert json.loads(docker("inspect", name))[0]["HostConfig"]["NetworkMode"] == "none"
        assert container["server_uid"].split()[0] == "10001"
        differences = []
        for text in SAMPLES:
            for source, result in [("local", local["predictions"][text]), ("container", container["predictions"][text])]:
                target = expected[text]
                assert all(result[key] == target[key] for key in ["category", "source", "model_version"])
                difference = abs(result["confidence"] - target["confidence"]) if target["confidence"] is not None else 0
                assert difference < 1e-6, (text, source, difference)
                differences.append(difference)
        info = json.loads(docker("image", "inspect", image))[0]
        report = {"image": image, "image_id": info["Id"], "image_size_bytes": info["Size"],
                  "docker_image_list_size": docker("images", image, "--format", "{{.Size}}"),
                  "architecture": info["Architecture"], "host": platform.platform(),
                  "bundle_sha256": file_hash(bundle), "fallback_sha256": manifest["fallback_sha256"],
                  "catalogue_sha256": manifest["catalogue_sha256"], "local": local, "container": container,
                  "parity_samples": len(SAMPLES), "maximum_probability_difference": max(differences),
                  "artifact_bytes": sum(p.stat().st_size for p in (bundle.parent / manifest["model_directory"]).rglob("*") if p.is_file()),
                  "limitations": ["Single sequential client; one worker and one math thread; Docker limited to one CPU.",
                      "Warm filesystem caches; not a cold-machine boot or load/capacity test.",
                      "RSS and Docker/cgroup memory use different accounting; cgroup peak includes the small stdlib driver.",
                      "Local RSS peak sampled at about 100 ms during startup and each warm sequence; brief peaks can be missed.",
                      "p95 is an empirical nearest-order statistic over 160 warm requests, not a production guarantee.",
                      "Docker image list and inspect use differing storage accounting; retain both rather than treating inspect Size as unpacked disk use."]}
        write_json(output, report)
        return report
    finally:
        docker("rm", "--force", name)


def main() -> None:
    """Run reversible local verification, leaving any existing containers untouched."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="spendcheck-classifier:v1")
    parser.add_argument("--bundle", type=Path, default=ROOT / "bundles/default/manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/verification/resources.json")
    args = parser.parse_args()
    print(json.dumps(benchmark(args.image, args.bundle, args.output), indent=2))


if __name__ == "__main__":
    main()
