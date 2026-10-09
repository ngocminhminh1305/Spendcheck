# Spendcheck — Module 1

Extract amount, merchant, and date from one English spending transaction.
V1 runs locally: preprocessing → rules → spaCy → GLiNER → validation → JSON.
Fine-tuning, LLMs, and deployment are deferred to RONIN.

## Setup and run

From the Spendcheck folder, use your existing environment:

```bash
source /Users/ngocminh/Desktop/venvs/DSA2111/bin/activate
python3 -m pip install -r requirements.txt
python3 -m spacy download en_core_web_sm
python3 -m uvicorn app.main:app --reload
```

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

## Test and inspect

```bash
python3 -m pytest -q
python3 -m app.inspect
python3 -m app.smoke_api
```

Pytest uses controlled model outputs without loading weights. Inspection runs real
models on 32 development cases. The HTTP smoke test needs Uvicorn running and
should report **9 checks passed; 0 failed**.

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
