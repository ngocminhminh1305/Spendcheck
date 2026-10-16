"""Run real HTTP checks against an already running local Spendcheck service."""

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REFERENCE = "2026-10-09T18:30:00+08:00"


def request(base_url, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(base_url + path, data=body, headers={"Content-Type": "application/json"})
    try:
        # A cold CPU container may need more than a minute to load GLiNER.
        with urlopen(req, timeout=180) as response:
            return response.status, response.read().decode()
    except HTTPError as exc:
        return exc.code, exc.read().decode()


def run_checks(base_url):
    passed = 0
    failed = 0

    def check(name, condition, actual):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"PASS {name}", flush=True)
        else:
            failed += 1
            print(f"FAIL {name}: {actual}", flush=True)

    status, body = request(base_url, "/health")
    check("health", status == 200 and json.loads(body) == {"status": "ok"}, body)
    status, body = request(base_url, "/docs")
    check("interactive docs", status == 200 and "swagger-ui" in body, f"HTTP {status}")

    for name, text, amount, merchant, date in [
        ("basic", "spent $8.90 at Kopitiam yesterday", 8.9, "Kopitiam", "2026-10-08"),
        ("spaCy fallback example", "Yesterday IKEA charged me $8", 8, "IKEA", "2026-10-08"),
        ("GLiNER fallback example", "Yesterday Kopitiam charged me $8", 8, "Kopitiam", "2026-10-08"),
        ("subscription", "subscribe quizlet premium today 88 dollars", 88, "quizlet", "2026-10-09"),
        ("missing date", "Kopitiam 8", 8, "Kopitiam", None),
        ("negative amount", "spent -$8 at Kopitiam today", None, "Kopitiam", "2026-10-09"),
    ]:
        expected = {"amount": amount, "merchant": merchant, "date": date}
        missing = [field for field, value in expected.items() if value is None]
        expected.update(status="incomplete" if missing else "ok", missing_fields=missing)
        status, body = request(base_url, "/extract", {"text": text, "reference_datetime": REFERENCE})
        check(name, status == 200 and json.loads(body) == expected, f"HTTP {status}: {body}")

    status, body = request(base_url, "/extract", {
        "text": "coffee today", "reference_datetime": "2026-10-09T18:30:00",
    })
    check("timezone validation", status == 422, f"HTTP {status}: {body}")
    print(f"\n{passed} checks passed; {failed} failed.")
    return failed == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        success = run_checks(args.base_url.rstrip("/"))
    except (URLError, TimeoutError) as exc:
        parser.exit(1, f"Cannot reach the API: {exc}\nStart it with python3 -m uvicorn app.main:app --reload\n")
    except json.JSONDecodeError as exc:
        parser.exit(1, f"API returned invalid JSON: {exc}\n")
    if not success:
        parser.exit(1)


if __name__ == "__main__":
    main()
