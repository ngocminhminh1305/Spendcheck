"""Inspect a separately stored model and classify supplied merchant strings offline."""

import argparse
from pathlib import Path
import json
from app.catalogue import MerchantCatalogue
from app.hybrid import categorise_merchant, load_bundle
from app.model import load_model
from app.settings import ROOT


def main() -> None:
    """Load once and print the selected model's public response for each input."""
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--model-dir', type=Path)
    inputs.add_argument('--bundle', type=Path)
    parser.add_argument('merchants', nargs='+')
    args = parser.parse_args()
    if args.model_dir:
        model, metadata = load_model(args.model_dir)
        catalogue = MerchantCatalogue([])
    else:
        model, catalogue, metadata = load_bundle(args.bundle or ROOT / 'bundles/default/manifest.json')
    for text in args.merchants:
        result = categorise_merchant(text, model, catalogue, metadata['model_version'])
        print(json.dumps({'merchant': text, **result}, ensure_ascii=False))


if __name__ == '__main__':
    main()
