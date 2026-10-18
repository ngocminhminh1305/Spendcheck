"""Verify all human-checked labels preserve the frozen dataset."""



from app.settings import ROOT
from scripts.common import read_csv


def test_all_human_checked_without_label_changes():
    """All actual description pairs retain their original text/group/category and order."""
    dataset = read_csv(ROOT / "data/prepared/merchant_dataset.csv")
    reviewed = read_csv(ROOT / "data/prepared/human_labels.csv")
    assert len(reviewed) == 372 and all(r["human_checked"] == "yes" for r in reviewed)
    assert [{key: row[key] for key in dataset[0]} for row in reviewed] == dataset


