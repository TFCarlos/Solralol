import { memo, useEffect, useState } from 'react';

type Props = { src?: string | null; alt: string; className?: string; fallback: string; title?: string; actorType?: string };

export const GameImage = memo(function GameImage({ src, alt, className = 'game-image', fallback, title, actorType }: Props) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  if (!src || failed) return <span className={`${className} image-fallback`} aria-label={alt} title={title} data-actor-type={actorType}>{fallback}</span>;
  return <img className={className} src={src} alt={alt} title={title} data-actor-type={actorType} loading="lazy" decoding="async" onError={() => setFailed(true)} />;
});
