# Data

`raw/` and `results/` are not committed (Berka is ~70 MB).

1. Download the Berka / PKDD'99 financial dataset (search "Berka dataset" on Kaggle).
2. Put `trans.csv` at `data/raw/trans.csv`. It is semicolon-separated with columns
   `trans_id;account_id;date;type;operation;amount;balance;k_symbol;bank;account`.
3. From the `forecaster/` folder run `python -m scripts.evaluate_berka --day 15`.
