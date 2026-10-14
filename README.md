# Spendcheck

Spendcheck is our team's spending transaction project. The current local V1
extractor turns one English spending transaction into amount, merchant, and date.

The extractor lives in [services/extractor/](services/extractor/README.md), with
its own application, data, tests, dependencies, and setup instructions.

The spending forecaster (Module 3) lives in
[services/forecaster/](services/forecaster/README.md). It predicts end-of-month
spending and raises a budget-risk alert. Run its commands, including `pytest`,
from `services/forecaster/`; it has its own `pytest.ini` because both modules
use a package named `app`.

Teammates should add modules under `services/<module_name>/`, keeping each
module's code, data, tests, dependencies, and README together. Shared repository
configuration stays at the root.

Run extractor setup and startup commands from `services/extractor/` as documented
in its README. Tests can also run from the repository root with
`python3 -m pytest -q` in an environment with the extractor dependencies installed.
The root `pytest.ini` currently discovers the extractor tests and adds its
directory to the test import path; extend test discovery when more modules arrive.
