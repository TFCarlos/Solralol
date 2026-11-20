export type RiotReadiness = 'checking' | 'ready' | 'missing' | 'invalid' | 'forbidden' | 'rate_limited' | 'unavailable';

const readinessLabels: Record<RiotReadiness, string> = {
  checking: 'Comprobando conexión con Riot',
  ready: 'API de Riot disponible',
  missing: 'API de Riot no configurada',
  invalid: 'Credenciales de Riot no válidas',
  forbidden: 'Acceso a Riot denegado',
  rate_limited: 'Límite de solicitudes alcanzado',
  unavailable: 'API de Riot no disponible',
};

export function riotReadinessLabel(state: RiotReadiness): string { return readinessLabels[state]; }

export function riotAnalysisActionLabel(readiness: RiotReadiness, state = '', available = false, eligible = true, unavailableReason = 'No se puede analizar esta partida'): string {
  if (available) return 'Abrir análisis';
  if (['pending', 'downloading'].includes(state)) return 'Descargando datos';
  if (state === 'processing') return 'Procesando datos';
  if (readiness === 'missing') return 'Configurar API de Riot';
  if (readiness === 'invalid' || readiness === 'forbidden') return 'Revisar API de Riot';
  if (readiness === 'checking') return readinessLabels.checking;
  if (readiness === 'unavailable' || readiness === 'rate_limited') return 'Reintentar';
  if (state === 'error') return 'Reintentar';
  if (!eligible) return unavailableReason;
  return 'Analizar';
}

export function riotAnalysisStatusLabel(readiness: RiotReadiness, state: string, available = false, message = '', eligible = true, unavailableReason = 'No se puede analizar esta partida'): string {
  if (available) return 'Análisis disponible';
  if (['pending', 'downloading'].includes(state)) return 'Descargando datos';
  if (state === 'processing') return 'Procesando datos';
  if (readiness !== 'ready') return readinessLabels[readiness];
  const text = message.toLocaleLowerCase('es');
  if (text.includes('credenciales') || text.includes('clave de riot no v')) return readinessLabels.invalid;
  if (text.includes('acceso a riot denegado') || text.includes('permisos para esta operaci')) return readinessLabels.forbidden;
  if (text.includes('límite de solicitudes') || text.includes('limitado temporalmente')) return readinessLabels.rate_limited;
  if (text.includes('conectar con riot') || text.includes('api de riot no disponible')) return readinessLabels.unavailable;
  if (state === 'error') return 'Error de análisis';
  if (state === 'partial') return 'Datos parciales';
  return eligible ? 'Listo para analizar' : unavailableReason;
}
