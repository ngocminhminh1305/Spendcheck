# Spendcheck — Module 1

Extract amount, merchant, and date from one English spending transaction.
V1 runs locally: preprocessing → rules → spaCy → GLiNER → validation → JSON.
Docker packages the CPU API for local use. Fine-tuning, LLMs, and deployment
are deferred to RONIN.

## Setup and run

From the Spendcheck repository root, enter the extractor directory. Run all
commands below from that directory so Python can find the local `app` package:

```bash
cd services/extractor
python3.14 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m spacy download en_core_web_sm
python3 -m uvicorn app.main:app --reload
```

If you already have an environment with these dependencies, activate it instead
of creating `.venv`. For the existing local setup, use
`source /Users/ngocminh/Desktop/venvs/DSA2111/bin/activate`.

Open [API docs](http://127.0.0.1:8000/docs) and try `POST /extract`:

```json
{
  "text": "spent $8.90 at Kopitiam yesterday",
  "reference_datetime": "2026-10-06T18:30:00+08:00"
}
```

Expected: `{"amount":8.9,"merchant":"Kopitiam","date":"2026-10-05","status":"ok","missing_fields":[]}`.

The reference datetime requires a timezone offset. Missing or rejected fields
return null and `status: "incomplete"`. `/health` checks the service; `/` has no route.

Models load on demand, run on CPU, and are cached per process. The first GLiNER
request downloads weights. Model setup failures return HTTP 503.
Versions are pinned for the tested macOS / Python 3.14 environment.

## Run with Docker

Start Docker Desktop (or a Docker Engine), then run from `services/extractor/`:

```bash
docker build --load -t spendcheck-extractor .
docker run --rm --name spendcheck-extractor -p 127.0.0.1:8001:8000 spendcheck-extractor
```

Open [API docs](http://127.0.0.1:8001/docs). The host uses port 8001; Uvicorn
listens on port 8000 inside the container. Stop it with Ctrl+C.
Rebuild the image after changing code; the container runs without auto-reload.

The image uses Python 3.14 on Linux, the pinned requirements, and one CPU worker.
PyTorch comes from its official CPU wheel index at the same pinned version,
avoiding unnecessary CUDA dependencies.
The first build needs internet access to install dependencies and download both
`en_core_web_sm` and `urchade/gliner_small-v2.1`. It may take several minutes
and creates a large image because it includes PyTorch and model weights.
Later code-only builds reuse the dependency and model layers.

Models load on demand from the image's bundled assets. `HF_HUB_OFFLINE=1`
disables Hugging Face downloads at runtime; no host model cache or volume is
needed. The API runs as a non-root user. Tests, development data, local virtual
environments, and generated reports are excluded from the build context.

In another terminal, check HTTP availability and real model extraction:

```bash
docker inspect --format '{{.State.Health.Status}}' spendcheck-extractor
docker exec spendcheck-extractor python -m app.smoke_api
```

The health status checks only `/health`, so it does not prove that models load.
The smoke test exercises spaCy and GLiNER fallback and should report
**9 checks passed; 0 failed**. Its first extraction can take over a minute while
models load into memory; the smoke script allows 180 seconds per request.
You can also run the smoke test from an activated local
environment with `python3 -m app.smoke_api --base-url http://127.0.0.1:8001`.

Tests run separately in your local development environment as described below.
The runtime image does not include the test suite. Docker Compose integration
with the other services is a later step.

## Test and inspect

```bash
python3 -m pytest -q
python3 -m app.inspect
python3 -m app.smoke_api
```

Pytest uses controlled model outputs without loading weights. Inspection runs real
models on 32 development cases. The HTTP smoke test needs Uvicorn running and
should report **9 checks passed; 0 failed**.

The module owns `pytest.ini`. Run each service's tests separately to avoid
collisions between their packages named `app`. From the repository root, use:

```bash
python3 -m pytest -c services/extractor/pytest.ini services/extractor/tests -q
```

One inspection command supports every layer:

```bash
python3 -m app.inspect --mode rules
python3 -m app.inspect --mode spacy
python3 -m app.inspect --mode gliner
python3 -m app.inspect --text 'Yesterday Kopitiam charged me $8' --reference '2026-10-06T18:30:00+08:00'
```

Default mode is `pipeline`. Raw spaCy/GLiNER inspection also accepts `--text`
without a reference. Only raw GLiNER mode accepts a custom `--threshold`.
Reports go to `data/outputs/<mode>_predictions.json` or `<mode>_custom.json`.
These paths are relative to `services/extractor/`; input and output paths are
resolved from the source file location, independently of the shell directory.
Pipeline reports include field sources and decision history; offsets refer to
cleaned text. Inspection reports mismatches but does not act as a pass/fail test.

## Files

- `app/main.py`, `schemas.py`: API and request/response shapes.
- `app/pipeline.py`: preprocessing and extraction entry points.
- `app/extractor.py`, `layered.py`: rules, validation, fallback decisions.
- `app/spacy_extractor.py`, `gliner_extractor.py`: pretrained model adapters.
- `app/inspect.py`, `smoke_api.py`: local inspection and HTTP checks.
- `tests/`: regression tests.
- `data/synthetic/`: development inputs and expected labels.
- `data/outputs/`: generated reports, ignored by Git.

## Extraction policy and limits

Fallback handles only missing or uncertain fields; accepted and rejected fields
are protected. GLiNER acceptance requires a score of at least 0.7, which is a
heuristic, not an accuracy guarantee. Raw inspection defaults to 0.5.

Support is limited to one transaction with a positive amount. Ambiguous fields,
unsupported dates, and obvious multiple transactions remain unresolved. Merchant
spelling is preserved. Subscription rules remove trailing plan descriptors,
which can be imperfect for business names ending in those words.

See [labeling policy](data/synthetic/README.md). Development success does not
guarantee accuracy on unseen text. The API does not save transaction text;
inspection commands do. Model loading can contact Hugging Face, but inference
runs locally.
