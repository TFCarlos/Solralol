import type { ReactNode, SVGProps } from 'react';

export type IconName = 'home' | 'chart' | 'draft' | 'live' | 'history' | 'video' | 'meta' | 'settings' | 'minimize' | 'maximize' | 'restore' | 'close' | 'refresh' | 'search' | 'external-link' | 'chevron' | 'panel-close' | 'panel-open' | 'trend-up' | 'trend-down' | 'trend-flat' | 'sparkles' | 'shield' | 'alert' | 'target' | 'swords' | 'clock' | 'eye' | 'dragon' | 'baron' | 'herald' | 'voidgrub' | 'turret' | 'check';

const paths: Record<IconName, ReactNode> = {
  home: <><path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9M9 20v-6h6v6"/></>,
  chart: <><path d="M4 19V5M4 19h17"/><path d="m7 15 4-4 3 2 6-7"/></>,
  draft: <><path d="m14 7 3-3 3 3-3 3"/><path d="m5 19 9-9M4 7l3-3 4 4-3 3zM14 17l3-3 4 4-3 3z"/></>,
  live: <><path d="M3 12h4l3-8 4 16 3-8h4"/><circle cx="12" cy="12" r="10"/></>,
  history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/></>,
  video: <><rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3"/></>,
  meta: <><path d="M4 19V5M4 19h17"/><path d="M8 15V9m4 6V5m4 10v-4m4 4V7"/></>,
  settings: <><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2" fill="currentColor"/><circle cx="15" cy="12" r="2" fill="currentColor"/><circle cx="8" cy="18" r="2" fill="currentColor"/></>,
  minimize: <path d="M5 12h14"/>,
  maximize: <rect x="5" y="5" width="14" height="14" rx="1"/>,
  restore: <><path d="M8 8V4h12v12h-4"/><rect x="4" y="8" width="12" height="12" rx="1"/></>,
  close: <><path d="m6 6 12 12M18 6 6 18"/></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.6 9a7 7 0 0 1 11.6-2L20 12M4 12l2.8 5a7 7 0 0 0 11.6-2"/></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  'external-link': <><path d="M14 4h6v6"/><path d="m20 4-9 9"/><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6"/></>,
  chevron: <path d="m8 10 4 4 4-4"/>,
  'panel-close': <><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18m9-12-3 3 3 3"/></>,
  'panel-open': <><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18m6-12 3 3-3 3"/></>,
  'trend-up': <><path d="m3 17 6-6 4 4 8-9"/><path d="M15 6h6v6"/></>,
  'trend-down': <><path d="m3 7 6 6 4-4 8 9"/><path d="M15 18h6v-6"/></>,
  'trend-flat': <><path d="M3 12h18"/><path d="m17 8 4 4-4 4"/></>,
  sparkles: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></>,
  shield: <><path d="M12 3 20 6v5c0 5-3.4 8.2-8 10-4.6-1.8-8-5-8-10V6z"/><path d="m8.5 12 2.2 2.2 4.8-5"/></>,
  alert: <><path d="M12 3 22 20H2z"/><path d="M12 9v4m0 3h.01"/></>,
  target: <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></>,
  swords: <><path d="m4 4 8 8m-5-9 4 4-3 3-4-4zM20 4l-8 8m5-9-4 4 3 3 4-4zM5 14l5 5m-7 1 4-4 3 3-4 4zM19 14l-5 5m7 1-4-4-3 3 4 4z"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  eye: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/></>,
  dragon: <><path d="M4 17c2-4 4-5 7-5l3-4 1 4 5 2-4 2-1 4-3-3H8l-2 2z"/><path d="m5 8 3 2m-5 1 3 1"/></>,
  baron: <><path d="M5 20h14M7 20V8l5-4 5 4v12"/><path d="M9 10h6m-6 4h6m-6 3h6"/></>,
  herald: <><path d="M4 19c4-1 5-6 5-10l3-4 3 4c0 4 1 9 5 10"/><path d="M9 13h6m-5 3h4"/></>,
  voidgrub: <><path d="M5 17c0-5 3-9 7-9s7 4 7 9l-3 3H8zM7 10 4 6m5 2-1-5m9 7 3-4m-5 2 1-5"/><path d="M9 14h.01M15 14h.01M10 17c1 .8 3 .8 4 0"/></>,
  turret: <><path d="M5 20h14M7 20l1-8h8l1 8M6 9l6-5 6 5-2 3H8z"/><path d="M12 4v5"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
};

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" focusable="false" {...props}>{paths[name]}</svg>;
}
