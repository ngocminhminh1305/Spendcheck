"""Standalone FastAPI entry point; models load once during startup."""

from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, Request, HTTPException

from app.catalogue import MerchantCatalogue
from app.hybrid import AmbiguousMerchant, categorise_merchant, load_bundle
from app.model import load_model
from app.schemas import ClassifyRequest, ClassifyResponse, HealthResponse
from app.settings import ROOT


def create_app(model_directory: Path | None = None, bundle_path: Path | None = None) -> FastAPI:
    """Construct an independent service with a replaceable artifact path for tests."""
    @asynccontextmanager
    async def lifespan(service: FastAPI):
        """Validate and cache the model before accepting any requests."""
        if model_directory is not None:
            # Explicit model injection supports isolated tests and offline artifact inspection.
            service.state.pipeline, service.state.metadata = load_model(model_directory)
            service.state.catalogue = MerchantCatalogue([])
        else:
            path = bundle_path or ROOT / "bundles/default/manifest.json"
            model, catalogue, manifest = load_bundle(path)
            service.state.pipeline, service.state.catalogue = model, catalogue
            service.state.metadata = {"model_version": manifest["model_version"],
                                      "data_status": manifest["data_status"]}
        yield

    service = FastAPI(title="Spendcheck Merchant Categoriser", version="1.0", lifespan=lifespan)

    @service.get("/health", response_model=HealthResponse)
    def health(request: Request) -> dict:
        """Confirm that startup validated the model and expose its data status."""
        metadata = request.app.state.metadata
        return {"status": "ready", "model_version": metadata["model_version"],
                "data_status": metadata["data_status"]}

    @service.post("/classify", response_model=ClassifyResponse)
    def classify(body: ClassifyRequest, request: Request) -> dict:
        """Categorise one merchant without recording or forwarding its text."""
        try:
            return categorise_merchant(body.merchant, request.app.state.pipeline,
                                      request.app.state.catalogue, request.app.state.metadata["model_version"])
        except AmbiguousMerchant as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return service


app = create_app(bundle_path=Path(os.environ["CLASSIFIER_BUNDLE"]) if "CLASSIFIER_BUNDLE" in os.environ else None)
