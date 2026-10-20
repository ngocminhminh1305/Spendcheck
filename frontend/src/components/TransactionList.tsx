// Recent entries, receipt style: station code, merchant, date, amount, and delete.
// Delete asks "Sure?" inside the row rather than with a browser dialog, which is clumsy on phones.

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { api, type Transaction } from "../api";
import { codeFor, sgd, shortDate } from "../format";

export default function TransactionList({ transactions, onChanged }: { transactions: Transaction[]; onChanged: () => void }) {
  const [confirming, setConfirming] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  if (transactions.length === 0) return <p className="empty">Nothing logged yet. What did you buy today?</p>;

  async function remove(t: Transaction) {
    setBusy(true);
    await api.remove(t.txn_id).catch(() => undefined);
    setBusy(false);
    setConfirming(null);
    onChanged();
  }

  return (
    <ul className="txns">
      {transactions.map((t) => (
        <li key={t.txn_id} className="txn">
          <span className="code" title={t.category}>{codeFor(t.category)}</span>
          <span style={{ minWidth: 0 }}>
            <div className="txn__merchant">{t.merchant}</div>
            <div className="txn__date">{shortDate(t.date)} · {t.category}</div>
          </span>
          <span className="txn__amount">{sgd(t.amount)}</span>
          {confirming === t.txn_id ? (
            <span className="txn__confirm">
              <button className="txn__yes" disabled={busy} onClick={() => remove(t)} aria-label={`Confirm delete ${t.merchant} ${sgd(t.amount)}`}>Delete</button>
              <button className="txn__no" disabled={busy} onClick={() => setConfirming(null)}>Keep</button>
            </span>
          ) : (
            <button className="txn__del" onClick={() => setConfirming(t.txn_id)} aria-label={`Delete ${t.merchant} ${sgd(t.amount)}`}><Trash2 size={16} /></button>
          )}
        </li>
      ))}
    </ul>
  );
}
