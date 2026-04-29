const moneyFmt = new Intl.NumberFormat("en-SG", {
  style: "currency",
  currency: "SGD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const moneyCompactFmt = new Intl.NumberFormat("en-SG", {
  style: "currency",
  currency: "SGD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const integerFmt = new Intl.NumberFormat("en-SG");

export function formatMoney(n: number): string {
  return moneyFmt.format(n);
}

export function formatMoneyCompact(n: number): string {
  return moneyCompactFmt.format(n);
}

export function formatInt(n: number): string {
  return integerFmt.format(n);
}

export function formatDate(input: Date | string, opts?: Intl.DateTimeFormatOptions): string {
  const d = typeof input === "string" ? new Date(input) : input;
  return d.toLocaleDateString("en-SG", opts ?? { day: "numeric", month: "short", year: "numeric" });
}

export function formatTime(input: Date | string): string {
  const d = typeof input === "string" ? new Date(input) : input;
  return d.toLocaleTimeString("en-SG", { hour: "2-digit", minute: "2-digit" });
}

export function formatTimeFromHMS(t: string): string {
  const [h, m] = t.split(":").map(Number);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return formatTime(d);
}

export function classNames(...args: (string | false | null | undefined)[]): string {
  return args.filter(Boolean).join(" ");
}
