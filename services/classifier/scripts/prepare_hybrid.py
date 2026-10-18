"""Prepare/check versioned hybrid resources without fitting or scoring models."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import unicodedata

from app.catalogue import MerchantCatalogue, normalise_merchant
from app.model import file_hash
from app.settings import CATEGORIES, DATA, ROOT
from scripts.common import read_csv, write_csv, write_json
from scripts.new_dataset import dataset_rows, fold_rows, SPLIT_FIELDS

DIRECTORY = DATA / "prepared"
SOURCES = DATA / "sources"
CATALOGUES = DATA / "catalogues"
FIELDS = ["merchant_text", "merchant_group", "category"]
# These are genuine short brands/product names or explicitly identified services.
# Artificial explanatory phrases in the older CSV are NOT automatically lookup aliases.
OMIT = {
    "foodpanda food delivery", "foodpanda groceries", "NUS Co-op textbooks",
    "POPULAR textbooks", "Singtel mobile", "Singtel broadband", "M1 broadband",
    "PUB water bill", "SP utilities bill", "City Energy gas bill", "SMRT buses/trains",
    "SMRT train fare", "SMRT bus fare", "SBS Transit bus fare", "ComfortDelGro taxi",
    "Grab rides", "SimplyGo transit fares", "SimplyGo bus fare", "SimplyGo MRT fare",
    "GetGo car sharing", "Shell petrol", "Esso petrol", "Caltex petrol",
    "Golden Village cinema", "USS admission", "Gardens by the Bay admission",
    "Berries Chinese enrichment", "Udemy course", "British Council English course",
    "NUS tuition fees", "National University of Singapore tuition", "NTU tuition fees",
    "Nanyang Technological University tuition", "SMU tuition fees",
    "Singapore Management University tuition", "OpenAI subscription",
    "Adobe Acrobat subscription", "Zoom Workplace subscription", "SingPost postage",
    "SingPost parcel delivery", "Helpling home cleaning", "LaundryMart dry cleaning",
    "Luce home cleaning", "Little Farms groceries", "StarHub mobile", "StarHub broadband",
    "Kumon English",
}
ALIASES = [
    ("NTUC FairPrice", "fairprice", "Groceries"),
    ("K-Market", "koryomart", "Groceries"),
    ("McDonalds", "mcdonalds", "Food & Drink"),
    ("SMRT", "smrt", "Transport"),
    ("SMRT Buses", "smrt", "Transport"),
    ("GetGo Carsharing", "getgo", "Transport"),
    ("Challenger MOBILE", "challenger", "Shopping"),
    ("SKS Bookstore", "sksbooks", "Shopping"),
    ("BOUNCE", "bouncesingapore", "Entertainment"),
    ("TeoHeng KTV", "teohengktv", "Entertainment"),
    ("Whiz Communications", "whizcomms", "Bills & Utilities"),
    ("British Council", "britishcouncilsingapore", "Education"),
    ("Kaplan", "kaplansingapore", "Education"),
    ("OpenAI", "openai", "Other"),
    ("Grab ride", "grab", "Transport"),
]


def source_file(name: str) -> Path:
    """Locate a source by its frozen logical filename, independent of historical directories."""
    return SOURCES / Path(name).name


def prepared_file(name: str) -> Path:
    """Resolve frozen prepared-file identifiers to data or runtime catalogue storage."""
    return (CATALOGUES if name.startswith("catalogue_") else DIRECTORY) / name


def identity(text: str) -> str:
    """Compare family/name identities without case, spacing, punctuation or accents."""
    return re.sub("[^a-z0-9]", "", unicodedata.normalize("NFKD", text.casefold()))


def save_once(path: Path, rows: list[dict], fields: list[str]) -> None:
    """Never replace a previously frozen CSV, including a partial preparation run."""
    if path.exists():
        raise ValueError(f"Already exists; preserve it: {path}")
    write_csv(path, rows, fields)


def partition_summary(rows: list[dict]) -> dict:
    """Summarise row, merchant-family and category coverage for every partition."""
    return {part: {"rows": len(selected),
                   "families": len({r["merchant_group"] for r in selected}),
                   "categories": dict(Counter(r["category"] for r in selected))}
            for part in ["train", "validation", "test"]
            for selected in [[r for r in rows if r["split"] == part]]}


def build_recognition(catalogue: list[dict]) -> list[dict]:
    """Freeze 72 authored recognition checks; do not claim blind/human collection."""
    result = []
    alias_names = {text for text, _, _ in ALIASES} | {
        "Yo-Chi", "FairPrice Finest", "SGH", "SNEC", "SIMBA Telecom", "MyRepublic Broadband",
        "ChatGPT Plus", "Canva Pro", "Dropbox Plus"}
    for category in CATEGORIES:
        available = [r for r in catalogue if r["category"] == category]
        canonical = [r for r in available if r["merchant_text"] not in alias_names][:2]
        aliases = [r for r in available if r["merchant_text"] in alias_names][:2]
        if len(aliases) != 2 or len(canonical) != 2:
            raise ValueError(f"Need two sourced recognition aliases and names for {category}")
        for kind, selected in [("exact", canonical), ("alias", aliases),
                               ("formatting", canonical), ("near_match", canonical)]:
            for row in selected:
                text = row["merchant_text"]
                if kind == "formatting":
                    text = "  " + "  ".join(text.upper().split()) + "  "
                elif kind == "near_match":
                    # Explicit synthetic negatives test substring rejection, not real merchant identities.
                    text += " unrelated business"
                result.append({"case_id": f"B{len(result)+1:03d}", "merchant_text": text,
                               "merchant_group": row["merchant_group"], "category": category,
                               "case_type": kind, "expected_match": str(kind != "near_match").lower()})
    return result


def build_operational(catalogue: list[dict], recognition: list[dict], unfamiliar: list[dict]) -> list[dict]:
    """Freeze a disjoint-input 50/50 mixture before any model prediction."""
    used = {r["merchant_text"] for r in recognition}
    result = []
    for category in CATEGORIES:
        candidates = [r for r in catalogue if r["category"] == category and r["merchant_text"] not in used]
        selected, families = [], set()
        for row in candidates:
            if row["merchant_group"] not in families:
                selected.append(row)
                families.add(row["merchant_group"])
            if len(selected) == 3:
                break
        if len(selected) != 3:
            raise ValueError(f"Insufficient known operational families for {category}")
        for row in selected:
            result.append({**row, "cohort": "known"})
        for row in unfamiliar:
            if row["category"] == category:
                result.append({**row, "cohort": "unfamiliar"})
    return [{"case_id": f"C{i:03d}", **row} for i, row in enumerate(result, 1)]


def prepare() -> None:
    """Build expanded data, staged catalogues, folds and frozen evaluation inputs once."""
    if DIRECTORY.exists():
        raise ValueError("Hybrid data already prepared; use check, never overwrite")
    base = read_csv(SOURCES / "new_merchant_dataset.csv")
    original = read_csv(SOURCES / "new_merchant_split.csv")
    additions = read_csv(SOURCES / "hybrid_additions.csv")
    unfamiliar = read_csv(SOURCES / "hybrid_operational_unfamiliar.csv")
    old_groups = {r["merchant_group"]: r["split_group"] for r in original}
    forbidden = {r["split_group"] for r in original if r["split"] != "train"}
    if any(r["merchant_group"] in old_groups for r in additions):
        raise ValueError("Expansion should add new families, not aliases of old ones")
    # Kopitiam is explicitly identified as FairPrice-affiliated in the current OTH directory.
    extra_relations = {"kopitiam": "fairprice"}
    dataset = DIRECTORY / "merchant_dataset.csv"
    save_once(dataset, base + additions, FIELDS)
    rows = dataset_rows(dataset)
    previous = {r["row_id"]: r for r in original}
    for row in rows:
        if row["row_id"] in previous:
            row.update(split=previous[row["row_id"]]["split"])
        else:
            row.update(split="train", split_group=extra_relations.get(row["merchant_group"], row["split_group"]))
        if row["split"] == "train" and row["split_group"] in forbidden:
            raise ValueError("Expansion leaks a protected family")
    save_once(DIRECTORY / "split.csv", rows, SPLIT_FIELDS)
    _, folds = fold_rows([r for r in rows if r["split"] == "train"])
    save_once(DIRECTORY / "folds.csv", folds, ["row_id", "split_group", "fold"])
    catalogue = [{k: r[k] for k in FIELDS} for r in rows if r["merchant_text"] not in OMIT]
    existing = {normalise_merchant(r["merchant_text"]) for r in catalogue}
    for text, group, category in ALIASES:
        if normalise_merchant(text) not in existing:
            catalogue.append(dict(zip(FIELDS, [text, group, category])))
            existing.add(normalise_merchant(text))
    stages = {
        "development": [r for r in catalogue if old_groups.get(r["merchant_group"], extra_relations.get(r["merchant_group"], r["merchant_group"])) not in forbidden],
        "post_selection": [r for r in catalogue if old_groups.get(r["merchant_group"], r["merchant_group"]) not in
                           {r["split_group"] for r in original if r["split"] == "test"}],
    }
    for stage, entries in stages.items():
        MerchantCatalogue(entries)
        save_once(CATALOGUES / f"catalogue_{stage}.csv", entries, FIELDS)
    # Recognition and operational validation do not execute the classifier.
    recognition = build_recognition(stages["development"])
    operational = build_operational(stages["development"], recognition, unfamiliar)
    save_once(DIRECTORY / "recognition.csv", recognition, list(recognition[0]))
    save_once(DIRECTORY / "operational.csv", operational, list(operational[0]))
    # Review actual description/label pairs, with no invented human approvals.
    save_once(DIRECTORY / "human_labels.csv",
              [{**r, "human_checked": ""} for r in base + additions], FIELDS + ["human_checked"])
    save_once(DIRECTORY / "canonical_labels.csv",
              [dict(zip(["merchant_group", "category", "human_checked"], [g, c, ""]))
               for g, c in sorted({(r["merchant_group"], r["category"]) for r in base + additions})],
              ["merchant_group", "category", "human_checked"])
    sources = read_csv(SOURCES / "merchant_checks.csv") + read_csv(SOURCES / "hybrid_sources.csv")
    save_once(DIRECTORY / "merchant_checks.csv", sources, ["merchant_group", "source_url", "notes"])
    input_paths = [SOURCES / name for name in ["new_merchant_dataset.csv", "new_merchant_split.csv",
                                           "hybrid_additions.csv", "hybrid_sources.csv", "hybrid_operational_unfamiliar.csv",
                                           "merchant_review.csv", "merchant_checks.csv"]]
    frozen = [p for folder in [DIRECTORY, CATALOGUES] for p in folder.glob("*.csv") if p.name not in {"human_labels.csv", "canonical_labels.csv"}]
    manifest = {"version": "hybrid-v1", "seed": 42, "assignment_method": "preserve base; additions training-only",
                "partitions": partition_summary(rows), "dataset_rows": len(rows),
                "dataset_families": len({r["merchant_group"] for r in rows}),
                "extra_split_relations": extra_relations,
                "input_hashes": {str(p.relative_to(ROOT)): file_hash(p) for p in input_paths},
                "file_hashes": {p.name: file_hash(p) for p in frozen},
                "catalogues": {"A_development": "catalogue_development.csv",
                               "A_final_unseen": "catalogue_post_selection.csv",
                               "B_recognition": "catalogue_development.csv",
                               "C_operational": "catalogue_post_selection.csv"},
                "operational_composition": {"known": 27, "unfamiliar": 27, "representative_frequency": False},
                "recognition_method": "72 AI-authored sourced-name/alias and constructed formatting/negative cases; not blind human data",
                "final_predictions": "not run", "human_checked_rows": 0,
                "limitations": ["Earlier source pool and development benchmarks already examined.",
                                "Final unfamiliar families screened against old supervised identities, not encoder pretraining."]}
    write_json(DIRECTORY / "manifest.json", manifest)
    check()


def check() -> dict:
    """Validate hashes, protected families and evaluation membership without predictions."""
    manifest = json.loads((DIRECTORY / "manifest.json").read_text())
    for rel, digest in manifest["input_hashes"].items():
        if file_hash(source_file(rel)) != digest:
            raise ValueError(f"Preparation source changed: {rel}")
    for name, digest in manifest["file_hashes"].items():
        if file_hash(prepared_file(name)) != digest:
            raise ValueError(f"Frozen file changed: {name}")
    rows, original = read_csv(DIRECTORY / "split.csv"), read_csv(SOURCES / "new_merchant_split.csv")
    expected = {r["row_id"]: r for r in original}
    found = {r["row_id"]: r for r in rows}
    for identifier, row in expected.items():
        if found.get(identifier) != row:
            raise ValueError("Original split/text/labels changed")
    groups = {}
    for row in rows:
        if groups.setdefault(row["split_group"], row["split"]) != row["split"]:
            raise ValueError("Cross-partition family")
    _, folds = fold_rows([r for r in rows if r["split"] == "train"])
    if folds != read_csv(DIRECTORY / "folds.csv"):
        raise ValueError("Training folds changed")
    protected = {r["merchant_group"] for r in rows if r["split"] != "train"}
    test_groups = {r["merchant_group"] for r in rows if r["split"] == "test"}
    development = read_csv(CATALOGUES / "catalogue_development.csv")
    post = read_csv(CATALOGUES / "catalogue_post_selection.csv")
    if protected & {r["merchant_group"] for r in development} or test_groups & {r["merchant_group"] for r in post}:
        raise ValueError("Protected family in catalogue")
    for entries in [development, post]:
        catalogue = MerchantCatalogue(entries)
        for row in entries:
            if catalogue.match(row["merchant_text"]) != row or catalogue.match("  " + row["merchant_text"].upper() + "  ") != row:
                raise ValueError("Exhaustive catalogue check failed")
    unfamiliar = [r for r in read_csv(DIRECTORY / "operational.csv") if r["cohort"] == "unfamiliar"]
    historical = read_csv(SOURCES / "merchant_review.csv")
    forbidden_names = {identity(r.get("canonical_merchant", "")) for r in historical}
    forbidden_names |= {identity(r["merchant_group"]) for r in historical + rows + post}
    forbidden_names |= {identity(r["merchant_text"]) for r in rows + post}
    if any(identity(r["merchant_text"]) in forbidden_names or identity(r["merchant_group"]) in forbidden_names for r in unfamiliar):
        raise ValueError("Operational unfamiliar identity previously present")
    if any(r["merchant_text"].casefold() == "bluesg" for r in rows + post + unfamiliar):
        raise ValueError("BlueSG excluded")
    labels = {(r["merchant_text"], r["merchant_group"]): r["category"] for r in rows}
    human_rows = read_csv(DIRECTORY / "human_labels.csv")
    if len(human_rows) != len(rows) or {(r["merchant_text"], r["merchant_group"]) for r in human_rows} != set(labels):
        raise ValueError("Human label sheet must preserve every description exactly once")
    for row in human_rows:
        if row["human_checked"].strip().lower() not in {"", "yes"}:
            raise ValueError("Human check field accepts blank or yes; record needed corrections separately")
        if labels[(row["merchant_text"], row["merchant_group"])] != row["category"]:
            raise ValueError("Human label correction found: prepare a new version before training")
    checked = sum(r["human_checked"].strip().lower() == "yes" for r in human_rows)
    print(json.dumps({"dataset_rows": len(rows), "partitions": manifest["partitions"],
                      "catalogue_development_entries": len(development), "catalogue_post_selection_entries": len(post),
                      "recognition_cases": len(read_csv(DIRECTORY / "recognition.csv")),
                      "operational_cases": len(read_csv(DIRECTORY / "operational.csv")),
                      "human_checked_description_rows": checked,
                      "preparation_snapshot_prediction_status": manifest["final_predictions"],
                      "note": "Preparation snapshot is historical; later evaluation outputs are separate."}, indent=2))
    return manifest


def main() -> None:
    """Expose one-time preparation and repeatable non-scoring integrity checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "check"])
    args = parser.parse_args()
    prepare() if args.command == "prepare" else check()


if __name__ == "__main__":
    main()
