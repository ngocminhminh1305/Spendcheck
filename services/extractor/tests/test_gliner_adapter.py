"""Adapter tests with controlled predictions; not model-accuracy tests."""

from types import SimpleNamespace

import pytest

from app import gliner_extractor


def test_passes_labels_and_threshold_and_preserves_spans(monkeypatch):
    def predict(text, labels, threshold):
        assert text == "kopitam 8 yesterdat"
        assert labels == ["amount", "merchant", "date"]
        assert threshold == 0.6
        return [{"start": 0, "end": 7, "label": "merchant", "score": 0.8}]

    monkeypatch.setattr(gliner_extractor, "load_model", lambda: SimpleNamespace(predict_entities=predict))
    assert gliner_extractor.extract_gliner_entities("kopitam 8 yesterdat", 0.6) == [{
        "text": "kopitam", "label": "merchant", "candidate_field": "merchant",
        "start": 0, "end": 7, "score": 0.8, "source": "gliner",
    }]


def test_preserves_competing_amounts(monkeypatch):
    model = SimpleNamespace(predict_entities=lambda *args, **kwargs: [
        {"start": 0, "end": 1, "label": "amount", "score": 0.9},
        {"start": 5, "end": 6, "label": "amount", "score": 0.7},
    ])
    monkeypatch.setattr(gliner_extractor, "load_model", lambda: model)
    assert [item["text"] for item in gliner_extractor.extract_gliner_entities("8 or 9")] == ["8", "9"]


def test_empty_input_does_not_load_model(monkeypatch):
    def unexpected_load():
        pytest.fail("Empty text should not require loading the model")
    monkeypatch.setattr(gliner_extractor, "load_model", unexpected_load)
    assert gliner_extractor.extract_gliner_entities("  ") == []


@pytest.mark.parametrize("threshold", [0, 1, -0.1, float("nan")])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValueError, match="threshold"):
        gliner_extractor.extract_gliner_entities("coffee", threshold)


def test_invalid_model_span_is_not_silently_accepted(monkeypatch):
    model = SimpleNamespace(predict_entities=lambda *args, **kwargs: [
        {"start": 0, "end": 99, "label": "merchant", "score": 0.9},
    ])
    monkeypatch.setattr(gliner_extractor, "load_model", lambda: model)
    with pytest.raises(ValueError, match="span"):
        gliner_extractor.extract_gliner_entities("coffee")
