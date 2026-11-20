import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Champion } from '../types/contracts';
import { GameImage } from './GameImage';

type Props = {
  champions: Champion[];
  value: string;
  onChange: (championId: string) => void;
  getIcon: (championId: string) => string | undefined;
  variant?: 'standard' | 'compact';
  placeholder?: string;
  label: string;
  onOpen?: (championIds: string[]) => void;
  disabled?: boolean;
};

const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es').trim();

/** Shared champion picker. The compact form is used by Draft bans; the standard form by Local Analysis. */
export function ChampionSelector({ champions, value, onChange, getIcon, variant = 'standard', placeholder = 'Seleccionar campeón', label, onOpen, disabled = false }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [position, setPosition] = useState<{ left: number; top: number; width: number; maxHeight: number }>();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const champion = champions.find((item) => item.id === value);
  const filtered = useMemo(() => {
    const term = normalize(query);
    return [...champions]
      .sort((a, b) => a.name.localeCompare(b.name, 'es'))
      .filter((item) => !term || normalize(item.name).includes(term) || normalize(item.id).includes(term));
  }, [champions, query]);

  const updatePosition = useCallback(() => {
    const anchor = triggerRef.current;
    const menu = menuRef.current;
    if (!anchor || !menu) return;
    const rect = anchor.getBoundingClientRect();
    const viewportPadding = 8;
    const menuWidth = Math.min(window.innerWidth - viewportPadding * 2, variant === 'compact' ? 230 : Math.max(280, rect.width));
    const left = Math.max(viewportPadding, Math.min(rect.left, window.innerWidth - menuWidth - viewportPadding));
    const measuredHeight = Math.min(menu.scrollHeight, window.innerHeight - viewportPadding * 2);
    const below = Math.max(0, window.innerHeight - rect.bottom - viewportPadding);
    const above = Math.max(0, rect.top - viewportPadding);
    const opensAbove = below < measuredHeight && above > below;
    const available = opensAbove ? above : below;
    const maxHeight = Math.max(80, Math.min(360, available));
    const top = opensAbove ? Math.max(viewportPadding, rect.top - Math.min(measuredHeight, maxHeight) - 5) : Math.min(rect.bottom + 5, window.innerHeight - maxHeight - viewportPadding);
    setPosition({ left, top, width: menuWidth, maxHeight });
  }, [variant]);

  const close = useCallback((restoreFocus = false) => {
    setOpen(false);
    setQuery('');
    setPosition(undefined);
    if (restoreFocus) requestAnimationFrame(() => triggerRef.current?.focus());
  }, []);

  useEffect(() => { if (disabled && open) close(); }, [disabled, open, close]);

  const show = () => {
    if (disabled) return;
    if (open) { close(); return; }
    setQuery('');
    setActiveIndex(Math.max(0, filtered.findIndex((item) => item.id === value)));
    setOpen(true);
    onOpen?.(filtered.slice(0, 18).map((item) => item.id));
  };

  useEffect(() => {
    if (!open) return;
    searchRef.current?.focus();
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close(true); }
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, close]);

  useEffect(() => {
    if (!open || !onOpen) return;
    const timer = window.setTimeout(() => onOpen(filtered.slice(0, 18).map((item) => item.id)), 140);
    return () => window.clearTimeout(timer);
  }, [open, query, filtered, onOpen]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    const reposition = () => updatePosition();
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    return () => {
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
    };
  }, [open, filtered.length, updatePosition]);

  useEffect(() => {
    if (activeIndex >= filtered.length) setActiveIndex(Math.max(0, filtered.length - 1));
  }, [activeIndex, filtered.length]);

  const focusOption = (index: number) => {
    if (!filtered.length) return;
    const next = Math.max(0, Math.min(filtered.length - 1, index));
    setActiveIndex(next);
    menuRef.current?.querySelectorAll<HTMLButtonElement>('[data-champion-option]')[next]?.focus();
  };

  return <div className={`champion-selector ${variant === 'compact' ? 'compact' : 'standard'}`} ref={rootRef}>
    <button ref={triggerRef} type="button" disabled={disabled} className={`champion-selector-trigger ${champion ? 'selected' : ''}`} aria-label={`${label}: ${champion?.name ?? placeholder}`} aria-haspopup="listbox" aria-expanded={open} title={champion?.name ?? placeholder} onClick={show} onKeyDown={(event) => { if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); if (!open) show(); } }}>
      {champion ? <GameImage src={getIcon(champion.id)} alt="" fallback={champion.name.slice(0, 1)} /> : <span className="champion-selector-placeholder">{placeholder}</span>}
      {variant === 'standard' && champion && <span className="champion-selector-name">{champion.name}</span>}
      <i aria-hidden="true">⌄</i>
    </button>
    {open && createPortal(<div ref={menuRef} className={`champion-selector-menu ${variant}`} role="dialog" aria-label={label} style={position ? { left: position.left, top: position.top, width: position.width, maxHeight: position.maxHeight } : { visibility: 'hidden' }}>
      <input ref={searchRef} type="search" value={query} onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }} placeholder="Buscar campeón…" aria-label={`Buscar en ${label}`} onKeyDown={(event) => { if (event.key === 'ArrowDown') { event.preventDefault(); focusOption(0); } else if (event.key === 'ArrowUp') { event.preventDefault(); focusOption(filtered.length - 1); } }} />
      <div className="champion-selector-options" role="listbox" aria-label={label} onScroll={(event) => {
        const node = event.currentTarget;
        const first = Math.max(0, Math.floor(node.scrollTop / 38));
        const count = Math.ceil(node.clientHeight / 38) + 10;
        onOpen?.(filtered.slice(first, first + count).map((item) => item.id));
      }}>
        {filtered.map((item, index) => <button type="button" role="option" aria-selected={item.id === value} data-champion-option key={item.id} className={index === activeIndex ? 'active' : ''} onMouseEnter={() => setActiveIndex(index)} onClick={() => { onOpen?.([item.id]); onChange(item.id); close(true); }} onKeyDown={(event) => { if (event.key === 'ArrowDown') { event.preventDefault(); focusOption(index + 1); } else if (event.key === 'ArrowUp') { event.preventDefault(); if (index === 0) searchRef.current?.focus(); else focusOption(index - 1); } }}>
          <GameImage src={getIcon(item.id)} alt="" fallback={item.name.slice(0, 1)} /><span>{item.name}</span>
        </button>)}
        {!filtered.length && <div className="champion-selector-empty">No se encontraron campeones.</div>}
      </div>
    </div>, document.body)}
  </div>;
}
