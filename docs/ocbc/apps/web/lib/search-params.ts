export type PageSearchParams = Record<string, string | string[] | undefined>;

export function readParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}