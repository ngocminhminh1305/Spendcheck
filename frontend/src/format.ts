// Formatting and the category "station codes" used across the site.

const cents = new Intl.NumberFormat("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const whole = new Intl.NumberFormat("en-SG", { maximumFractionDigits: 0 });

// The en-SG locale prints SGD as a bare "$"; Spendcheck always says S$ so it is unambiguous.
/** S$1,156.21 */
export const sgd = (n: number) => `${n < 0 ? "−" : ""}S$${cents.format(Math.abs(n))}`;
/** S$1,156 */
export const sgdWhole = (n: number) => `${n < 0 ? "−" : ""}S$${whole.format(Math.abs(n))}`;

/** "18 Oct" (dates arrive as YYYY-MM-DD and are shown in Singapore's calendar). */
export function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-SG", { day: "numeric", month: "short" });
}

export function monthName(yyyyMm: string): string {
  const [y, m] = yyyyMm.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-SG", { month: "long", year: "numeric" });
}

/** Two-letter codes, like MRT station codes: identity by text, not by ten different colours. */
export const CATEGORY_CODES: Record<string, string> = {
  "Food & Drink": "FD",
  Groceries: "GR",
  Transport: "TR",
  Shopping: "SH",
  Entertainment: "EN",
  "Bills & Utilities": "BU",
  Health: "HE",
  Education: "ED",
  Travel: "TV",
  Other: "OT",
};

export const codeFor = (category: string | null) => (category ? CATEGORY_CODES[category] ?? "··" : "??");
