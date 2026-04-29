const DEFAULT_AUTH_EMAIL_DOMAIN = "victoriaenso.com";

function authEmailDomain() {
  return import.meta.env.VITE_AUTH_EMAIL_DOMAIN || DEFAULT_AUTH_EMAIL_DOMAIN;
}

export function usernameToAuthEmail(value: string) {
  const identifier = value.trim().toLowerCase();
  if (!identifier || identifier.includes("@")) return identifier;
  return `${identifier}@${authEmailDomain()}`;
}

export function emailToUsername(value: string | null | undefined) {
  if (!value) return "";
  return value.split("@")[0] || value;
}
