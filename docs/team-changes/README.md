# Changes made to Modules 1 and 3 during integration

Integration lead: Okaggar. The originals are untouched in `incoming/team-repo` (clone of
github.com/ngocminhminh1305/Spendcheck at commit c7166c2). Our working copies are in
`services/extractor` and `services/forecaster`. Every change is marked in the code with a comment
starting "Spendcheck integration change". Full diffs: `extractor.diff`, `forecaster.diff`.

Please review; if you agree, these can go into the team repo as they are.

## Module 1: extractor (Pham Ngoc Minh)

| Change | Why | Files |
|---|---|---|
| Ride entries: "grab to school 14.60" -> merchant `grab` | "to" was read as "paid to <merchant>", so the destination became the merchant: "grab to school 14.60" extracted nothing ("school" is a generic word) and "taxi to airport 30" gave merchant `airport`. A ride word (grab, gojek, tada, ryde, zig, cdg, comfortdelgro, taxi, cab, uber, bus, mrt, train) followed by "to/from" now marks the ride provider as the merchant, the same way subscriptions are handled | `app/extractor.py` (`_TRIP`, `extract_trip_provider`), `app/layered.py` (`strong_rule_merchant`) |
| Load spaCy and GLiNER at startup | the first entry that needed a model took ~22 s; now < 1 s (startup takes ~30 s instead). `EXTRACTOR_WARMUP=0` turns it off | `app/main.py` |
| Dockerfile + .dockerignore | the module had none; CPU-only PyTorch, models baked into the image (3.2 GB), runs as a non-root user | `Dockerfile`, `.dockerignore` |
| 10 new tests | rides, a ride with a date, and checks that non-ride "to" entries are unchanged | `tests/test_trips.py` |

All 151 original tests still pass (161 with the new ones). Rule changes can change your
development-set numbers, so please re-run `python3 -m app.inspect` before reporting results.

## Module 3: forecaster (Muhaimin Ihsan)

| Change | Why | Files |
|---|---|---|
| One-off purchases kept out of the spending pace | a demo user who bought a $329 phone on day 6 had $846 spent by day 16, and the `ml` forecast was $875: only $29 more for the rest of the month. The model learned on Berka, where big payments are early-month bills, so a high month-to-date looks like "month nearly done". A purchase is a one-off when it is at least 5x the user's median past purchase and at least 20% of their usual month. The API forecasts the rest and adds one-offs back; this user's forecast is now $1,186 | `app/features.py` (`one_off_spend`), `app/main.py` |
| `one_off_spend` field in the response | so callers (and Module 4's chat agent) can explain the forecast; defaults to 0 | `app/schemas.py` |
| 3 new tests | a large purchase is added once, not extrapolated; ordinary purchases and users without history are unaffected | `tests/test_one_offs.py` |

`predict()`, the trained model and `scripts/evaluate_berka.py` are unchanged, so the Berka MAE
results in your README stay valid. All 21 original tests still pass (24 with the new ones).
