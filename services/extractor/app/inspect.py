"""Inspect rules, raw model candidates, or the complete pipeline."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from app import gliner_extractor, spacy_extractor
from app.layered import GLINER_ACCEPT_THRESHOLD
from app.pipeline import extract_transaction_with_trace


def inspect_case(case, mode, threshold):
    if mode == "spacy":
        return {**case, "entities": spacy_extractor.extract_spacy_entities(case["text"])}
    if mode == "gliner":
        return {**case, "entities": gliner_extractor.extract_gliner_entities(case["text"], threshold)}
    response, trace = extract_transaction_with_trace(
        case["text"], datetime.fromisoformat(case["reference_datetime"]),
        use_models=mode == "pipeline",
    )
    predicted = response.model_dump(mode="json")
    result = {**case, "predicted": predicted, "trace": trace}
    if "expected" in case:
        result["differences"] = {
            key: {"expected": value, "predicted": predicted[key]}
            for key, value in case["expected"].items() if predicted[key] != value
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pipeline", "rules", "spacy", "gliner"), default="pipeline")
    parser.add_argument("--text", help="Inspect one input instead of the development dataset")
    parser.add_argument("--reference", help="Timezone-aware ISO datetime for a custom transaction")
    parser.add_argument("--threshold", type=float, default=gliner_extractor.DEFAULT_THRESHOLD,
                        help="Raw GLiNER candidate threshold (GLiNER mode only)")
    args = parser.parse_args()
    if not 0 < args.threshold < 1:
        parser.error("--threshold must be between 0 and 1 (exclusive)")
    if args.mode != "gliner" and args.threshold != gliner_extractor.DEFAULT_THRESHOLD:
        parser.error("--threshold applies only to --mode gliner")

    root = Path(__file__).resolve().parents[1]
    if args.text is None:
        cases = json.loads((root / "data/synthetic/development.json").read_text())
    else:
        case = {"id": "custom", "text": args.text}
        if args.mode in ("pipeline", "rules"):
            try:
                reference = datetime.fromisoformat(args.reference or "")
                if reference.utcoffset() is None:
                    raise ValueError
            except ValueError:
                parser.error("--text requires --reference with a timezone in pipeline/rules mode")
            case["reference_datetime"] = reference.isoformat()
        cases = [case]

    results = []
    for case in cases:
        try:
            result = inspect_case(case, args.mode, args.threshold)
        except RuntimeError as exc:
            parser.exit(1, f"{exc}\nCause: {exc.__cause__}\n")
        results.append(result)
        print(f"{case['id']}: {json.dumps(result.get('predicted', result.get('entities')))}", flush=True)

    report = {"mode": args.mode, "cases": results}
    if args.mode == "gliner":
        report.update(model=gliner_extractor.MODEL_NAME, threshold=args.threshold)
    elif args.mode == "spacy":
        report["model"] = spacy_extractor.MODEL_NAME
    elif args.mode == "pipeline":
        report["gliner_accept_threshold"] = GLINER_ACCEPT_THRESHOLD
    suffix = "custom" if args.text is not None else "predictions"
    output = root / "data/outputs" / f"{args.mode}_{suffix}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    if args.text is None and args.mode in ("pipeline", "rules"):
        mismatches = sum(bool(item["differences"]) for item in results)
        print(f"{len(results)} development cases; {mismatches} with mismatches.")
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
