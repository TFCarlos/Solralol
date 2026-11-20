import { useEffect, useMemo, useRef, useState } from 'react';
import { Icon as AppIcon, type IconName } from '../components/Icon';
import { CombatMatchupsTab } from './CombatMatchupsTab';
import type { CombatMatchupsResult } from '../types/contracts';
import './AiMatchReport.css';

type Data = Record<string, unknown>;
type ReportEvent = { title: string; time: string; description: string; importanceReason: string; tone: string; icon: IconName; secondaryIcon?: IconName; evidenceRefs: string[]; source?: string; relevance?: string; eventKind?: string; playerContribution?: string; recommendation?: string };

const isData = (value: unknown): value is Data => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const text = (value: unknown): string => typeof value === 'string' ? value.trim() : '';
const numericRuneId = (value: unknown): string => typeof value === 'number' && Number.isInteger(value) && value > 0 ? String(value) : typeof value === 'string' && /^\d{1,10}$/.test(value) && Number(value) > 0 ? value : '';
const texts = (value: unknown): string[] => Array.isArray(value) ? [...new Set(value.map(text).filter(Boolean))] : text(value) ? [text(value)] : [];
const first = (...values: unknown[]) => values.map(text).find(Boolean) ?? '';
const norm = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es');
const isRawPhaseEventDump = (value: string) => (value.match(/\b\d{1,2}:\d{2}\b/g)?.length ?? 0) >= 3 && /\b(?:muertes?|bajas?)\s+propias?\b|objetivos?\s+(?:neutrales|estructuras)\s+clave/i.test(value);
const dedupe = (items: string[]) => {
  const seen = new Set<string>();
  return items.filter(item => { const key = norm(item); if (!key || seen.has(key)) return false; seen.add(key); return true; });
};
const phaseLabels: Record<string, string> = { early: 'Juego temprano', mid: 'Juego medio', late: 'Juego tardío' };
const categories: Array<{ key: string; label: string; icon: IconName }> = [
  { key: 'farming', label: 'Farmeo', icon: 'chart' }, { key: 'itemization', label: 'Objetos y equipamiento', icon: 'swords' },
  { key: 'purchase_timing', label: 'Momento de compra', icon: 'clock' }, { key: 'objective_conversion', label: 'Aprovechamiento de objetivos', icon: 'target' },
  { key: 'objectives', label: 'Control de objetivos', icon: 'dragon' }, { key: 'vision', label: 'Visión', icon: 'eye' },
  { key: 'combat', label: 'Combates y posicionamiento', icon: 'swords' }, { key: 'death_impact', label: 'Impacto de las muertes', icon: 'shield' },
  { key: 'survivability', label: 'Supervivencia', icon: 'shield' }, { key: 'decision_making', label: 'Toma de decisiones', icon: 'target' },
];

function Icon({ name }: { name: IconName }) { return <span className="ai-report-icon"><AppIcon name={name}/></span>; }
function TimelineEvent({ event, richText }: { event: ReportEvent; richText?: (value: string) => React.ReactNode }) {
  return <article className={'ai-report-event ' + event.tone}>
    <span className={'ai-report-event-icon ' + (event.secondaryIcon ? 'with-secondary' : '')}><Icon name={event.icon}/>{event.secondaryIcon && <Icon name={event.secondaryIcon}/>}</span>
    <div className="ai-report-event-copy">
      <div className="ai-report-event-heading"><h4>{event.time && <time>{event.time} — </time>}{event.title}</h4>
        <span>{event.source === 'deterministic_fallback' ? 'Hechos detectados' : event.source === 'factual_timeline' ? 'Registro de partida' : 'Análisis estratégico'}</span>
        {event.relevance && <small className={'event-relevance ' + event.relevance}>Importancia {event.relevance === 'high' ? 'alta' : event.relevance === 'medium' ? 'media' : 'baja'}</small>}
      </div>
      {event.description && <p>{richText ? richText(event.description) : event.description}</p>}
      {event.playerContribution && <p className="ai-report-event-player"><b>Tu participación</b>{richText ? richText(event.playerContribution) : event.playerContribution}</p>}
      {event.importanceReason && <p className="ai-report-event-impact"><b>Por qué importó</b>{richText ? richText(event.importanceReason) : event.importanceReason}</p>}
      {event.recommendation && <p className="ai-report-event-recommendation"><b>Consejo para la próxima partida</b>{richText ? richText(event.recommendation) : event.recommendation}</p>}
    </div>
  </article>;
}
function Bullets({ items, tone = '', richText }: { items: string[]; tone?: string; richText?: (value: string) => React.ReactNode }) {
  if (!items.length) return null;
  return <ul className={`ai-report-list ${tone}`}>{items.map((item, i) => <li key={`${item}-${i}`}>{richText ? richText(item) : item}</li>)}</ul>;
}
function Expandable({ title = 'Ver detalles', children }: { title?: string; children: React.ReactNode }) {
  return <details className="ai-report-expand"><summary>{title}<span aria-hidden="true">⌄</span></summary><div>{children}</div></details>;
}
function ChronologyPanel({ id, active, children }: { id: ChronologyTab; active: boolean; children: React.ReactNode }) {
  return <div id={'ai-chronology-panel-' + id} className="ai-report-chronology-panel" role="tabpanel" aria-labelledby={'ai-chronology-tab-' + id} hidden={!active}>{children}</div>;
}
function EventList({ title, events, emptyMessage, showAll = true, onShowAll, richText }: { title: string; events: ReportEvent[]; emptyMessage: string; showAll?: boolean; onShowAll?: () => void; richText?: (value: string) => React.ReactNode }) {
  const visible = showAll ? events : events.slice(0, 20);
  return <section className="ai-report-section"><h3 className="ai-report-section-title">{title}</h3>{events.length ? <><div className="ai-report-timeline">{visible.map((event, i) => <TimelineEvent key={`${event.time}-${event.title}-${i}`} event={event} richText={richText}/>)}</div>{events.length > 20 && onShowAll && <button className="ai-report-more" type="button" onClick={onShowAll}>{showAll ? 'Mostrar menos' : `Ver ${events.length - 20} momentos adicionales`}</button>}</> : <p className="ai-report-tab-empty">{emptyMessage}</p>}</section>;
}

type ReportTab = 'summary'|'performance'|'chronology'|'combat'|'plan';
const reportTabs: Array<{ id: ReportTab; label: string; icon: IconName }> = [
  { id: 'summary', label: 'Resumen', icon: 'chart' }, { id: 'performance', label: 'Rendimiento', icon: 'trend-up' },
  { id: 'chronology', label: 'Cronología', icon: 'clock' }, { id: 'combat', label: 'Combate', icon: 'swords' }, { id: 'plan', label: 'Plan de mejora', icon: 'target' },
];
type ChronologyTab = 'all'|'combat'|'objectives'|'rewards';
const chronologyTabs: Array<{ id: ChronologyTab; label: string; icon: IconName }> = [
  { id: 'all', label: 'Todos', icon: 'clock' }, { id: 'combat', label: 'Combates', icon: 'swords' },
  { id: 'objectives', label: 'Objetivos', icon: 'target' }, { id: 'rewards', label: 'Recompensas', icon: 'sparkles' },
];

export function AiMatchReport({ value, busy, error, onGenerate, matchId, cachedMatchups, timelineIndex = null, itemAssets = {} }: { value: Data | null; busy: boolean; error: string; onGenerate: () => void; matchId: string; cachedMatchups: CombatMatchupsResult | null; timelineIndex?: Data | null; itemAssets?: Record<string, string | null> }) {
  const report = useMemo(() => transform(value, timelineIndex), [value, timelineIndex]);
  const itemCatalog = useMemo(() => reportItemCatalog(value), [value]);
  const richText = useMemo(() => (content: string) => renderItemReferences(content, itemCatalog, itemAssets), [itemCatalog, itemAssets]);
  const [showAllStrengths, setShowAllStrengths] = useState(false);
  const [showAllWeaknesses, setShowAllWeaknesses] = useState(false);
  const [showAllEvents, setShowAllEvents] = useState(false);
  const [activeTab, setActiveTab] = useState<ReportTab>('summary');
  const [activeChronologyTab, setActiveChronologyTab] = useState<ChronologyTab>('all');
  const [combatRefreshKey, setCombatRefreshKey] = useState(0);
  const previousBusy = useRef(busy);
  useEffect(() => {
    if (previousBusy.current && !busy) setCombatRefreshKey(value => value + 1);
    previousBusy.current = busy;
  }, [busy]);
  useEffect(() => {
    if (import.meta.env.DEV) console.info(`[UI timeline] highlighted=${report.events.length} additional=${report.additionalEvents.length} initially_visible=${Math.min(20, report.events.length)}`);
  }, [report.events.length, report.additionalEvents.length]);
  const hasReport = Boolean(value);
  const onTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = reportTabs.findIndex(item => item.id === activeTab);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? reportTabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + reportTabs.length) % reportTabs.length;
    setActiveTab(reportTabs[next].id);
    document.getElementById('ai-tab-' + reportTabs[next].id)?.focus();
  };
  const onChronologyKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = chronologyTabs.findIndex(item => item.id === activeChronologyTab);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? chronologyTabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + chronologyTabs.length) % chronologyTabs.length;
    setActiveChronologyTab(chronologyTabs[next].id);
    document.getElementById('ai-chronology-tab-' + chronologyTabs[next].id)?.focus();
  };
  return <section className="deep-panel ai-report">
    <header className="ai-report-toolbar"><div><span className="eyebrow">INFORME DE PARTIDA</span><h2>Análisis de rendimiento con IA</h2><p>Evaluación estratégica de tu partida</p></div>
      <button className="ai-report-refresh" type="button" disabled={busy} onClick={onGenerate}><AppIcon className={busy ? 'ai-report-spinner' : ''} name="refresh"/>{busy ? 'Generando análisis...' : hasReport ? 'Regenerar análisis' : 'Generar análisis'}</button>
    </header>
    {busy && <p className="ai-report-generating" role="status"><span className="ai-report-loading-spinner"/>Generando el análisis. Puedes seguir consultando el informe.</p>}
    {error && <p className="ai-report-error" role="alert">{error}</p>}
    <div className="ai-report-tabs" role="tablist" aria-label="Secciones del análisis de rendimiento">
      {reportTabs.map(tab => <button key={tab.id} id={'ai-tab-' + tab.id} type="button" role="tab" aria-selected={activeTab === tab.id} aria-controls={'ai-panel-' + tab.id} tabIndex={activeTab === tab.id ? 0 : -1} className={activeTab === tab.id ? 'active' : ''} onClick={() => setActiveTab(tab.id)} onKeyDown={onTabKeyDown}><AppIcon name={tab.icon}/>{tab.label}</button>)}
    </div>
    <div id="ai-panel-summary" className="ai-report-tab-panel" role="tabpanel" aria-labelledby="ai-tab-summary" hidden={activeTab !== 'summary'}>
      {!value ? <div className="ai-report-empty"><Icon name="sparkles"/><p>El informe se genera a petición a partir de las estadísticas y eventos disponibles de Riot. El vídeo no se analiza visualmente.</p></div> : <>
        <div className="ai-report-overview">
          <article className={'ai-report-grade ' + report.gradeTone}><span>Evaluación general</span><strong>{report.grade || 'Evaluación de la partida'}</strong></article>
          <article className="ai-report-summary"><h3>Resumen de la partida</h3><p>{richText(report.summary || 'El informe no incluye un resumen breve.')}</p></article>
          {report.strengths[0] && <article className="ai-report-callout positive"><h3><Icon name="check"/> Punto fuerte</h3><p>{richText(report.strengths[0])}</p></article>}
          {(report.weaknesses[0] || report.mainError) && <article className="ai-report-callout caution"><h3><Icon name="alert"/> Aspecto a mejorar</h3><p>{richText(report.weaknesses[0] || report.mainError)}</p></article>}
          {report.priority && <article className="ai-report-callout priority"><h3><Icon name="target"/> Prioridad principal</h3><p>{richText(report.priority)}</p></article>}
        </div>
        {(report.strengths.length || report.weaknesses.length) > 0 && <section className="ai-report-section"><h3 className="ai-report-section-title">Lo mejor y lo que puedes mejorar</h3><div className="ai-report-columns">
          {report.strengths.length > 0 && <article className="ai-report-card positive"><h4><Icon name="check"/> Fortalezas</h4><Bullets items={showAllStrengths ? report.strengths : report.strengths.slice(0, 3)} richText={richText}/>{report.strengths.length > 3 && <button className="ai-report-more" onClick={() => setShowAllStrengths(x => !x)}>{showAllStrengths ? 'Mostrar menos' : 'Ver ' + (report.strengths.length - 3) + ' más'}</button>}</article>}
          {report.weaknesses.length > 0 && <article className="ai-report-card caution"><h4><Icon name="alert"/> Aspectos a mejorar</h4><Bullets items={showAllWeaknesses ? report.weaknesses : report.weaknesses.slice(0, 3)} richText={richText}/>{report.weaknesses.length > 3 && <button className="ai-report-more" onClick={() => setShowAllWeaknesses(x => !x)}>{showAllWeaknesses ? 'Mostrar menos' : 'Ver ' + (report.weaknesses.length - 3) + ' más'}</button>}</article>}
        </div></section>}
        
      </>}
    </div>
    <div id="ai-panel-performance" className="ai-report-tab-panel" role="tabpanel" aria-labelledby="ai-tab-performance" hidden={activeTab !== 'performance'}>
      {report.categories.length > 0 && <section className="ai-report-section"><h3 className="ai-report-section-title">Análisis por categoría</h3><div className="ai-report-category-grid">{report.categories.map(item => <article className="ai-report-card ai-report-category" key={item.key}><h4><Icon name={item.icon}/>{item.label}</h4>{item.assessment && <p>{richText(item.assessment)}</p>}{item.recommendations[0] && <p className="category-action"><b>Recomendación</b>{richText(item.recommendations[0])}</p>}{Boolean(item.strengths.length || item.mistakes.length || item.recommendations.length > 1) && <Expandable><Bullets items={[...item.strengths.map(x => 'A favor: ' + x), ...item.mistakes.map(x => 'A revisar: ' + x), ...item.recommendations.slice(1).map(x => 'Recomendación: ' + x)]} richText={richText}/></Expandable>}{item.key === 'itemization' && <ItemizationDetails value={value} catalog={itemCatalog} itemAssets={itemAssets} richText={richText}/>}</article>)}</div></section>}
      {value && <RuneAnalysis evaluation={report.runeEvaluation ?? {}} rawRunes={isData(value.match_evidence) && isData(value.match_evidence.player) ? value.match_evidence.player.runes : null} assets={itemAssets} richText={richText}/>}
      
      {!report.categories.length && <p className="ai-report-tab-empty">No hay categorías de rendimiento disponibles en este informe.</p>}
    </div>
    <div id="ai-panel-chronology" className="ai-report-tab-panel" role="tabpanel" aria-labelledby="ai-tab-chronology" hidden={activeTab !== 'chronology'}>
      <div className="ai-report-chronology-tabs" role="tablist" aria-label="Vistas de la cronologí">
        {chronologyTabs.map(tab => <button key={tab.id} id={'ai-chronology-tab-' + tab.id} type="button" role="tab" aria-selected={activeChronologyTab === tab.id} aria-controls={'ai-chronology-panel-' + tab.id} tabIndex={activeChronologyTab === tab.id ? 0 : -1} className={activeChronologyTab === tab.id ? 'active' : ''} onClick={() => setActiveChronologyTab(tab.id)} onKeyDown={onChronologyKeyDown}><AppIcon name={tab.icon}/>{tab.label}</button>)}
      </div>
      <ChronologyPanel id="all" active={activeChronologyTab === 'all'}>
        {report.phases.length > 0 && <section className="ai-report-section"><h3 className="ai-report-section-title">Fases del juego</h3><div className="ai-report-phase-grid">{report.phases.map(phase => <article className="ai-report-card ai-report-phase" key={phase.key}><h4><Icon name={phase.icon}/>{phase.title}</h4>{phase.assessment && <p className="ai-report-assessment">{richText(phase.assessment)}</p>}{phase.worked[0] && <p className="phase-good"><b>Qué funcionó</b>{richText(phase.worked[0])}</p>}{phase.failed[0] && <p className="phase-bad"><b>Qué revisar</b>{richText(phase.failed[0])}</p>}{phase.recommendations[0] && <p className="phase-action"><b>Próximo ajuste</b>{richText(phase.recommendations[0])}</p>}{(phase.worked.length > 1 || phase.failed.length > 1 || phase.recommendations.length > 1 || phase.evidence.length > 0) && <Expandable><Bullets items={phase.worked.slice(1).map(item => 'Qué funcionó: ' + item).concat(phase.failed.slice(1).map(item => 'Qué revisar: ' + item), phase.recommendations.slice(1).map(item => 'Recomendación: ' + item), phase.evidence)} richText={richText}/></Expandable>}</article>)}</div></section>}
        {!report.phases.length && <p className="ai-report-tab-empty">No hay fases del juego disponibles en este informe.</p>}
        <EventList title="Momentos clave" events={report.timelineEvents} showAll={showAllEvents} onShowAll={() => setShowAllEvents(value => !value)} emptyMessage={chronologyEmptyMessage(value, timelineIndex)} richText={richText}/>
      </ChronologyPanel>
      <ChronologyPanel id="combat" active={activeChronologyTab === 'combat'}><EventList title="Combates con tu participación" events={report.combats} emptyMessage="No se detectaron combates agrupados de cuatro o más bajas en los que participaras." richText={richText}/></ChronologyPanel>
      <ChronologyPanel id="objectives" active={activeChronologyTab === 'objectives'}><EventList title="Objetivos personales" events={report.objectives} emptyMessage="No hay objetivos asegurados por ti ni conversiones personales verificadas." richText={richText}/></ChronologyPanel>
      <ChronologyPanel id="rewards" active={activeChronologyTab === 'rewards'}><EventList title="Shutdowns de 700 de oro" events={report.rewards} emptyMessage="No hay shutdowns confirmados de 700 de oro en los que participaras." richText={richText}/></ChronologyPanel>
    </div>
    <div id="ai-panel-combat" className="ai-report-tab-panel" role="tabpanel" aria-labelledby="ai-tab-combat" hidden={activeTab !== 'combat'}>
      <CombatMatchupsTab matchId={matchId} active={activeTab === 'combat'} cachedMatchups={cachedMatchups} refreshKey={combatRefreshKey}/>
    </div>
    <div id="ai-panel-plan" className="ai-report-tab-panel" role="tabpanel" aria-labelledby="ai-tab-plan" hidden={activeTab !== 'plan'}>
      {report.priorities.length > 0 ? <section className="ai-report-section"><h3 className="ai-report-section-title"><Icon name="target"/> Plan de mejora</h3><div className="ai-report-plan">{report.priorities.map((item, i) => <article className="ai-report-card" key={item.title + '-' + i}><span className={'ai-report-priority priority-' + item.priority}>{item.priority ? 'Prioridad ' + (item.priority === 'high' ? 'alta' : item.priority === 'medium' ? 'media' : 'baja') : 'Acción recomendada'}</span><h4>{richText(item.title)}</h4>{item.action && <p>{richText(item.action)}</p>}{item.explanation && item.explanation !== item.action && <small>{richText(item.explanation)}</small>}</article>)}</div></section> : <p className="ai-report-tab-empty">Este informe no contiene recomendaciones priorizadas.</p>}
    </div>
  </section>;
}

function transform(value: Data | null, timelineIndex: Data | null = null) {
  const summary = isData(value?.summary) ? value.summary : {};
  const grade = first(summary.overall_grade, summary.overall_assessment);
  const gradeNorm = norm(grade);
  const strengthList = dedupe([...texts(summary.strengths), ...[text(summary.primary_strength)].filter(Boolean)]);
  const weaknessList = dedupe([...texts(summary.weaknesses), ...[text(summary.primary_weakness)].filter(Boolean)]);
  const phasesObject = isData(value?.game_phases) ? value.game_phases : {};
  const phases = Object.entries(phaseLabels).flatMap(([key, title]) => {
    const raw = phasesObject[key]; if (!isData(raw)) return [];
    const phaseSummary = first(raw.summary, raw.assessment);
    const phase = { key, title, icon: (key === 'early' ? 'clock' : key === 'mid' ? 'swords' : 'target') as IconName, assessment: isRawPhaseEventDump(phaseSummary) ? '' : phaseSummary, worked: dedupe([...texts(raw.what_worked), ...texts(raw.strengths)]), failed: dedupe([...texts(raw.what_failed), ...texts(raw.mistakes)]), recommendations: dedupe([...texts(raw.adaptation), ...texts(raw.recommendations)]), evidence: evidenceLabels(raw.evidence_events) };
    if (/no hay eventos suficientes|no hay datos suficientes/.test(norm(phase.assessment)) && !phase.evidence.length) return [];
    return [phase];
  });
  const performance = isData(value?.performance) ? value!.performance : {};
  const categoryData = categories.flatMap(def => {
    const raw = isData(value?.[def.key]) ? value![def.key] as Data : {};
    const model = isData(performance[def.key]) ? performance[def.key] as Data : {};
    const assessment = first(raw.assessment, raw.short_summary, model.assessment);
    const recommendations = dedupe([...texts(raw.recommendations), ...texts(model.tip)]);
    const strengths = texts(raw.strengths), mistakes = texts(raw.mistakes);
    return assessment || recommendations.length || strengths.length || mistakes.length ? [{ ...def, assessment, strengths, mistakes, recommendations }] : [];
  });
  if (text(value?.build_assessment) || texts(value?.itemization_notes).length) {
    const itemization = categoryData.find(item => item.key === 'itemization');
    const notes = texts(value?.itemization_notes);
    if (itemization) {
      itemization.assessment ||= text(value?.build_assessment);
      itemization.mistakes = dedupe([...itemization.mistakes, ...notes]);
    } else categoryData.push({ key: 'build_assessment', label: 'Objetos y equipamiento', icon: 'swords', assessment: text(value?.build_assessment), strengths: [], mistakes: notes, recommendations: [] });
  }
  if (!categoryData.some(item => item.key === 'itemization') && ([value?.item_reviews, value?.item_alternatives, value?.situational_item_suggestions].some(items => Array.isArray(items) && items.length > 0))) {
    categoryData.push({ key: 'itemization', label: 'Objetos y equipamiento', icon: 'swords', assessment: '', strengths: [], mistakes: [], recommendations: [] });
  }
  const prioritiesRaw = Array.isArray(value?.next_game_priorities) ? value!.next_game_priorities : Array.isArray(value?.improvement_priorities) ? value!.improvement_priorities : [];
  const priorities = dedupeObjects(prioritiesRaw);
  const { events, additionalEvents, combats, objectives, rewards } = extractEvents(value, timelineIndex);
  const timelineEvents = [...events, ...additionalEvents].sort((a, b) => eventTimeSeconds(a.time) - eventTimeSeconds(b.time));
  return { grade, gradeTone: /excel|buena|positiv|fuerte/.test(gradeNorm) ? 'positive' : /mal|baja|negativ|dificil|difícil/.test(gradeNorm) ? 'negative' : 'neutral', summary: first(summary.short_summary, summary.key_takeaway, summary.short_summary_es), strengths: strengthList, weaknesses: weaknessList, mainError: text(summary.main_error), priority: first(summary.core_priority, priorities[0]?.action, priorities[0]?.title), phases, categories: categoryData.filter(item => item.assessment || item.strengths.length || item.mistakes.length || item.recommendations.length), priorities, events, additionalEvents, timelineEvents, combats, objectives, rewards, runeEvaluation: isData(value?.rune_evaluation) ? value.rune_evaluation : null };
}

type ItemMeta = { id: string; name: string; description: string; cost: string; stats: string };
function reportItemCatalog(value: Data | null): Map<string, ItemMeta> {
  const result = new Map<string, ItemMeta>();
  const add = (raw: unknown) => {
    if (!isData(raw)) return;
    const id = text(raw.item_id ?? raw.itemId ?? raw.id);
    if (!/^\d{1,8}$/.test(id)) return;
    const name = first(raw.name, raw.target_item_name, raw.component_name, raw.replace_or_delay_item, raw.target_item, `Objeto ${id}`);
    const stats = isData(raw.stats) ? Object.entries(raw.stats).map(([key, val]) => `${key}: ${String(val)}`).join(' · ') : '';
    result.set(id, { id, name, description: first(raw.description, raw.mechanical_advantage, raw.assessment, raw.model_note), cost: String(raw.gold_total ?? raw.cost ?? ''), stats });
  };
  const evidence = isData(value?.match_evidence) ? value.match_evidence : {};
  (Array.isArray(evidence.item_catalog) ? evidence.item_catalog : []).forEach(add);
  (Array.isArray(value?.item_reviews) ? value!.item_reviews : []).forEach(add);
  (Array.isArray(value?.item_alternatives) ? value!.item_alternatives : []).forEach(item => {
    add(item);
    if (isData(item)) {
      add({ item_id: item.replace_or_delay_item_id, name: item.replace_or_delay_item, description: item.replace_or_delay_item_description, stats: item.replace_or_delay_item_stats, gold_total: item.replace_or_delay_item_gold_total });
      add({ item_id: item.component_id, name: item.component_name });
    }
  });
  (Array.isArray(value?.situational_item_suggestions) ? value!.situational_item_suggestions : []).forEach(add);
  return result;
}
function renderItemReferences(content: string, catalog: Map<string, ItemMeta>, assets: Record<string, string | null>): React.ReactNode {
  if (!content || !catalog.size) return content;
  const entries = [...catalog.values()].sort((a, b) => b.name.length - a.name.length);
  const patterns = entries.flatMap(item => [
    { item, regex: new RegExp(`\\b${item.id}\\b`, 'g') },
    { item, regex: new RegExp(`${escapeRegExp(item.name)}(?:\\s*\\(\\s*${item.id}\\s*\\))?`, 'gi') },
  ]);
  const matches: Array<{ start: number; end: number; item: ItemMeta }> = [];
  for (const { item, regex } of patterns) {
    regex.lastIndex = 0;
    let found: RegExpExecArray | null;
    while ((found = regex.exec(content))) matches.push({ start: found.index, end: found.index + found[0].length, item });
  }
  matches.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  for (const match of matches) {
    if (match.start < cursor) continue;
    if (match.start > cursor) parts.push(content.slice(cursor, match.start));
    const meta = match.item;
    const tooltip = [meta.name, meta.description, meta.stats, meta.cost ? `Coste: ${meta.cost} de oro` : ''].filter(Boolean).join('\n');
    const icon = assets[`item:${meta.id}`];
    parts.push(icon ? <span className="ai-report-item-reference" key={`${match.start}-${meta.id}`} title={tooltip} aria-label={meta.name}><img src={icon} alt="" loading="lazy"/></span> : <span className="ai-report-item-fallback" key={`${match.start}-${meta.id}`} title={tooltip}>{meta.name}</span>);
    cursor = match.end;
  }
  if (!parts.length) return content;
  if (cursor < content.length) parts.push(content.slice(cursor));
  return <>{parts}</>;
}
function escapeRegExp(value: string): string { return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function ItemIcon({ id, catalog, assets }: { id: unknown; catalog: Map<string, ItemMeta>; assets: Record<string, string | null> }) {
  const meta = catalog.get(text(id));
  if (!meta) return null;
  const tooltip = [meta.name, meta.description, meta.stats, meta.cost ? `Coste: ${meta.cost} de oro` : ''].filter(Boolean).join('\n');
  const icon = assets[`item:${meta.id}`];
  return icon ? <span className="ai-report-item-reference" title={tooltip} aria-label={meta.name}><img src={icon} alt="" loading="lazy"/></span> : <span className="ai-report-item-fallback" title={tooltip}>{meta.name}</span>;
}
function ItemizationDetails({ value, catalog, itemAssets, richText }: { value: Data | null; catalog: Map<string, ItemMeta>; itemAssets: Record<string, string | null>; richText: (value: string) => React.ReactNode }) {
  const reviews = Array.isArray(value?.item_reviews) ? value!.item_reviews.filter(isData) : [];
  const alternatives: Data[] = [
    ...(Array.isArray(value?.item_alternatives) ? value!.item_alternatives.filter(isData) : []),
    ...(Array.isArray(value?.situational_item_suggestions) ? value!.situational_item_suggestions.filter(isData).map(item => ({ ...item, mechanical_advantage: first(item.reason, item.mechanical_advantage) } as Data)) : []),
  ];
  if (!reviews.length && !alternatives.length) return null;
  return <div className="ai-report-itemization-extra">
    {reviews.length > 0 && <section><h5>Evaluación de tu equipamiento</h5><div className="ai-report-item-review-list">{reviews.map((item, index) => <article key={`${text(item.item_id)}-${index}`}><ItemIcon id={item.item_id} catalog={catalog} assets={itemAssets}/><span><b>{text(item.verdict) || 'Objeto comprado'}</b><small>{richText(first(item.model_assessment, item.assessment, text(item.name)))}</small></span></article>)}</div></section>}
    {alternatives.length > 0 && <section><h5>Alternativas recomendadas</h5><div className="ai-report-item-alternatives">{alternatives.map((item, index) => <article key={`${text(item.item_id)}-${index}`}><div className="ai-report-item-pair"><ItemIcon id={item.item_id} catalog={catalog} assets={itemAssets}/>{text(item.replace_or_delay_item_id) && <><span>por</span><ItemIcon id={item.replace_or_delay_item_id} catalog={catalog} assets={itemAssets}/></>}</div><p>{richText(first(item.model_note, item.mechanical_advantage, item.reason))}</p>{text(item.tradeoff) && <small>Coste de oportunidad: {richText(text(item.tradeoff))}</small>}{text(item.timing) && <small>{richText(text(item.timing))}</small>}</article>)}</div></section>}
  </div>;
}
function RuneAnalysis({ evaluation, rawRunes, assets, richText }: { evaluation: Data; rawRunes: unknown; assets: Record<string, string | null>; richText: (value: string) => React.ReactNode }) {
  const selected = Array.isArray(evaluation.selected_runes) ? evaluation.selected_runes.filter(isData) : [];
  if (!selected.length && isData(rawRunes) && Array.isArray(rawRunes.styles)) {
    rawRunes.styles.slice(0, 2).forEach(style => {
      if (isData(style) && Array.isArray(style.selections)) style.selections.slice(0, 4).forEach(selection => {
        if (isData(selection)) { const id = numericRuneId(selection.perk); if (id) selected.push({ id, name: 'Runa equipada', description: '' }); }
      });
    });
  }
  const current = isData(evaluation.current) ? evaluation.current : null;
  const alternative = isData(evaluation.alternative) ? evaluation.alternative : null;
  const matchupComments = texts(evaluation.matchup_assessment);
  return <section className="ai-report-section ai-report-rune-section"><h3 className="ai-report-section-title">Runas</h3><article className="ai-report-card ai-report-runes"><h4><Icon name="sparkles"/> Configuración utilizada</h4>{selected.length ? <div className="ai-report-rune-list">{selected.map((rune, index) => { const id = text(rune.id); const image = assets[`rune:${id}`]; const tooltip = [text(rune.name), text(rune.description) || (text(rune.name) === 'Runa equipada' ? 'Descripción no disponible para este informe guardado.' : '')].filter(Boolean).join('\n'); return <span key={`${id}-${index}`} className="ai-report-rune" title={tooltip}>{image ? <img src={image} alt="" loading="lazy"/> : <i/>}<small>{text(rune.name) || `Runa ${index + 1}`}</small></span>; })}</div> : <p className="ai-report-assessment">El informe guardado no conserva una configuración de runas identificable; no se inventan selecciones.</p>}{current && <p className="ai-report-assessment"><b>{text(evaluation.verdict) || 'Evaluación'}</b> · {richText(text(evaluation.conclusion))}</p>}{matchupComments.map((comment, index) => <p className="ai-report-assessment" key={index}>{richText(comment)}</p>)}{!current && !matchupComments.length && <p className="ai-report-assessment">No hay una evaluación estratégica de runas en este informe guardado.</p>}</article>
    {(alternative || selected.length > 0) && <article className="ai-report-card ai-report-rune-alternative"><h4>Alternativa recomendada</h4>{alternative ? <><p>{assets[`rune:${text(alternative.id)}`] && <img src={assets[`rune:${text(alternative.id)}`]!} alt="" title={`${text(alternative.name)} · ${text(alternative.mechanics)}`} loading="lazy"/>}<b>{text(alternative.name)}</b>{text(alternative.reason || alternative.mechanics) && <> · {richText(text(alternative.reason || alternative.mechanics))}</>}</p>{text(alternative.tradeoff) && <small>Coste de oportunidad: {richText(text(alternative.tradeoff))}</small>}</> : <p>No se encontró una alternativa distinta con respaldo suficiente para esta configuración y enfrentamiento.</p>}</article>}
  </section>;
}

function evidenceLabels(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap(raw => {
    if (!isData(raw)) return [];
    const eventType = text(raw.event_type ?? raw.type).toLocaleLowerCase();
    const time = first(text(raw.time_label), timestamp(raw.timestamp ?? raw.time_seconds ?? raw.time));
    const title = first(raw.title, raw.description, eventLabel(eventType));
    const detail = first(raw.explanation, raw.impact, raw.note);
    return [`${time ? `${time} · ` : ''}${title}${detail ? ` — ${detail}` : ''}`];
  });
}
function timestamp(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '';
  const seconds = value > 100000 ? Math.floor(value / 1000) : Math.floor(value);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
function eventLabel(type: string): string { return type.includes('death') ? 'Muerte' : type.includes('kill') ? 'Eliminación' : type.includes('dragon') ? 'Dragón' : type.includes('baron') ? 'Barón Nashor' : type.includes('herald') ? 'Heraldo' : type.includes('turret') || type.includes('building') ? 'Estructura' : type.includes('objective') ? 'Objetivo' : 'Evento registrado'; }
function extractEvents(value: Data | null, timelineIndex: Data | null = null): { events: ReportEvent[]; additionalEvents: ReportEvent[]; combats: ReportEvent[]; objectives: ReportEvent[]; rewards: ReportEvent[] } {
  const reportEvidence = isData(value?.match_evidence) ? value!.match_evidence : {};
  const evidence = isData(timelineIndex) && timelineIndex.index_version === 1
    && ['available', 'available_empty'].includes(text(timelineIndex.status))
    ? timelineIndex : reportEvidence;
  const timeline = Array.isArray(evidence.notable_timeline) ? evidence.notable_timeline.filter(isData) : [];
  const byId = new Map<string, Data>();
  timeline.forEach(event => { const id = text(event.event_id); if (id) byId.set(id, event); });
  const localTeam = text(isData(evidence.match) ? evidence.match.local_team : '').toLocaleUpperCase();
  const selection = isData(evidence.personal_event_selection) ? evidence.personal_event_selection : {};
  const personalIds = new Set(texts(selection.personal_event_ids));
  const combatIds = new Set(texts(selection.combat_event_ids));
  const objectiveIds = new Set(texts(selection.objective_event_ids));
  const rewardIds = new Set(texts(selection.reward_event_ids));
  const deathObjectiveRelations = Array.isArray(selection.player_death_objective_correlations) ? selection.player_death_objective_correlations.filter(isData) : [];
  const deathObjectivePairs = new Set(deathObjectiveRelations.filter(item => item.status === 'accepted').map(item => text(item.death_event_id) + '|' + text(item.objective_event_id)));
  if (!personalIds.size) {
    // Compatibility for old cached indexes: reconstruct personal eligibility from
    // participant IDs and already validated correlations; never infer by time/team.
    const correlations = Array.isArray(evidence.kill_objective_correlations) ? evidence.kill_objective_correlations.filter(isData) : [];
    for (const event of timeline) {
      const id = text(event.event_id), category = text(event.category);
      const direct = event.player_involved === true;
      if (category === 'kill' && direct && event.bounty === 700 && (event.killer_key === 'player_local' || texts(event.assister_keys).includes('player_local'))) rewardIds.add(id);
      if (['objective', 'structure'].includes(category) && (event.killer_key === 'player_local' || event.player_key === 'player_local')) objectiveIds.add(id);
    }
    for (const relation of correlations) {
      const kill = byId.get(text(relation.kill_event_id));
      const objective = text(relation.objective_event_id);
      if (relation.status === 'accepted' && kill?.player_involved === true && objectiveIds.has(objective)) {
        objectiveIds.add(text(relation.kill_event_id));
      }
    }
    const fights = Array.isArray(evidence.teamfights) ? evidence.teamfights.filter(isData) : [];
    for (const fight of fights) if (Number(fight.death_count) >= 4 && fight.local_player_involved === true) {
      for (const ref of texts(fight.event_ids)) { combatIds.add(ref); personalIds.add(ref); }
    }
    [...objectiveIds, ...rewardIds].forEach(id => personalIds.add(id));
  }
  const reportEvents = Array.isArray(value?.key_events) ? value!.key_events : [];
  const indexedEvents = Array.isArray(evidence.key_events) ? evidence.key_events : [];
  const raw = [...reportEvents, ...indexedEvents];
  const relevanceRank: Record<string, number> = { low: 0, medium: 1, high: 2 };
  const seenGroups = new Set<string>();
  const events: ReportEvent[] = raw.flatMap(rawEvent => {
    if (!isData(rawEvent)) return [];
    const refs = [...new Set(texts(rawEvent.event_ids))];
    const records = refs.map(ref => byId.get(ref)).filter((item): item is Data => Boolean(item));
    const title = text(rawEvent.title), description = text(rawEvent.description);
    const importanceReason = cleanTimelineDisclaimer(text(rawEvent.why_it_matters));
    const groupKey = [...refs].sort().join('|');
    if (!refs.length || refs.length !== records.length || !title || !description || importanceReason.length < 8
      || ((personalIds.size > 0 || Number(selection.version) >= 1) && refs.some(ref => !personalIds.has(ref))) || seenGroups.has(groupKey)) return [];
    seenGroups.add(groupKey);
    const times = [...new Set(records.map(item => first(item.time_label, timestamp(item.time_seconds))).filter(Boolean))].sort((a, b) => eventTimeSeconds(a) - eventTimeSeconds(b));
    const facts = norm(records.map(item => [item.category, item.type, item.objective, item.label].map(text).join(' ')).join(' '));
    const localDeath = records.some(item => item.victim_key === 'player_local');
    const localKill = records.some(item => item.killer_key === 'player_local');
    const hasObjective = /objective|structure|dragon|baron|herald|turret|building|inhibitor/.test(facts);
    const objectiveTeams = records.filter(item => /objective|structure/.test(norm([item.category, item.type, item.objective].map(text).join(' ')))).map(item => text(item.team).toLocaleUpperCase()).filter(Boolean);
    const alliedObjective = Boolean(hasObjective && localTeam && objectiveTeams.includes(localTeam));
    const enemyObjective = Boolean(hasObjective && localTeam && objectiveTeams.some(team => team !== localTeam));
    const negative = enemyObjective || localDeath && !alliedObjective;
    const positive = alliedObjective || localKill && !negative;
    const inverseConversion = [...deathObjectivePairs].some(pair => { const [deathRef, objectiveRef] = pair.split('|'); return refs.includes(deathRef) && refs.includes(objectiveRef); });
    const icon = inverseConversion ? 'alert' : facts.includes('baron') ? 'baron' : facts.includes('dragon') ? 'dragon' : facts.includes('herald') ? 'herald' : /turret|building|inhibitor|structure/.test(facts) ? 'turret' : hasObjective ? 'target' : localDeath ? 'alert' : 'swords';
    const secondaryIcon = inverseConversion ? eventIcon(records.find(item => ['objective', 'structure'].includes(text(item.category))) || records[records.length - 1]) : undefined;
    const rank = records.map(item => text(item.relevance)).sort((a,b) => (relevanceRank[b] ?? 0) - (relevanceRank[a] ?? 0))[0] || 'medium';
    return [{ title, time: times.join(' - '), description, importanceReason, tone: inverseConversion || negative ? 'negative' : positive ? 'positive' : 'neutral', icon: icon as IconName, secondaryIcon, evidenceRefs: refs, source: text(rawEvent.source), relevance: text(rawEvent.relevance) || rank, eventKind: inverseConversion ? 'player_death_to_enemy_objective' : text(rawEvent.event_kind), playerContribution: cleanTimelineDisclaimer(text(rawEvent.player_contribution)), recommendation: cleanTimelineDisclaimer(text(rawEvent.recommendation)) }];
  });
  const used = new Set(events.flatMap(event => event.evidenceRefs));
  const additionalEvents: ReportEvent[] = timeline.flatMap(event => {
    const id = text(event.event_id), category = text(event.category);
    if (!id || used.has(id) || !personalIds.has(id) || !['kill', 'objective', 'structure'].includes(category)) return [];
    const team = text(event.team).toLocaleUpperCase();
    const isLocalKill = event.killer_key === 'player_local';
    const isLocalDeath = event.victim_key === 'player_local';
    const enemyObjective = category !== 'kill' && Boolean(localTeam && team && team !== localTeam);
    return [{ title: first(event.label, eventLabel(text(event.type))), time: first(event.time_label, timestamp(event.time_seconds)), description: '', importanceReason: '', tone: enemyObjective || isLocalDeath ? 'negative' : isLocalKill || category !== 'kill' && team === localTeam ? 'positive' : 'neutral', icon: category === 'kill' ? isLocalDeath ? 'alert' : 'swords' : eventIcon(event), evidenceRefs: [id], source: 'factual_timeline', relevance: '' } as ReportEvent];
  }).sort((a, b) => eventTimeSeconds(a.time) - eventTimeSeconds(b.time));
  const all = [...events, ...additionalEvents];
  const matching = (ids: Set<string>) => all.filter(event => event.evidenceRefs.some(ref => ids.has(ref)));
  return { events, additionalEvents, combats: matching(combatIds), objectives: matching(objectiveIds), rewards: matching(rewardIds) };
}
function cleanTimelineDisclaimer(value: string): string {
  return value.replace(/La secuencia y los participantes(?: compartidos)? est(?:\u00e1n|an) confirmados;\s*no demuestra(?: causalidad| que la baja causara el objetivo)?\.?/gi, '').replace(/\s{2,}/g, ' ').trim();
}
function chronologyEmptyMessage(value: Data | null, timelineIndex: Data | null = null): string {
  if (isData(timelineIndex) && timelineIndex.index_version === 1) {
    if (timelineIndex.status === 'missing_local') return 'No hay una cronología local guardada para esta partida. La lista se reconstruirá cuando Riot o la caché local proporcionen sus eventos.';
    if (timelineIndex.status === 'retrieval_failed') return 'No se pudo leer la cronología desde la caché local. El informe guardado se conserva y se puede reintentar la carga.';
    if (timelineIndex.status === 'malformed') return 'Se encontró una cronología local dañada o incompleta y no se pudo validar. Los datos originales se conservaron.';
    if (timelineIndex.status === 'available_empty') return 'La cronología se cargó correctamente, pero no contiene eventos estratégicos que cumplan los criterios de esta lista.';
  }
  const evidence = isData(value?.match_evidence) ? value!.match_evidence : {};
  const extraction = isData(evidence.timeline_extraction) ? evidence.timeline_extraction : {};
  if (text(extraction.status) === 'unavailable' || (extraction.status == null && isData(evidence.coverage) && evidence.coverage.timeline_available === false)) {
    return 'No hay una cronología de eventos disponible en este informe guardado. Si se conserva la partida con su timeline local, puede reconstruirse al actualizar el análisis.';
  }
  if (!Array.isArray(evidence.notable_timeline)) {
    return 'Este informe antiguo no guardó el índice de eventos. Regenera el análisis cuando haya una cronología local disponible para reconstruirlo.';
  }
  return 'La cronología se procesó, pero no hay secuencias adicionales respaldadas para destacar. Los objetivos y combates detectados se muestran cuando sus eventos están presentes en los datos guardados.';
}
function eventIcon(event: Data): IconName {
  const facts = norm([event.category, event.type, event.objective, event.label].map(text).join(' '));
  return facts.includes('baron') ? 'baron' : facts.includes('dragon') ? 'dragon' : facts.includes('herald') ? 'herald' : /turret|building|inhibitor|structure/.test(facts) ? 'turret' : 'target';
}
function eventTimeSeconds(value: string): number { const match = /^(\d+):(\d{2})$/.exec(value); return match ? Number(match[1]) * 60 + Number(match[2]) : Number.MAX_SAFE_INTEGER; }
function dedupeObjects(raw: unknown[]): Array<{ title: string; action: string; explanation: string; priority: string }> {
  const seen = new Set<string>();
  return raw.flatMap(item => {
    if (!isData(item)) return [];
    const title = first(item.title, item.name, item.action, item.concrete_action);
    const action = first(item.action, item.concrete_action, item.recommendation);
    const explanation = first(item.explanation, item.evidence, item.rationale);
    if (!title && !action && !explanation) return [];
    const key = norm(action || title); if (seen.has(key)) return []; seen.add(key);
    const rawPriority = norm(text(item.priority));
    const priority = /high|alta|critical|critica/.test(rawPriority) ? 'high' : /medium|media|moderada/.test(rawPriority) ? 'medium' : /low|baja/.test(rawPriority) ? 'low' : '';
    return [{ title: title || action, action, explanation, priority }];
  });
}
