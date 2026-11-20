import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Icon } from './Icon';

export function WindowTitleBar({ label, className = 'topbar', children }: { label: string; className?: string; children?: ReactNode }) {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    void window.solralol.getWindowState().then(state => setMaximized(state.maximized)).catch(() => {});
    return window.solralol.onWindowState(state => setMaximized(state.maximized));
  }, []);
  return <header className={className} onDoubleClick={event => {
    if ((event.target as HTMLElement).closest('button,a,input,select,[role="button"]')) return;
    void window.solralol.toggleMaximize();
  }}><div className="topbar-label"><span className="crumb">SOLRALOL</span><span className="slash">/</span><span>{label}</span></div>{children}<div className="window-controls"><button onClick={() => void window.solralol.minimize()} aria-label="Minimizar"><Icon name="minimize" /></button><button onClick={() => void window.solralol.toggleMaximize()} aria-label={maximized ? 'Restaurar' : 'Maximizar'}><Icon name={maximized ? 'restore' : 'maximize'} /></button><button className="close-control" onClick={() => void window.solralol.close()} aria-label="Cerrar"><Icon name="close" /></button></div></header>;
}
