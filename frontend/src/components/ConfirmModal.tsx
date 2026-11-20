import { useEffect, useMemo, useRef } from 'react';
import { GameImage } from './GameImage';
import type { DeletionManifest } from '../types/contracts';
import './ConfirmModal.css';

type DeletionResource = DeletionManifest['resources'][number];
type Props = {
  title: string; description: string; manifest?: DeletionManifest; championImage?: string | null;
  loading?: boolean; busy?: boolean; error?: string; onRetry?: () => void;
  onCancel: () => void; onConfirm: () => void;
};

const categoryNames: Record<string, string> = { grabacion: 'Grabaciones', riot: 'Datos de Riot almacenados localmente', ia: 'Análisis con IA', partida: 'Partida guardada', historial: 'Registros locales', conservado: 'Se conservará' };
const dateLabel = (value: string) => { const date = new Date(value); return Number.isNaN(date.valueOf()) ? 'Fecha no disponible' : new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' }).format(date); };
const bytesLabel = (bytes: number) => {
  if (!Number.isFinite(bytes) || bytes < 0) return 'Tamaño desconocido';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024, unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
  return `${new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 }).format(value)} ${units[unit]}`;
};
const fileBadge = (resource: DeletionResource) => resource.kind === 'record' ? 'DATO' : resource.name.toLowerCase().endsWith('.mp4') ? 'MP4' : /\.(jpe?g|webp|png)$/i.test(resource.name) ? 'IMG' : resource.name.toLowerCase().endsWith('.log') ? 'LOG' : resource.name.toLowerCase().endsWith('.json') ? 'JSON' : 'ARCH';

export function ConfirmModal({ title, description, manifest, championImage, loading = false, busy = false, error, onRetry, onCancel, onConfirm }: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const groups = useMemo(() => {
    const result = new Map<string, DeletionResource[]>();
    for (const resource of manifest?.resources ?? []) result.set(resource.category, [...(result.get(resource.category) ?? []), resource]);
    return [...result.entries()];
  }, [manifest?.resources]);
  useEffect(() => {
    cancelRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) { event.preventDefault(); onCancel(); }
      if (event.key === 'Enter') event.preventDefault();
      if (event.key === 'Tab' && dialogRef.current) {
        const controls = [...dialogRef.current.querySelectorAll<HTMLElement>('button:not(:disabled)')];
        if (!controls.length) return;
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [busy, onCancel]);
  return <div className="solralol-modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
    <div className="solralol-confirm-modal deletion-modal" role="alertdialog" aria-modal="true" aria-labelledby="solralol-confirm-title" aria-describedby="solralol-confirm-description" ref={dialogRef}>
      <span className="eyebrow">CONFIRMACIÓN</span>
      <h2 id="solralol-confirm-title">{title}</h2>
      <p id="solralol-confirm-description">{description}</p>
      {manifest && <div className="deletion-match"><GameImage src={championImage ?? null} alt={manifest.champion} className="deletion-champion" fallback={manifest.champion.slice(0, 1)} /><div><b>{manifest.champion}</b><span>{manifest.startedAt ? dateLabel(manifest.startedAt) : 'Fecha no disponible'}</span></div></div>}
      {loading && <div className="deletion-loading" role="status">Calculando archivos asociados...</div>}
      {manifest && !loading && <div className="deletion-inventory-wrap"><h3>ARCHIVOS Y DATOS QUE SE ELIMINARÁN</h3><div className="deletion-inventory">
        {groups.length === 0 && <div className="deletion-empty">No hay archivos locales adicionales asociados.</div>}
        {groups.map(([category, resources]) => <section className="deletion-group" key={category}><h4>{categoryNames[category] ?? category}</h4>{resources.map(resource => <div className="deletion-resource" key={resource.id} title={`${resource.name}${resource.detail ? ` · ${resource.detail}` : ''}`}><span className="deletion-file-badge">{fileBadge(resource)}</span><span className="deletion-resource-copy"><b>{resource.name}</b><small>{resource.type}{resource.detail ? ` · ${resource.detail}` : ''}</small></span><span className="deletion-resource-size">{resource.kind === 'file' ? bytesLabel(resource.size ?? NaN) : resource.size == null ? 'Registro local' : `≈ ${bytesLabel(resource.size)}`}</span></div>)}</section>)}
      </div><div className="deletion-summary"><b>{manifest.summary.files} {manifest.summary.files === 1 ? 'archivo' : 'archivos'} · {manifest.summary.records} {manifest.summary.records === 1 ? 'registro' : 'registros'}</b><span>{manifest.summary.bytes == null ? 'Estimación no disponible' : `${bytesLabel(manifest.summary.bytes)} estimados`}</span></div>
      <details className="deletion-preserved"><summary>Datos que se conservarán</summary>{manifest.preserved.map(item => <div key={item.name}><b>{item.name}</b><span>{item.detail}</span></div>)}</details></div>}
      {error && <div className="solralol-confirm-error" role="alert">{error}{onRetry && <button type="button" onClick={onRetry} disabled={busy}>Actualizar vista previa</button>}</div>}
      <div className="solralol-confirm-actions"><button ref={cancelRef} type="button" className="secondary-button" disabled={busy} onClick={onCancel}>Cancelar</button><button type="button" className="solralol-confirm-danger" disabled={busy || loading || !manifest} onClick={onConfirm}>{busy ? 'Eliminando...' : 'Eliminar definitivamente'}</button></div>
    </div>
  </div>;
}
