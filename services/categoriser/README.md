# Spendcheck Merchant Categoriser

Module 2 maps a merchant string to one of nine spending categories through an independent FastAPI/Docker service.

**Selected API version: merchant-categoriser-v1.** No training or network access is needed during inference.

## Architecture

Input validation → conservative normalisation → verified exact/alias catalogue lookup → frozen MiniLM + logistic-regression fallback.

Catalogue matching normalises Unicode, case, whitespace and documented leading payment markers. It preserves meaningful punctuation, uses explicit aliases and performs no fuzzy/substring matching. ML uses the same merchant cleaning as training and unit-normalised embeddings.

| Category | Merchant/service default |
|---|---|
| Food & Drink | Prepared food, cafés, drinks, hawkers and identifiable food delivery |
| Groceries | Supermarkets, convenience stores, specialist groceries and grocery delivery |
| Transport | Transit, rides, taxis, parking, vehicle rental/sharing and fuel |
| Shopping | General retail, marketplaces, household goods, stationery and general bookstores |
| Entertainment | Cinema, games, attractions, recreation, concerts and media subscriptions |
| Bills & Utilities | Telecoms, broadband, electricity, water, gas and identified household bills |
| Health | Clinics, hospitals, healthcare and pharmacy-oriented retailers |
| Education | Tuition, courses, educational services and explicitly identified textbooks |
| Other | Personal services and general-purpose software subscriptions outside the above |

Watsons/Guardian/Unity default to Health; Octobox to Groceries; general bookstores to Shopping; ChatGPT/Google Cloud to Other. The category describes the merchant/service, not individual purchased items.

## Repository structure

```text
app/                       FastAPI, catalogue matching and ML inference
models/minilm/             Selected classifier, offline encoder and original metadata
data/sources/              Source datasets and merchant verification records
data/prepared/             Frozen dataset, human labels, splits, folds and benchmark inputs
data/catalogues/           Runtime and recognition-evaluation merchant catalogues
bundles/default/           Active manifests and runtime metadata
bundles/evaluation/        Immutable manifest evidence referenced by saved results
bundles/training_encoders.json  Encoder revisions for optional training
scripts/                   Preparation, training, evaluation and verification commands
tests/                     Current automated tests
reports/selection/         TF-IDF, MiniLM and MPNet model-selection results
reports/evaluation/        Final A/B/C metrics and predictions
reports/gemini/            Development, A and C prompts, responses and scores
reports/verification/      Completed parity, readiness and resource checks
```

Optional training outputs go to ignored runs/reproduction/. They do not replace the deployed model or reported results.

## Requirements and assets

Use Python 3.12 locally or Docker Engine/Desktop. Build/install needs internet; inference uses bundled assets offline. Install the pinned runtime requirements, plus requirements-dev.txt for testing.

The selected model is sentence-transformers/all-MiniLM-L6-v2 (384-dimensional normalised embeddings) plus logistic regression with C=1 and balanced class weights, fitted to 280 rows. The active catalogue has 298 entries across 250 families.

Runtime assets, relative to this directory:

- app/*.py; requirements.txt and requirements-encoders.txt.
- bundles/default/manifest.json and metadata.json.
- models/minilm/ in full: 13 files, approximately 91.6 MB.
- data/catalogues/catalogue_post_selection.csv and catalogue_development.csv.

Preserve the exact encoder inventory: head, weights, tokenizer/configuration/pooling/normalisation files and upstream encoder README. The latter is a model card bound by checksums, not another component guide.
Docker packages only inference dependencies/code, selected manifest/metadata/model and the two catalogues. It excludes training data, reports, tests and original-source evidence.

## Local Python setup and configuration

From the Spendcheck repository root:

```bash
cd services/categoriser
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt -r requirements-encoders.txt
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8003 --workers 1
```

CLASSIFIER_BUNDLE optionally selects a compatible manifest; the default resolves relative to the module. Model/catalogue loading occurs once at startup and rejects mismatched assets. Offline flags and one math thread are set by Docker. Docker build arguments MODEL_DIRECTORY/BUNDLE select matching assets; retain defaults for this release. WITH_ENCODERS=0 cannot run the selected MiniLM.

## API

GET /health reports readiness, model_version and data_status. POST /classify takes only a strict merchant string. GET /docs provides interactive OpenAPI documentation.

Lookup confidence is null and source is lookup. Unmatched valid inputs receive the best model category with source=model and numeric **uncalibrated maximum class probability**, including below 0.50. Null is not a failure or 100% probability. There is no needs_review field or review workflow.

Missing/non-string/blank/punctuation-only/over-500-character input or extra fields produce HTTP 422. Bare Grab/Apple produce HTTP 422 ambiguity errors; specify the service. Probabilities are not verified correctness probabilities.

## Build and run

From repository root:

```bash
cd services/categoriser
docker build -f Dockerfile.hybrid -t spendcheck-classifier:v1 .
docker run --rm --name spendcheck-classifier -p 127.0.0.1:8003:8000 spendcheck-classifier:v1
```

From another terminal:

```bash
curl --fail http://127.0.0.1:8003/health
curl --fail -H 'Content-Type: application/json' -d '{"merchant":"NTUC FairPrice"}' http://127.0.0.1:8003/classify
```

Expected:

```json
{"category":"Groceries","confidence":null,"source":"lookup","model_version":"merchant-categoriser-v1"}
```

The gateway calls http://classifier:8000/classify if the integrator names the Compose service classifier. Use build context ./services/categoriser and dockerfile Dockerfile.hybrid. No Compose/gateway/frontend is implemented by this module.

Forward only the extracted merchant field. If merchant=null, handle incomplete extraction upstream without calling classification. Do not send amount/date or other extra fields.
Accept nullable confidence and source; absence of needs_review is intentional. Low confidence still yields a category. Bare Grab/Apple return 422 ambiguity errors; request-validation errors also return 422. Handle both detail shapes without treating them as outages or silently assigning Other. Merge successful category into a transaction with valid date and positive amount for the forecaster.

## Testing and training

Activate an existing Python 3.12 environment or create .venv; install requirements-dev.txt and requirements-encoders.txt. Then:

```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m scripts.prepare_hybrid check
python -m scripts.release_hybrid check
python -m scripts.verify_predictions
python -m pytest -q -p no:cacheprovider
python -m scripts.benchmark_hybrid --output reports/local/resources_check.json
```

Use a new report path when repeating checks; never overwrite frozen outputs. The full submitted test suite requires only shared resources, not ignored historical models. Toy fixture fits test orchestration; no project training is run by the tests.

Training is optional manual reproduction, not needed to deploy. All use the same frozen group split and train-only CV; TF-IDF C=1 and unweighted/balanced; encoders C=.1,1,10 and unweighted/balanced:

```bash
python -m scripts.new_dataset train tfidf --compare-class-weight
python -m scripts.new_dataset train minilm --compare-class-weight
```

MPNet weights are deliberately excluded from Git. To prepare its fixed original encoder revision, temporarily allow network access, then restore offline flags:

```bash
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE
python -m scripts.encoder_utils mpnet --output encoder_sources/mpnet
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python -m scripts.new_dataset train mpnet --compare-class-weight --encoder-dir encoder_sources/mpnet
```

Outputs default to runs/reproduction, never the reported selected model directory. Encoder preparation is explicit, version-pinned and refuses existing destinations. It is never called during inference.

The Dockerfile installs target-native CPU dependencies without an architecture hardcode. ARM64 is tested. Build and smoke-test directly on the target AMD64 host if applicable; do not assume ARM64 images run natively there.


## Authoritative comparison

| Benchmark | Local ML accuracy / macro-F1 | Hybrid accuracy / macro-F1 | Keyword accuracy / macro-F1 | Gemini accuracy / macro-F1 |
|---|---|---|---|---|
| Development (45) | 60.00% / .6010 | Not separately reported | Not consolidated here | **100% / 1.0000** |
| A unseen-family (47) | 59.57% / .5971 | 59.57% / .5971 | 25.53% / .2829 | **97.87% / .9852** |
| C operational (54) | 79.63% / .7901 | 83.33% / .8274 | 64.81% / .7023 | **98.15% / .9814** |

TF-IDF development: 44.44% / .5045; MPNet: 51.11% / .5407. Original comparison artifacts remain under reports/selection. Hyperparameters were selected on identical train-only group folds, not reserved-test outcomes.

B recognition: 54/54 positives matched, all 18 constructed near-matches stayed unmatched. Coverage 75% including deliberate negatives; matched accuracy 100%. This is catalogue-informed authored testing, not a blind accuracy estimate.
C contains 27 known and 27 unfamiliar cases, three per category/cohort. Hybrid: 27/27 known and 18/27 unfamiliar (66.67%, macro-F1 .6365). Lookup coverage 50%, matched accuracy 100%. The constructed mixture is not observed transaction frequency.
A/C use the post-selection catalogue; B uses the frozen development catalogue. All reserved families and operational unfamiliar families remain absent from the applicable catalogue/training.

## Gemini protocol and interpretation

Gemini 3.1 Pro with High thinking was run via chat in separate fresh conversations, using the same zero-shot instruction structure, nine category definitions and merchant inputs, with no labelled examples supplied. Chat settings/conversation procedure are user-reported; exact prompts, responses and scoring provenance are saved. Model building used supervised training/CV; this zero-shot baseline did not receive task demonstrations or training.

Gemini substantially outperformed the local system on these constructed benchmarks. This comparison does not isolate Singapore-specific training: model scale, pretraining and reasoning differ too. Zero-shot does not mean absence of merchant knowledge from pretraining. Offline operation and deterministic lookup are implementation properties; no Gemini latency/cost comparison was measured.
Gemini's only errors: Flexar → Shopping in A, Valu$ → Groceries in C.

Existing Gemini tasks/results remain at reports/gemini/development and reports/gemini/A_unseen and reports/gemini/C_operational. Do not paste private manifest labels into Gemini. To import a future saved response, use the existing task and a new result path:

```bash
python -m scripts.evaluate_hybrid import --task PATH_TO_EXISTING_TASK --predictions RESPONSE.csv --model-name 'ACTUAL MODEL' --run-date YYYY-MM-DD --output NEW_RESULT.json
```

## Limitations and report locations

372/372 merchant-description/category pairs are human-checked, including user-confirmed Sonic Bowl; they are constructed descriptions, not observed bank transactions or a newly collected independent test set. This count does not establish independent human checks of all additional B/C cases.
Some merchant families were examined in older development. A is reserved within a development corpus, not guaranteed independent blind data. C unfamiliar families were screened against supervised identities, not encoder pretraining or every possible corporate relationship. Small category supports limit generalisation claims. Merchant defaults do not identify individual purchased items.

The ML fallback remains moderately accurate for unfamiliar brands. Examples from frozen A: GrabFood → Groceries, National University Polyclinics → Education, Kinokuniya → Food & Drink. These errors were not used to change the classifier or catalogue. Probabilities are uncalibrated; null lookup confidence is a deterministic mapping, not a probability.

Per-category metrics, confusion matrices and predictions remain under reports/evaluation/A_unseen, B_recognition, C_operational. Lookup-only CSV matrices include unmatched cases explicitly; the old nine-label JSON matrix omits that column. Original results are preserved rather than rewritten. Source parity and resource measurements are under reports/verification.


## Frozen data, metrics and integrity

data/prepared/merchant_dataset.csv has merchant_text,merchant_group,category: 372 descriptions / 291 families, partitioned into 280 train / 45 validation / 47 reserved test rows. All 372 description/category pairs are human-checked. They are constructed descriptions, not observed transactions or a newly collected independent test set.

split.csv preserves row/family assignments; folds.csv fixes shared three-fold training CV. Preparation checks seven necessary CSVs in data/sources/: new_merchant_dataset/new_merchant_split (original inputs/assignments), hybrid_additions/hybrid_sources/hybrid_operational_unfamiliar (expansion and evaluation sources), merchant_checks (verification sources) and merchant_review (screening unfamiliar identities against earlier examined names). These are retained because scripts.prepare_hybrid reads them and verifies their recorded hashes.

TF-IDF combines word/character features with C=1. Frozen MiniLM/MPNet search C=.1,1,10. Unweighted/balanced choices use identical train-only group CV and mean macro-F1; ties prefer unweighted, then smaller C. TF-IDF vocabulary fits within each fold; embeddings are cached once and reused across fits. Validation selects the architecture; reserved tests are not used for fitting or selection.

reports/selection/{tfidf,minilm,mpnet}/ retain summaries, train/validation JSON metrics and validation predictions. Per-category results and confusion matrices already exist in those JSON files, so duplicate CSV exports are excluded. TF-IDF/MPNet training_metadata.json preserve actual CV/selection provenance without their weights; MiniLM metadata already accompanies its selected artifact.

Final reports/evaluation/{A_unseen,B_recognition,C_operational}/ retain metrics and predictions. Lookup-only confusion CSVs are also retained because they explicitly include unmatched cases omitted by the original nine-label JSON matrix.

bundles/default/ is the sole deployable release bundle. manifest.json selects the default catalogue and model; recognition_manifest.json is an evaluation configuration using B's frozen catalogue, with the same public model version. metadata.json binds the cleaned preprocessing source to the unchanged model weights.

bundles/evaluation/ retains the exact manifests identified by frozen evaluation, parity and resource reports. Their paths are historical identifiers, not runtime configuration. Current bundles/default/ manifests select the files in this repository and record their current runtime-source hashes. Original model metadata and preparation/Gemini manifests remain byte-for-byte unchanged; preparation resolves their logical source filenames under data/sources/ and catalogue filenames under data/catalogues/. Checks still validate every recorded file hash. The historical application is excluded, so original source hashes cannot reconstruct that executable. scripts.verify_predictions instead compares the current release directly with the 218 saved validation/A/B/C predictions, including ML confidence within 1e-6. No training, selection or report rewriting occurs.

reports/verification/evaluated_readiness.json retains the original pre-evaluation readiness evidence identified by the evaluated manifest. 

reports/verification/parity.json records a completed development comparison on 226 validation/test/recognition/operational/regression inputs: categories and sources were identical, with maximum same-platform probability difference zero. This is evidence for those checked inputs, not proof of equivalence on every input. The historical comparison cannot be rerun from the submitted files because the original executable source is excluded. Original source is not claimed to be byte-identical to cleaned source. Frozen release-time human-review counts are historical; human_labels.csv records the current 372/372 checks.

reports/verification/resources.json records ARM64 measurements with one worker/math thread: Docker readiness about 3.4 s, model HTTP p95 about 11.18 ms, Docker warm memory about 389 MiB (process RSS about 528 MiB). The offline container passed 17 HTTP checks and eight local/container parity samples at numerical tolerance 1e-6. These are sequential warm-cache measurements, not production capacity guarantees. Native AMD64 build/startup verification remains required on that target.

## Reproducing evaluation

Use fresh output directories; original results refuse overwrite:

```bash
python -m scripts.evaluate_hybrid score --evaluation unseen --bundle bundles/default/manifest.json --output reports/local/recheck_A
python -m scripts.evaluate_hybrid score --evaluation recognition --bundle bundles/default/recognition_manifest.json --output reports/local/recheck_B
python -m scripts.evaluate_hybrid score --evaluation operational --bundle bundles/default/manifest.json --output reports/local/recheck_C
```

Gemini tasks already have saved responses/results. For blinded exports use scripts.evaluate_hybrid export with --evaluation, --bundle and a new --output. Paste only prompt.txt; manifests contain private scoring labels. For imports supply the task directory, response CSV, actual model/run date and a new result path. Never provide correct labels to the LLM.

## Repository contents

Git includes application/deployment source, selected model, checked data/source records, current tests/training/evaluation scripts and final comparison evidence. Historical datasets/spreadsheets, non-selected weights, redundant report tables, development notes, caches and environments remain local but are excluded by the submission allowlist.
