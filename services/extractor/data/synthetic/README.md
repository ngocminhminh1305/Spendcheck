# Development examples and labeling policy

`development.json` contains 32 manually specified synthetic examples and expected
outputs. Labels were written independently of the extractor. They are a working
contract for V1, not a final benchmark, training set, or proof of general accuracy.

Policy for this checkpoint:

- One English spending transaction per request. Explicit multiple transactions
  are out of scope: all three fields are null rather than mixing transactions.
- Positive amounts with up to two decimal places; zero and negative amounts are
  unsupported. A quantity (such as two coffees) is not the transaction total.
- Merchant names preserve input spelling and case, including unknown names and
  typos. Meal descriptions such as "lunch" are not merchant names.
- Dates use the supplied reference datetime's local calendar date. Numeric dates
  use day/month/year except ISO year-month-day. Invalid dates remain null.
- Missing dates are not silently replaced with today. Unambiguous date typos
  such as "yesterdat" may normalize to yesterday.
- If a single field is ambiguous, that field remains null. For example, "$8 or
  $9" has no unique amount, but its merchant and date can still be extracted.
- For this output schema, missing, invalid, unsupported, and unresolved fields
  all appear in `missing_fields`; a richer error schema can be considered later.

The updated rules satisfy these examples, with extraction assertions in
`tests/test_baseline_safety.py`. This development success does not establish
general accuracy. Preserve the correct labels when an extractor fails; improve
the extractor instead of changing labels to match it.

From `services/extractor/`, run `python3 -m app.inspect --mode rules` to inspect
mismatches. This saves generated
predictions separately under `data/outputs/rules_predictions.json`.
`tests/test_development_data.py` validates label consistency only; passing those
tests does not mean the extractor successfully handles the dataset.
