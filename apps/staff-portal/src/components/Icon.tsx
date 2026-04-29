type IconName =
  | "alert"
  | "archive"
  | "bar-chart"
  | "calendar"
  | "check"
  | "chevron-left"
  | "chevron-right"
  | "clock"
  | "database"
  | "document"
  | "fingerprint"
  | "home"
  | "inventory"
  | "lock"
  | "log-out"
  | "menu"
  | "package"
  | "receipt"
  | "search"
  | "shield"
  | "spark"
  | "user"
  | "users"
  | "wallet"
  | "x"
  | "x-mark"
  | "calendar-days"
  | "check-circle"
  | "document-text"
  | "plus";

const paths: Record<IconName, string[]> = {
  alert: ["M12 9v4", "M12 17h.01", "M10.3 3.7 2.4 17.2A2 2 0 0 0 4.1 20h15.8a2 2 0 0 0 1.7-2.8L13.7 3.7a2 2 0 0 0-3.4 0Z"],
  archive: ["M3 7h18", "M5 7v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7", "M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2", "M10 12h4"],
  "bar-chart": ["M4 19V5", "M4 19h16", "M8 16v-5", "M12 16V8", "M16 16v-8"],
  calendar: ["M7 3v4", "M17 3v4", "M4 9h16", "M5 5h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z"],
  check: ["M20 6 9 17l-5-5"],
  "chevron-left": ["M15 18 9 12l6-6"],
  "chevron-right": ["M9 18l6-6-6-6"],
  clock: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z", "M12 7v5l3 2"],
  database: ["M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Z", "M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6", "M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"],
  document: ["M7 3h7l5 5v13H7V3Z", "M14 3v6h5", "M9 13h6", "M9 17h6"],
  fingerprint: ["M7 12a5 5 0 0 1 10 0", "M4 11a8 8 0 0 1 16 0", "M9 16a3 3 0 0 1 6 0", "M12 19v-3"],
  home: ["M3 11 12 3l9 8", "M5 10v10h5v-6h4v6h5V10"],
  inventory: ["M4 7 12 3l8 4-8 4-8-4Z", "M4 7v10l8 4 8-4V7", "M12 11v10"],
  lock: ["M7 10V7a5 5 0 0 1 10 0v3", "M6 10h12v10H6V10Z"],
  "log-out": ["M10 17l5-5-5-5", "M15 12H3", "M21 4v16"],
  menu: ["M4 7h16", "M4 12h16", "M4 17h16"],
  package: ["M4 8 12 4l8 4-8 4-8-4Z", "M4 8v8l8 4 8-4V8", "M12 12v8"],
  receipt: ["M6 3h12v18l-3-2-3 2-3-2-3 2V3Z", "M9 8h6", "M9 12h6", "M9 16h4"],
  search: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z", "M20 20l-4-4"],
  shield: ["M12 3 19 6v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3Z"],
  spark: ["M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z", "M19 3v4", "M21 5h-4"],
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M4 21a8 8 0 0 1 16 0"],
  users: ["M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M3 21a6 6 0 0 1 12 0", "M17 11a3 3 0 1 0 0-6", "M21 21a5 5 0 0 0-5-5"],
  wallet: ["M4 7h15a1 1 0 0 1 1 1v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h12", "M16 13h.01"],
  x: ["M18 6 6 18", "M6 6l12 12"],
  "x-mark": ["M18 6 6 18", "M6 6l12 12"],
  "calendar-days": ["M7 3v4", "M17 3v4", "M4 9h16", "M5 5h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z"],
  "check-circle": ["M22 11.08V12a10 10 0 1 1-5.93-9.14", "M22 4L12 14.01l-3-3"],
  "document-text": ["M7 3h7l5 5v13H7V3Z", "M14 3v6h5", "M9 13h6", "M9 17h6"],
  plus: ["M12 5v14", "M5 12h14"],
};

export function Icon({ name, className = "h-4 w-4" }: { name: IconName; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {paths[name].map((path) => (
        <path key={path} d={path} />
      ))}
    </svg>
  );
}

export type { IconName };
