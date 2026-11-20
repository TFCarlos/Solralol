export function battleScoreColor(value: number | null | undefined): string {
  if (value == null) return '#918979';
  if (value < 4) return '#df7b70';
  if (value < 6) return '#c7bda8';
  if (value < 8) return '#77c99b';
  return '#dfc16c';
}

export function formatBattleScore(value: number | null | undefined): string {
  return value == null ? 'BS —' : `BS ${value.toLocaleString('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`;
}
