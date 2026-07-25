/**
 * Display formatting.
 *
 * Units are always shown next to the number: a bare figure in this system is
 * ambiguous between metres and degrees.
 */

const NUMBER = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });
const INTEGER = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });

export function formatNumber(value: number, fractionDigits = 2): string {
  return new Intl.NumberFormat("en-GB", { maximumFractionDigits: fractionDigits }).format(value);
}

export function formatArea(km2: number): string {
  return `${NUMBER.format(km2)} km²`;
}

/** Cell size, labelled with the unit the dataset actually declares. */
export function formatResolution(x: number | null, y: number | null, units: string): string {
  if (x === null || y === null) {
    return "unknown";
  }
  const unit = units === "m" ? "m" : units === "degree" ? "°" : units;
  return x === y
    ? `${formatNumber(x, 3)} ${unit}`
    : `${formatNumber(x, 3)} × ${formatNumber(y, 3)} ${unit}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${NUMBER.format(bytes / 1024)} kB`;
  if (bytes < 1024 * 1024 * 1024) return `${NUMBER.format(bytes / (1024 * 1024))} MB`;
  return `${NUMBER.format(bytes / (1024 * 1024 * 1024))} GB`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

export function formatCoordinate(value: number): string {
  return `${formatNumber(value, 5)}°`;
}

export function formatPercent(ratio: number): string {
  return `${INTEGER.format(ratio * 100)}%`;
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}
