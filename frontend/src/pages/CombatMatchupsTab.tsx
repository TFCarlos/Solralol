import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { GameImage } from '../components/GameImage';
import { Icon } from '../components/Icon';
import type { CombatAbility, CombatChampion, CombatContext, CombatMatchup, CombatMatchupsResult } from '../types/contracts';
import './CombatMatchupsTab.css';

type Props = { matchId: string; active: boolean; cachedMatchups: CombatMatchupsResult | null; refreshKey: number };
type Assets = { champions: Record<string, string | null>; abilities: Record<string, string | null> };
const difficulty: Record<CombatMatchup['difficulty'], { label: string; icon: 'trend-down'|'trend-flat'|'trend-up' }> = {
  easy: { label: 'Fácil', icon: 'trend-down' }, medium: { label: 'Media', icon: 'trend-flat' }, hard: { label: 'Difícil', icon: 'trend-up' },
};
const slotLabel: Record<string, string> = { q: 'Q', w: 'W', e: 'E', r: 'R', passive: 'Pasiva' };
const tagLabel: Record<string, string> = { Fighter: 'Luchador', Tank: 'Tanque', Mage: 'Mago', Assassin: 'Asesino', Marksman: 'Tirador', Support: 'Apoyo' };
const roleLabel: Record<string, string> = { TOP: 'Superior', JUNGLE: 'Jungla', MIDDLE: 'Medio', MID: 'Medio', BOTTOM: 'Tirador', UTILITY: 'Apoyo', SUPPORT: 'Apoyo' };
const localizedRole = (value: string) => roleLabel[value.trim().toUpperCase()] || value || 'Rol no disponible';

function abilityBySlot(champion: CombatChampion, slot: string) { return champion.abilities.find(ability => ability.slot === slot); }

function omitAbilityNames(value: string, champions: CombatChampion[]): string {
  let text = value;
  const names = [...new Set(champions.flatMap(champion => champion.abilities.map(ability => ability.name.trim())).filter(name => name.length >= 4))].sort((a, b) => b.length - a.length);
  for (const name of names) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const quotedReference = new RegExp(`\\s*\\(?\\s*["']?\\s*${escaped}\\s*["']?\\s*\\)?`, 'gi');
    text = text.replace(quotedReference, ' ');
  }
  return text.replace(/\s+([,.;:!?])/g, '$1').replace(/\(\s*\)/g, '').replace(/\s{2,}/g, ' ').trim();
}

export function CombatMatchupsTab({ matchId, active, cachedMatchups, refreshKey }: Props) {
  const [context, setContext] = useState<CombatContext | null>(null);
  const [assets, setAssets] = useState<Assets>({ champions: {}, abilities: {} });
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const assetsRequestKey = useRef('');
  const lastReportRefresh = useRef(0);
  const contextRequested = useRef(false);
  const [retryContext, setRetryContext] = useState(0);

  useEffect(() => {
    if (!active || context || loading || contextRequested.current) return;
    contextRequested.current = true;
    setLoading(true);
    window.solralol.request('soloq_analyses.combat.context', { matchId })
      .then(value => setContext(value))
      .catch(cause => setError(cause instanceof Error ? cause.message : 'No se pudo cargar el contexto de campeones.'))
      .finally(() => setLoading(false));
  }, [active, context, loading, matchId, retryContext]);

  useEffect(() => {
    if (!active || !context || refreshKey === 0 || lastReportRefresh.current === refreshKey) return;
    lastReportRefresh.current = refreshKey;
    window.solralol.request('soloq_analyses.combat.context', { matchId })
      .then(value => setContext(value))
      .catch(cause => setError(cause instanceof Error ? cause.message : 'No se pudo actualizar el contexto de combate.'));
  }, [active, context, matchId, refreshKey]);

  useEffect(() => {
    if (!active || context?.generation_status !== 'generating') return;
    let live = true;
    const timer = window.setTimeout(() => {
      window.solralol.request('soloq_analyses.combat.context', { matchId })
        .then(value => { if (live) setContext(value); })
        .catch(cause => { if (live) setError(cause instanceof Error ? cause.message : 'No se pudo consultar el estado del análisis de combate.'); });
    }, 2000);
    return () => { live = false; window.clearTimeout(timer); };
  }, [active, context, matchId]);

  const matchupData = context?.matchups ?? cachedMatchups;
  const abilityRequests = useMemo(() => {
    if (!context?.player || !matchupData) return [];
    const requests = new Set<string>();
    for (const matchup of matchupData.matchups) {
      for (const row of matchup.key_enemy_abilities) requests.add(matchup.enemy_champion_id + '|' + row.slot);
      for (const row of matchup.relevant_player_abilities) requests.add(matchup.player_champion_id + '|' + row.slot);
    }
    return [...requests].map(value => { const [champion, slot] = value.split('|'); return { champion, slot: slot as CombatAbility['slot'] }; });
  }, [context?.player, matchupData]);

  useEffect(() => {
    if (!active || !context?.player || context.enemies.length !== 5) return;
    const requestKey = [context.player.champion_id, ...context.enemies.map(item => item.champion_id), ...abilityRequests.map(item => item.champion + '|' + item.slot)].join(',');
    if (assetsRequestKey.current === requestKey) return;
    assetsRequestKey.current = requestKey;
    const champions = [context.player, ...context.enemies].map(item => item.champion);
    const abilityBatches = Array.from({ length: Math.ceil(abilityRequests.length / 20) }, (_, i) => abilityRequests.slice(i * 20, i * 20 + 20));
    const requests: Array<Promise<Record<string, string | null>>> = [
      window.solralol.request('home.assets', { champions }).then(result => Object.fromEntries(Object.entries(result.champions).map(([key, src]) => ['champion:' + key, src]))),
      ...abilityBatches.map(abilities => window.solralol.request('meta.assets', { abilities })),
    ];
    Promise.all(requests).then(results => {
      if (assetsRequestKey.current !== requestKey) return;
      const joined: Record<string, string | null> = Object.assign({} as Record<string, string | null>, ...results);
      setAssets({
        champions: Object.fromEntries(Object.entries(joined).filter(([key]) => key.startsWith('champion:')).map(([key, src]) => [key.slice(9), src])),
        abilities: Object.fromEntries(Object.entries(joined).filter(([key]) => key.startsWith('ability:'))),
      });
    }).catch(() => undefined);
  }, [active, context?.player, context?.enemies, abilityRequests]);

  const generate = async () => {
    if (starting || !context?.available) return;
    setStarting(true); setError('');
    try { setContext(await window.solralol.request('soloq_analyses.combat.generate', { matchId })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'No se pudieron generar los enfrentamientos.'); }
    finally { setStarting(false); }
  };

  if (!context && loading) return <div className="combat-loading"><span className="combat-spinner"/> Cargando campeones y habilidades locales…</div>;
  if (!context) return <div className="combat-empty"><div><p>{error || 'No se pudo preparar el análisis de enfrentamientos.'}</p>{error && <button className="combat-retry" type="button" onClick={() => { contextRequested.current = false; setError(''); setRetryContext(value => value + 1); }}>Reintentar</button>}</div></div>;
  const player = context.player;
  const matchups = matchupData?.matchups ?? [];
  const needsBaitingRefresh = matchups.some(item => !item.baiting_strategy?.trim());
  const byEnemy = new Map(matchups.map(item => [item.enemy_champion_id, item]));

  return <section className="combat-matchups">
    <header className="combat-heading"><div><h3>Análisis de enfrentamientos</h3><p>Descubre cómo enfrentarte a cada campeón enemigo utilizando las fortalezas de tu campeón.</p></div>
      {context.available && (!matchupData || needsBaitingRefresh) && <button type="button" disabled={starting || context.generation_status === 'generating'} onClick={() => void generate()}><Icon name="sparkles"/>{starting || context.generation_status === 'generating' ? 'Analizando…' : needsBaitingRefresh ? 'Actualizar enfrentamientos' : context.generation_status === 'error' ? 'Reintentar análisis' : 'Generar enfrentamientos'}</button>}
    </header>
    {error && <p className="combat-error" role="alert">{error}</p>}
    {context.status_message && context.generation_status === 'generating' && <p className="combat-progress" role="status"><span className="combat-spinner"/>{context.status_message}</p>}
    {context.status_message && context.generation_status === 'error' && matchupData && <p className="combat-error" role="status">No se pudo actualizar el análisis. Se conserva la versión guardada. {context.status_message}</p>}
    {!context.available && !matchupData && <div className="combat-empty"><Icon name="alert"/><p>{context.reason || 'Faltan datos locales para identificar con certeza a los seis campeones.'}</p></div>}
    {player && matchups.length === 0 && context.available && !context.generation_status?.includes('generating') && <div className="combat-empty"><Icon name="swords"/><p>El análisis de enfrentamientos todavía no se ha generado. Se usan los datos de campeón guardados y el catálogo local de habilidades.</p></div>}
    {matchups.length > 0 && player && <>
      <div className="combat-pairing-summary"><GameImage src={assets.champions[player.champion_id] ?? null} alt={player.champion} className="combat-summary-avatar" fallback={player.champion.slice(0, 1)}/><span>Enfrentamientos de</span><b>{player.champion}</b><small>{[...new Set(player.damage_profile.map(tag => tagLabel[tag] || tag))].join(' · ')}{player.role ? ' · ' + localizedRole(player.role) : ''}</small></div>
      <div className="combat-matchup-grid">{context.enemies.map(enemy => {
        const matchup = byEnemy.get(enemy.champion_id);
        if (!matchup) return null;
        return <MatchupCard key={enemy.champion_id} player={player} enemy={enemy} matchup={matchup} assets={assets}/>;
      })}</div>
      {(context.patch && context.enemies.some(enemy => !enemy.ability_data_matches_game_patch) || !player.ability_data_matches_game_patch) && <p className="combat-patch-note">El catálogo local de algunas habilidades es de una versión distinta a la partida. Las recomendaciones describen esas mecánicas con esa limitación.</p>}
    </>}
    {context.generation_status === 'error' && !matchupData && <p className="combat-error" role="alert">{context.status_message || 'No se pudo completar el análisis. Puedes volver a intentarlo.'}</p>}
  </section>;
}

function MatchupCard({ player, enemy, matchup, assets }: { player: CombatChampion; enemy: CombatChampion; matchup: CombatMatchup; assets: Assets }) {
  const diff = difficulty[matchup.difficulty];
  const matchupText = (text: string) => omitAbilityNames(text, [player, enemy]);
  const enemyAbilities = matchup.key_enemy_abilities.flatMap(item => { const ability = abilityBySlot(enemy, item.slot); return ability ? [{ ability, reason: matchupText(item.reason) }] : []; });
  const playerAbilities = matchup.relevant_player_abilities.flatMap(item => { const ability = abilityBySlot(player, item.slot); return ability ? [{ ability, use: matchupText(item.use) }] : []; });
  const observation = enemy.match_observation;
  return <article className="combat-matchup-card">
    <div className="combat-versus"><div className="combat-champion"><GameImage src={assets.champions[enemy.champion_id] ?? null} alt={enemy.champion} className="combat-champion-avatar" fallback={enemy.champion.slice(0, 1)}/><b>{enemy.champion}</b><small>{localizedRole(enemy.role)}</small></div><span className="combat-versus-mark">VS</span><div className="combat-champion"><GameImage src={assets.champions[player.champion_id] ?? null} alt={player.champion} className="combat-champion-avatar" fallback={player.champion.slice(0, 1)}/><b>{player.champion}</b><small>Tu campeón</small></div></div>
    <div className={'combat-difficulty ' + matchup.difficulty}><Icon name={diff.icon}/><b>Dificultad {diff.label.toLocaleLowerCase('es')}</b><span>{matchupText(matchup.difficulty_reason)}</span></div>
    <section className="combat-subsection"><h4>Principales amenazas</h4><div className="combat-ability-list">{enemyAbilities.map(item => <AbilityToken key={item.ability.slot} champion={enemy} ability={item.ability} detail={item.reason} assets={assets}/>)}</div></section>
    <section className="combat-subsection"><h4>Cómo enfrentarte a {enemy.champion}</h4><p>{matchupText(matchup.combat_strategy)}</p></section>
    {matchup.baiting_strategy && <section className="combat-baiting"><b>Cómo baitear</b><p>{matchupText(matchup.baiting_strategy)}</p>{playerAbilities.length > 0 && <div className="combat-player-abilities">{playerAbilities.map(item => <AbilityToken key={item.ability.slot} champion={player} ability={item.ability} detail={item.use} assets={assets}/>)}</div>}</section>}
    {matchup.counterplay_windows && <section className="combat-opportunity"><b>Ventana de oportunidad</b><p>{matchupText(matchup.counterplay_windows)}</p>{playerAbilities.length > 0 && <div className="combat-player-abilities">{playerAbilities.map(item => <AbilityToken key={item.ability.slot} champion={player} ability={item.ability} detail={item.use} assets={assets}/>)}</div>}</section>}
    <section className="combat-tip"><Icon name="target"/><div><b>Consejo estratégico</b><p>{matchupText(matchup.strategic_tip)}</p></div></section>
    <details className="combat-details"><summary>Más detalles <Icon name="chevron"/></summary><div>
      {observation && observation.count > 0 && <section className="combat-match-fact"><b>Hecho de esta partida</b><p>{enemy.champion} eliminó a {player.champion} {observation.count} {observation.count === 1 ? 'vez' : 'veces'}{observation.timestamps.length ? ' (' + observation.timestamps.join(', ') + ')' : ''}</p></section>}
      {matchup.match_specific_observations && <section className="combat-match-fact"><b>Observación del informe</b><p>{matchupText(matchup.match_specific_observations)}</p></section>}
      {playerAbilities.length > 0 && <section className="combat-subsection"><h4>Habilidades de {player.champion} que pueden responder</h4><div className="combat-ability-list">{playerAbilities.map(item => <AbilityToken key={item.ability.slot} champion={player} ability={item.ability} detail={item.use} assets={assets}/>)}</div></section>}
      {matchup.mistakes_to_avoid.length > 0 && <section className="combat-subsection"><h4>Errores a evitar</h4><ul>{matchup.mistakes_to_avoid.map((item, i) => <li key={i}>{matchupText(item)}</li>)}</ul></section>}
      {matchup.target_priority && <section className="combat-subsection"><h4>Prioridad de objetivo</h4><p>{matchupText(matchup.target_priority)}</p></section>}
      {matchup.teamfight_considerations && <section className="combat-subsection"><h4>En peleas de equipo</h4><p>{matchupText(matchup.teamfight_considerations)}</p></section>}
    </div></details>
  </article>;
}

function AbilityToken({ champion, ability, detail, assets }: { champion: CombatChampion; ability: CombatAbility; detail: string; assets: Assets }) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; above: boolean } | null>(null);
  const cooldown = ability.cooldown_by_rank.length ? ability.cooldown_by_rank.map(value => value + ' s').join(' / ') : '';
  const show = (target: HTMLElement) => {
    const rect = target.getBoundingClientRect();
    const width = Math.min(350, window.innerWidth - 24);
    const left = Math.max(12, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 12));
    const above = rect.bottom + 230 > window.innerHeight;
    const y = above ? Math.max(12, rect.top - 12) : Math.min(window.innerHeight - 12, rect.bottom + 10);
    setTooltip({ x: left, y, above });
  };
  const tooltipNode = tooltip && createPortal(<div className={'combat-ability-tooltip ' + (tooltip.above ? 'above' : '')} style={{ left: tooltip.x, top: tooltip.y }} role="tooltip"><strong>{champion.champion} · {slotLabel[ability.slot] || ability.slot.toUpperCase()} — {ability.name}</strong><p>{ability.description || 'Descripción no disponible en el catálogo local.'}</p>{detail && <p className="combat-ability-relevance"><b>Interacción:</b> {detail}</p>}{cooldown && <small>Enfriamiento por rango · {cooldown}</small>}{!champion.ability_data_matches_game_patch && <small>Los datos locales no corresponden al parche de esta partida.</small>}</div>, document.body);
  return <span className="combat-ability-wrap" onMouseEnter={event => show(event.currentTarget)} onMouseLeave={() => setTooltip(null)} onFocus={event => show(event.currentTarget)} onBlur={() => setTooltip(null)}>
    <button className="combat-ability-token" type="button" aria-label={champion.champion + ' ' + (slotLabel[ability.slot] || ability.slot) + ': ' + ability.name}>
      <GameImage src={assets.abilities['ability:' + champion.champion_id + '|' + ability.slot] ?? null} alt="" className="combat-ability-icon" fallback={(slotLabel[ability.slot] || '?').slice(0, 1)}/><span>{slotLabel[ability.slot] || ability.slot.toUpperCase()}</span>
    </button>{tooltipNode}
  </span>;
}
