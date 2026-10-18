# Spendcheck

Spendcheck is our team's spending transaction project. The current local V1
extractor turns one English spending transaction into amount, merchant, and date.

The extractor lives in [services/extractor/](services/extractor/README.md), with
its own application, data, tests, dependencies, and setup instructions.

The merchant categoriser lives in
[services/categoriser/](services/categoriser/README.md). It automatically assigns
one of nine spending categories using a verified merchant catalogue and a MiniLM
classifier fallback; its README covers the standalone API, Docker setup and tests.

The spending forecaster (Module 3) lives in
[services/forecaster/](services/forecaster/README.md). It predicts end-of-month
spending and raises a budget-risk alert. Run its commands, including `pytest`,
from `services/forecaster/`; it has its own `pytest.ini` because both modules
use a package named `app`.

Teammates should add modules under `services/<module_name>/`, keeping each
module's code, data, tests, dependencies, and README together. Shared repository
configuration stays at the root.

Run extractor setup, Docker, and test commands from `services/extractor/` as
documented in its README. Each service owns its pytest configuration and runs
tests separately because both services use a package named `app`.
To run extractor tests from the repository root, activate an environment with
the extractor dependencies installed and run:

```bash
python3 -m pytest -c services/extractor/pytest.ini services/extractor/tests -q
```
