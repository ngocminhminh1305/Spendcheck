// Live module status in the signage band: the five microservices, like line indicators.
// Shows the architecture during the demo, and tells the user why something might not answer.

import type { Status } from "../api";

const MODULES: { key: string; code: string; label: string }[] = [
  { key: "extractor", code: "M1", label: "Reads your entries" },
  { key: "categoriser", code: "M2", label: "Picks categories" },
  { key: "forecaster", code: "M3", label: "Forecasts the month" },
  { key: "chat-agent", code: "M4", label: "Answers your questions" },
  { key: "report-reader", code: "M5", label: "Reads annual reports" },
];

export default function StatusStrip({ status }: { status: Status | null }) {
  return (
    <ul className="modules" aria-label="Module status" style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {MODULES.map((m) => {
        const up = status?.modules[m.key] ?? false;
        return (
          <li key={m.key} className={`module${up ? "" : " module--down"}`} title={`${m.code}: ${m.label} (${up ? "running" : "not responding"})`}>
            <span className="module__dot" aria-hidden />
            {m.code}
            <span className="visually-hidden">{m.label}: {up ? "running" : "not responding"}</span>
          </li>
        );
      })}
    </ul>
  );
}
