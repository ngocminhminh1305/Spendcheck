"""Test our adapter with controlled spans, not spaCy's learned accuracy."""

from types import SimpleNamespace

from app import spacy_extractor


def install_fake_model(monkeypatch, spans):
    def predict(text):
        return SimpleNamespace(ents=[
            SimpleNamespace(text=text[start:end], label_=label, start_char=start, end_char=end)
            for start, end, label in spans
        ])
    monkeypatch.setattr(spacy_extractor, "load_model", lambda: predict)


def test_preserves_source_spans_and_maps_supported_labels(monkeypatch):
    text = "Apple 8 yesterday"
    install_fake_model(monkeypatch, [(0, 5, "ORG"), (6, 7, "MONEY"), (8, 17, "DATE")])
    result = spacy_extractor.extract_spacy_entities(text)
    assert [entity["candidate_field"] for entity in result] == ["merchant", "amount", "date"]
    for entity in result:
        assert text[entity["start"]:entity["end"]] == entity["text"]
        assert entity["source"] == "spacy"
        assert "confidence" not in entity


def test_cardinal_is_not_automatically_an_amount(monkeypatch):
    install_fake_model(monkeypatch, [(0, 1, "CARDINAL")])
    result = spacy_extractor.extract_spacy_entities("2 coffees")
    assert result[0]["candidate_field"] is None


def test_multiple_merchants_remain_separate_candidates(monkeypatch):
    install_fake_model(monkeypatch, [(0, 5, "ORG"), (10, 14, "ORG")])
    result = spacy_extractor.extract_spacy_entities("Apple and IKEA")
    assert [entity["text"] for entity in result] == ["Apple", "IKEA"]


def test_no_entities_returns_empty_list(monkeypatch):
    install_fake_model(monkeypatch, [])
    assert spacy_extractor.extract_spacy_entities("hello") == []
