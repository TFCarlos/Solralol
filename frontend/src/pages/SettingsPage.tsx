import { useCallback, useEffect, useRef, useState } from 'react';
import type { DesktopSettings } from '../types/contracts';
import type { StorageInfo, StorageMigrationStatus, StoragePreview } from '../types/contracts';
import { Icon } from '../components/Icon';
import { AnalysisSettingsPanel } from './AnalysisSettingsPanel';
import { OverlayContent, overlayPreview, type OverlayPanel } from './LiveOverlayPanel';

type Section = 'cuenta' | 'grabacion' | 'overlays' | 'almacenamiento' | 'analisis';
type Provider = 'riot' | 'gemini';
const panelNames: Record<OverlayPanel, string> = { gold: 'Diferencias de oro', alerts: 'Alertas', purchase: 'Compra recomendada', recall:'Último backeo', ability:'Orden de habilidades' };
const qualityOptions: Array<[string, string]> = [['1080','1080p · 60 FPS'],['108030','1080p · 30 FPS'],['900','900p · 60 FPS'],['90030','900p · 30 FPS'],['720','720p · 60 FPS'],['72030','720p · 30 FPS'],['540','540p · 30 FPS'],['480','480p · 30 FPS'],['420','420p · 30 FPS']];
const bitrateOptions: Array<[number, string]> = [[16000,'16 Mbps · máxima'],[12000,'12 Mbps · muy alta'],[8000,'8 Mbps · alta'],[6000,'6 Mbps · recomendada'],[4000,'4 Mbps · media'],[2500,'2,5 Mbps · baja'],[1500,'1,5 Mbps · mínima']];
const audioOptions: Array<[string, string]> = [['none','Sin sonido · solo vídeo'],['game','Solo juego'],['mic','Solo micrófono'],['game_mic','Juego y micrófono'],['all','Juego, micrófono y resto del PC'],['full','Juego, micrófono y todo el sistema']];
const emptySettings: DesktopSettings = {
  riot_api_key_configured:false,gemini_api_key_configured:false,recording_auto:true,recording_monitor_index:-1,
  recording_quality:'1080',recording_bitrate:8000,recording_audio_mode:'game',recording_mic_device:'',
  recording_system_audio_device:'',recording_mic_capture_device:'',recording_game_audio_device:'',recording_output_dir:'',recording_size_limit_gb:50,
  overlay_panels:{gold:true,alerts:true,purchase:true,recall:true,ability:true},overlay_tab_only:{gold:false,alerts:false,purchase:false,recall:false,ability:false},
  overlay_panel_opacity:{gold:92,alerts:92,purchase:92,recall:92,ability:92},overlay_panel_click_through:{gold:false,alerts:false,purchase:false,recall:false,ability:true},
  overlay_panel_scales:{gold:1,alerts:1,purchase:1,recall:1,ability:1},overlay_positions:{},overlay_edit_shortcut:'Control+Alt+Shift+O',overlay_ability_hud_anchor:{x:0.5,y:0.89},overlay_ability_slot_spacing:47,overlay_alert_duration:8,overlay_alert_lead:60,
  overlay_sound_enabled:true,overlay_sound_volume:.6,overlay_sound_objective:true,overlay_sound_dragon:true,overlay_sound_enemy_buy:true,overlay_click_through:false,
};

export function SettingsPage({ backendReady, initialSection = 'cuenta' }: { backendReady: boolean; initialSection?: string }) {
  const [section, setSection] = useState<Section>('cuenta');
  const [settings, setSettings] = useState<DesktopSettings>(emptySettings);
  const [overlayEditing, setOverlayEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [status, setStatus] = useState<{text:string; kind:'ok'|'error'|'info'}>();
  const [riotKey, setRiotKey] = useState('');
  const [geminiKey, setGeminiKey] = useState('');
  const [devices, setDevices] = useState<string[]>([]);
  const [devicesAvailable, setDevicesAvailable] = useState<boolean>();
  const [displays, setDisplays] = useState<Array<{index:number;width:number;height:number}>>([]);
  const [storageInfo, setStorageInfo] = useState<StorageInfo>();
  const [storageCandidate, setStorageCandidate] = useState('');
  const [storagePreview, setStoragePreview] = useState<StoragePreview>();
  const [storageMigration, setStorageMigration] = useState<StorageMigrationStatus>();
  const [previewAssets, setPreviewAssets] = useState<Record<string,string|null>>({});
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => { let active=true; void window.solralol.getOverlayEditing().then(value=>{if(active)setOverlayEditing(value)}); const off=window.solralol.onOverlayEditing(setOverlayEditing); return()=>{active=false;off();}; }, []);

  useEffect(() => {
    if (['cuenta','grabacion','overlays','almacenamiento','analisis'].includes(initialSection)) setSection(initialSection as Section);
  }, [initialSection]);

  useEffect(() => {
    const updateMigration = (event: Event) => {
      const migration = (event as CustomEvent<StorageMigrationStatus>).detail;
      setStorageMigration(migration);
      if (migration.state === 'complete') { setBusy(''); setStatus({text:'Migración completada. Solralol abrirá los datos desde la nueva ubicación.',kind:'ok'}); }
      else if (['failed','recovery_required','cancelled'].includes(migration.state)) { setBusy(''); setStatus({text:migration.message || 'No se pudo completar la migración. La ubicación original sigue disponible.',kind:'error'}); }
    };
    window.addEventListener('solralol:migration-update', updateMigration);
    return () => window.removeEventListener('solralol:migration-update', updateMigration);
  }, []);

  useEffect(() => {
    if (!backendReady) { setLoading(true); return; }
    let active = true;
    Promise.all([window.solralol.request('settings.load'), window.solralol.getDisplays()])
      .then(([value, displayList]) => { if (active) { setSettings(value); setDisplays(displayList); } })
      .catch((error: Error) => { if (active) setStatus({text:error.message,kind:'error'}); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [backendReady]);

  useEffect(() => {
    if (!backendReady || section !== 'almacenamiento') return;
    let active = true;
    window.solralol.request('storage.info').then((value) => { if (active) { setStorageInfo(value); setStorageMigration(value.migration); } })
      .catch((error: Error) => { if (active) setStatus({text:error.message,kind:'error'}); });
    return () => { active = false; };
  }, [backendReady, section]);

  useEffect(() => {
    if (!backendReady || section !== 'overlays') return;
    let active=true;
    Promise.all([
      window.solralol.request('meta.assets',{items:['6655','3157','3089','3802','1058'],abilities:(['q','w','e','r'] as const).map(slot=>({champion:'Ahri',slot}))}),
      window.solralol.request('home.assets',{champions:['Darius','Lee Sin','Ahri','Jinx','Lulu']}),
    ]).then(([items,champions])=>{
      if(active)setPreviewAssets({...items,...Object.fromEntries(Object.entries(champions.championAliases??{}).map(([name,id])=>[`champion:${name}`,champions.champions[String(id)]??null]))});
    }).catch(()=>{});
    return()=>{active=false;};
  },[backendReady,section]);

  const save = useCallback((changes: Partial<DesktopSettings>) => {
    setSettings((current) => ({...current,...changes}));
    setStatus(undefined);
    saveQueue.current = saveQueue.current.then(async () => {
      setBusy('save');
      try {
        const next = await window.solralol.request('settings.update', {changes});
        setSettings(next);
        setStatus({text:'Ajuste guardado en la configuración local.',kind:'ok'});
      } catch (error) {
        const latest = await window.solralol.request('settings.load').catch(() => null);
        if (latest) setSettings(latest);
        setStatus({text:error instanceof Error ? error.message : 'No se pudo guardar el ajuste.',kind:'error'});
      } finally { setBusy(''); }
    });
  }, []);

  const saveKey = async (provider: Provider) => {
    const value = provider === 'riot' ? riotKey.trim() : geminiKey.trim();
    if (!value) { setStatus({text:'Introduce la clave antes de validarla.',kind:'error'}); return; }
    setBusy(provider); setStatus({text:`Comprobando clave ${provider === 'riot' ? 'Riot' : 'Gemini'}…`,kind:'info'});
    try {
      const result = await window.solralol.request('settings.key.save', {provider,apiKey:value});
      if (provider === 'riot') { setSettings((current) => ({...current,riot_api_key_configured:result.configured})); setRiotKey(''); }
      else { setSettings((current) => ({...current,gemini_api_key_configured:result.configured})); setGeminiKey(''); }
      setStatus({text:result.message,kind:result.valid?'ok':'error'});
    } catch (error) { setStatus({text:error instanceof Error?error.message:'No se pudo validar la clave.',kind:'error'}); }
    finally { setBusy(''); }
  };

  const clearKey = async (provider: Provider) => {
    setBusy(provider);
    try {
      await window.solralol.request('settings.key.clear',{provider});
      setSettings((current) => ({...current,[provider === 'riot' ? 'riot_api_key_configured' : 'gemini_api_key_configured']:false}));
      setStatus({text:`Clave ${provider === 'riot' ? 'Riot' : 'Gemini'} eliminada de la configuración local.`,kind:'ok'});
    } catch (error) { setStatus({text:error instanceof Error?error.message:'No se pudo eliminar la clave.',kind:'error'}); }
    finally { setBusy(''); }
  };

  const scanDevices = async () => {
    setBusy('devices'); setStatus({text:'Buscando FFmpeg y dispositivos de audio…',kind:'info'});
    try { const result=await window.solralol.request('settings.audio-devices'); setDevices(result.devices); setDevicesAvailable(result.available); setStatus({text:result.message,kind:result.available?'ok':'error'}); }
    catch(error) { setStatus({text:error instanceof Error?error.message:'No se pudieron consultar los dispositivos.',kind:'error'}); }
    finally { setBusy(''); }
  };

  const testRecording = async () => {
    setBusy('recording-test'); setStatus({text:'Probando la captura en segundo plano. Puede tardar unos segundos…',kind:'info'});
    try { const result=await window.solralol.request('settings.recording-test'); setStatus({text:result.video_ok?`Vídeo validado: ${result.frames} fotogramas. Audio: ${result.audio_state}`:`Prueba no completada (${result.stage}): ${result.message || result.audio_state}`,kind:result.video_ok?'ok':'error'}); }
    catch(error) { setStatus({text:error instanceof Error?error.message:'Falló la prueba de grabación.',kind:'error'}); }
    finally { setBusy(''); }
  };

  const changeFolder = async () => {
    try { const path=await window.solralol.chooseRecordingsDirectory(); if(path) { setSettings((current)=>({...current,recording_output_dir:path})); setStatus({text:'Carpeta de grabaciones guardada.',kind:'ok'}); } }
    catch(error) { setStatus({text:error instanceof Error?error.message:'No se pudo cambiar la carpeta.',kind:'error'}); }
  };

  const previewStorageChange = async (requestedPath?: string) => {
    try {
      const path = (requestedPath ?? storageCandidate) || await window.solralol.chooseStorageDirectory();
      if (!path) return;
      setBusy('storage'); setStatus(undefined);
      const preview = await window.solralol.request('storage.preview', {path});
      setStoragePreview(preview);
    } catch (error) {
      setStatus({text:error instanceof Error ? error.message : 'No se pudo validar la carpeta seleccionada.',kind:'error'});
    } finally { setBusy(''); }
  };

  const browseStorage = async () => {
    try {
      const path = await window.solralol.chooseStorageDirectory();
      if (path) { setStorageCandidate(path); setStatus({text:`Destino seleccionado: ${path}`,kind:'info'}); }
    } catch (error) { setStatus({text:error instanceof Error ? error.message : 'No se pudo abrir el selector de carpetas.',kind:'error'}); }
  };

  const migrateStorage = async () => {
    if (!storagePreview) return;
    const destination = storagePreview.destination;
    setStoragePreview(undefined); setStorageCandidate(''); setBusy('storage-migration');
    try {
      const migration = await window.solralol.request('storage.migrate.start', {path:destination});
      setStorageMigration(migration);
      window.dispatchEvent(new CustomEvent('solralol:migration-started', {detail:migration}));
    } catch (error) {
      setStatus({text:error instanceof Error ? error.message : 'No se pudo iniciar el traslado.',kind:'error'});
      setBusy('');
    }
  };

  const openStorage = async () => {
    try {
      const result = await window.solralol.openStorageDirectory();
      if (result) setStatus({text:`No se pudo abrir la carpeta: ${result}`,kind:'error'});
    } catch (error) { setStatus({text:error instanceof Error ? error.message : 'No se pudo abrir la carpeta de datos.',kind:'error'}); }
  };

  const updateMap = (key: 'overlay_panels'|'overlay_tab_only'|'overlay_panel_click_through', panel:string, value:boolean) => save({[key]:{...settings[key],[panel]:value}} as Pick<DesktopSettings, typeof key>);
  const updateNumberMap = (key:'overlay_panel_opacity'|'overlay_panel_scales',panel:string,value:number) => save({[key]:{...settings[key],[panel]:value}} as Pick<DesktopSettings, typeof key>);

  return <div className="settings-page">
    <div className="settings-heading"><div><div className="eyebrow">PREFERENCIAS DE SOLRALOL</div><h1>Ajustes</h1><p>Configura integraciones, grabación y asistencia en partida.</p></div><span className="settings-storage"><Icon name="settings"/> Guardado local</span></div>
    <nav className="settings-tabs" aria-label="Categorías de ajustes">
      {([['cuenta','Cuenta y API'],['grabacion','Grabación'],['overlays','Overlay y avisos'],['almacenamiento','Almacenamiento'],['analisis','Análisis']] as Array<[Section,string]>).map(([id,label])=><button key={id} type="button" className={section===id?'selected':''} onClick={()=>setSection(id)} aria-current={section===id?'page':undefined}>{label}</button>)}
    </nav>
    {!backendReady ? <div className="settings-loading" role="status">Conectando con el backend local…</div> : loading ? <div className="settings-loading" role="status">Cargando configuración existente…</div> : <>
      {section==='cuenta' && <div className="settings-grid">
        <CredentialCard provider="riot" configured={settings.riot_api_key_configured} value={riotKey} setValue={setRiotKey} busy={busy==='riot'} onSave={()=>void saveKey('riot')} onClear={()=>void clearKey('riot')}/>
        <CredentialCard provider="gemini" configured={settings.gemini_api_key_configured} value={geminiKey} setValue={setGeminiKey} busy={busy==='gemini'} onSave={()=>void saveKey('gemini')} onClear={()=>void clearKey('gemini')}/>
        <div className="settings-note"><strong>Privacidad de claves</strong><span>Las claves permanecen en settings.json del usuario. El renderer solo recibe el estado configurado; nunca vuelve a leer el secreto guardado.</span></div>
      </div>}
      {section==='grabacion' && <div className="settings-grid">
        <section className="settings-card settings-card-wide"><CardTitle eyebrow="CAPTURA LOCAL" title="Grabaciones" description="Las preferencias se guardan en la configuración compartida y se aplican a la próxima captura del motor de grabación."/>
          <ToggleRow title="Grabar cada partida automáticamente" description="Inicia y detiene la captura cuando comienza y termina una partida." checked={settings.recording_auto} onChange={(value)=>save({recording_auto:value})}/>
          <SelectRow title="Monitor de grabación" description="Pantalla alternativa cuando no se detecta League of Legends." value={String(settings.recording_monitor_index)} options={[['-1','Automático · monitor de League'],...displays.map((display)=>[String(display.index),`Monitor ${display.index+1} · ${display.width} × ${display.height}`] as [string,string])]} onChange={(value)=>save({recording_monitor_index:Number(value)})}/>
          <SelectRow title="Calidad de vídeo" value={settings.recording_quality} options={qualityOptions} onChange={(value)=>save({recording_quality:value})}/>
          <SelectRow title="Bitrate de vídeo" description="Un bitrate mayor conserva más detalle y ocupa más espacio." value={String(settings.recording_bitrate)} options={bitrateOptions.map(([value,label])=>[String(value),label])} onChange={(value)=>save({recording_bitrate:Number(value)})}/>
          <SelectRow title="Qué sonido se graba" description="La captura aislada de audio de League depende de loopback por proceso; el motor actual no lo ofrece." value={settings.recording_audio_mode} options={audioOptions} onChange={(value)=>save({recording_audio_mode:value})}/>
          <div className="settings-inline-actions"><button className="secondary-button" onClick={()=>void scanDevices()} disabled={busy==='devices'}>{busy==='devices'?'Buscando…':'Buscar dispositivos de audio'}</button><span>{devicesAvailable===undefined?'No se ha consultado FFmpeg todavía.':devicesAvailable?`${devices.length} dispositivo(s) disponible(s).`:'FFmpeg no disponible.'}</span></div>
          {devicesAvailable && <><SelectRow title="Micrófono" value={settings.recording_mic_device} options={ [['','Automático / ninguno'],...devices.map((device)=>[device,device] as [string,string])] } onChange={(value)=>save({recording_mic_device:value})}/><SelectRow title="Mezcla del sistema" description="Para Discord, YouTube y otras aplicaciones." value={settings.recording_system_audio_device || settings.recording_mic_capture_device} options={ [['','Automático / ninguno'],...devices.map((device)=>[device,device] as [string,string])] } onChange={(value)=>save({recording_system_audio_device:value,recording_mic_capture_device:value})}/></>}
          <div className="settings-folder"><div><small>CARPETA DE GRABACIONES</small><span title={settings.recording_output_dir}>{settings.recording_output_dir || 'Carpeta predeterminada de Solralol'}</span></div><button className="secondary-button" onClick={()=>void changeFolder()}>Cambiar</button><button className="secondary-button" onClick={()=>void window.solralol.openRecordingsDirectory().then((message)=>message&&setStatus({text:message,kind:'error'})).catch((error:Error)=>setStatus({text:error.message,kind:'error'}))}>Abrir</button></div>
          <RangeRow title="Límite de almacenamiento" description="Al superar el límite, el sistema conserva la grabación nueva y elimina las más antiguas." value={settings.recording_size_limit_gb} min={1} max={500} step={5} display={`${settings.recording_size_limit_gb} GB`} onChange={(value)=>save({recording_size_limit_gb:value})}/>
          <div className="settings-inline-actions"><button className="secondary-button" onClick={()=>void testRecording()} disabled={busy==='recording-test'}>{busy==='recording-test'?'Probando captura…':'Probar grabación'}</button><span>La prueba crea un clip temporal breve en la carpeta configurada.</span></div>
        </section>
        <div className="settings-note warning"><strong>Compatibilidad de captura</strong><span>La captura requiere un FFmpeg compatible y depende del codificador y los dispositivos disponibles en este equipo. El audio aislado por proceso de League no está disponible; micrófono y mezcla del sistema dependen de las fuentes seleccionadas.</span></div>
      </div>}
      {section==='overlays' && <div className="settings-grid settings-overlay-grid">
        <div className="settings-note warning settings-card-wide"><strong>Aplicación de los cambios</strong><span>Las ventanas usan el estado de partida del backend. Las vistas previas son ejemplos aislados. El HUD necesita calibración para alinear las habilidades.</span></div>
        <section className="settings-card settings-card-wide"><CardTitle eyebrow="PANELES DE PARTIDA" title="Overlays" description="Visibilidad, acceso con TAB, interacción, opacidad y escala por panel."/>
          <div className={`overlay-editor-controls${overlayEditing?' is-active':''}`}>
            <button className="secondary-button" type="button" onClick={()=>void window.solralol.setOverlayEditing(!overlayEditing).then(setOverlayEditing)}>{overlayEditing?'Finalizar colocación':'Colocar overlays'}</button>
            <label><span>Atajo de edición</span><select className="overlay-shortcut-select" value={settings.overlay_edit_shortcut??'Control+Alt+Shift+O'} onChange={event=>save({overlay_edit_shortcut:event.target.value})}>{['O','P','L','K'].map(key=><option key={key} value={`Control+Alt+Shift+${key}`}>{`Ctrl+Alt+Mayús+${key}`}</option>)}</select></label>
            <small>{overlayEditing?'Modo de edición activo. Arrastra los overlays y finaliza para guardar sus posiciones.':'Activa el modo de edición para mover los overlays, incluso sin una partida abierta.'}</small>
          </div>
          <div className="overlay-settings-grid">
            {(Object.entries(panelNames) as Array<[OverlayPanel,string]>).map(([panel,label])=><article className="overlay-settings-item" key={panel}>
              <h3>{label}</h3>
              <div className="overlay-preview-frame" aria-label={`Vista previa de ${label}`}>
                <div className="overlay-preview-content" style={{opacity:(settings.overlay_panel_opacity[panel]??92)/100,transform:`scale(${settings.overlay_panel_scales[panel]??1})`,width:panel==='ability'?3*(settings.overlay_ability_slot_spacing??47)+65:undefined}}>
                  <OverlayContent panel={panel} snapshot={overlayPreview} assets={previewAssets} slotSpacing={settings.overlay_ability_slot_spacing}/>
                </div>
              </div>
              <ToggleRow title="Overlay visible" checked={settings.overlay_panels[panel] ?? true} onChange={(value)=>updateMap('overlay_panels',panel,value)}/>
              {panel!=='ability'&&<ToggleRow title="Solo con TAB" checked={settings.overlay_tab_only[panel] ?? false} onChange={(value)=>updateMap('overlay_tab_only',panel,value)}/>}
              {panel!=='ability'&&panel!=='alerts'&&<ToggleRow title="Permitir clics al juego" description="Click-through del panel." checked={settings.overlay_panel_click_through[panel] ?? settings.overlay_click_through} onChange={(value)=>updateMap('overlay_panel_click_through',panel,value)}/>}
              {panel==='alerts'&&<p className="overlay-context-note">Las notificaciones dejan pasar los clics al juego y solo se pueden arrastrar en modo de colocación.</p>}
              {panel==='ability'&&<p className="overlay-context-note">Solo aparece con un punto pendiente y siempre deja pasar los clics al juego.</p>}
              <RangeRow title="Opacidad" value={settings.overlay_panel_opacity[panel] ?? 92} min={0} max={100} step={1} display={`${settings.overlay_panel_opacity[panel] ?? 92}%`} onChange={(value)=>updateNumberMap('overlay_panel_opacity',panel,value)}/>
              <RangeRow title="Tamaño" value={Math.round((settings.overlay_panel_scales[panel] ?? 1)*100)} min={50} max={150} step={1} display={`${Math.round((settings.overlay_panel_scales[panel] ?? 1)*100)}%`} onChange={(value)=>updateNumberMap('overlay_panel_scales',panel,value/100)}/>
              {panel==='ability'&&<div className="overlay-hud-controls">
                <RangeRow title="Ancla horizontal" value={Math.round((settings.overlay_ability_hud_anchor?.x??0.5)*100)} min={10} max={90} step={1} display={`${Math.round((settings.overlay_ability_hud_anchor?.x??0.5)*100)}%`} onChange={(value)=>save({overlay_ability_hud_anchor:{x:value/100,y:settings.overlay_ability_hud_anchor?.y??0.89}})}/>
                <RangeRow title="Ancla vertical" value={Math.round((settings.overlay_ability_hud_anchor?.y??0.89)*100)} min={60} max={98} step={1} display={`${Math.round((settings.overlay_ability_hud_anchor?.y??0.89)*100)}%`} onChange={(value)=>save({overlay_ability_hud_anchor:{x:settings.overlay_ability_hud_anchor?.x??0.5,y:value/100}})}/>
                <RangeRow title="Separación Q/W/E/R" value={settings.overlay_ability_slot_spacing??47} min={43} max={72} step={1} display={`${settings.overlay_ability_slot_spacing??47} px`} onChange={(value)=>save({overlay_ability_slot_spacing:value})}/>
              </div>}
              <button className="secondary-button" onClick={()=>{updateNumberMap('overlay_panel_scales',panel,1);if(panel==='ability')save({overlay_ability_hud_anchor:{x:0.5,y:0.89},overlay_ability_slot_spacing:47});}}>{panel==='ability'?'Restablecer posición y tamaño':'Restablecer tamaño'}</button>
            </article>)}
          </div>
          <div className="settings-inline-actions"><button className="secondary-button" onClick={()=>save({overlay_panels:Object.fromEntries(Object.keys(panelNames).map((key)=>[key,!Object.values(settings.overlay_panels).some(Boolean)]))})}>{Object.values(settings.overlay_panels).some(Boolean)?'Ocultar todos los overlays':'Mostrar todos los overlays'}</button><span>El modo TAB usa una sola lectura compartida. La pantalla completa exclusiva puede impedir mostrar ventanas externas.</span></div>
        </section>
        <section className="settings-card"><CardTitle eyebrow="AVISOS" title="Alertas" description="Duración de los avisos durante la partida; la vista previa muestra un ejemplo."/><SelectRow title="Duración del aviso" value={String(settings.overlay_alert_duration)} options={['3','5','8','10'].map((v)=>[v,`${v} segundos`] as [string,string])} onChange={(value)=>save({overlay_alert_duration:Number(value)})}/></section>
        <section className="settings-card"><CardTitle eyebrow="AUDIO" title="Sonidos de avisos" description="Preferencias de sonido guardadas en settings.json."/><ToggleRow title="Activar sonidos" checked={settings.overlay_sound_enabled} onChange={(value)=>save({overlay_sound_enabled:value})}/><RangeRow title="Volumen" value={Math.round(settings.overlay_sound_volume*100)} min={0} max={100} step={1} display={`${Math.round(settings.overlay_sound_volume*100)}%`} onChange={(value)=>save({overlay_sound_volume:value/100})}/><ToggleRow title="Objetivos" checked={settings.overlay_sound_objective} onChange={(value)=>save({overlay_sound_objective:value})}/><ToggleRow title="Dragón" checked={settings.overlay_sound_dragon} onChange={(value)=>save({overlay_sound_dragon:value})}/><ToggleRow title="Compras rivales" checked={settings.overlay_sound_enemy_buy} onChange={(value)=>save({overlay_sound_enemy_buy:value})}/></section>
      </div>}
      {section==='almacenamiento' && <div className="settings-grid">
        <section className="settings-card settings-card-wide"><CardTitle eyebrow="DATOS LOCALES" title="Almacenamiento" description="El directorio central contiene partidas, análisis, cachés, ajustes y recursos locales de Solralol."/>
          <div className="settings-folder storage-location"><div><small>DIRECTORIO DE DATOS</small><span title={storageInfo?.root}>{storageInfo?.root || 'Cargando ubicación…'}</span></div><button className="secondary-button" onClick={()=>void browseStorage()} disabled={busy==='storage'||busy==='storage-migration'}>Examinar</button><button className="secondary-button" onClick={()=>void openStorage()}>Abrir carpeta</button></div>
          {storageCandidate && <div className="storage-candidate">Destino seleccionado: <span>{storageCandidate}</span></div>}
          <div className="settings-inline-actions"><button className="gold-button" onClick={()=>void previewStorageChange()} disabled={busy==='storage'||busy==='storage-migration'}>Cambiar ubicación</button><button className="secondary-button" onClick={()=>{setStorageCandidate('');void previewStorageChange(storageInfo?.defaultRoot)}} disabled={!storageInfo||storageInfo.root===storageInfo.defaultRoot||busy==='storage'||busy==='storage-migration'}>Restaurar ubicación predeterminada</button><span>La nueva carpeta se usará después de copiar y verificar los datos.</span></div>
          {storageInfo && <div className="storage-usage"><strong>Espacio utilizado por Solralol</strong><div className="storage-usage-grid"><span>Total<strong>{formatStorageBytes(storageInfo.totalBytes)}</strong></span><span>Grabaciones<strong>{formatStorageBytes(storageInfo.categories.recordings||0)}</strong></span><span>Partidas y datos de Riot<strong>{formatStorageBytes(storageInfo.categories.matches||0)}</strong></span><span>Análisis<strong>{formatStorageBytes(storageInfo.categories.analysis||0)}</strong></span><span>Cachés<strong>{formatStorageBytes(storageInfo.categories.cache||0)}</strong></span><span>Otros datos<strong>{formatStorageBytes(storageInfo.categories.other||0)}</strong></span><span>Disponible en la unidad<strong>{formatStorageBytes(storageInfo.freeBytes)}</strong></span></div></div>}
          {storageMigration && ['preparing','validating','copying','verifying','committing','reinitializing'].includes(storageMigration.state) && <div className="storage-progress" role="status"><strong>Migrando datos · {storagePhaseLabel(storageMigration.phase || storageMigration.state)}</strong><span>{storageMigration.message || 'La migración continúa en segundo plano.'}</span>{storageMigration.state==='copying' && <progress max={Math.max(storageMigration.totalBytes,1)} value={storageMigration.currentBytes}/ >}{storageMigration.state==='verifying' && <progress max={Math.max(storageMigration.totalBytes,1)} value={storageMigration.verifiedBytes || 0}/>}<span>{storageMigration.state==='verifying'?'Verificados: '+formatStorageBytes(storageMigration.verifiedBytes || 0):'Copiados: '+formatStorageBytes(storageMigration.currentBytes)} de {formatStorageBytes(storageMigration.totalBytes)} · {storageMigration.processedFiles || 0}/{storageMigration.fileCount} archivos</span>{storageMigration.currentFile && <small title={storageMigration.currentFile}>Archivo: {storageMigration.currentFile}</small>}</div>}
          {storageMigration && ['complete','startup_verified'].includes(storageMigration.state) && <div className="storage-migration-result complete" role="status"><strong>Migración completada</strong><span>Solralol utiliza {storageMigration.result?.root || storageInfo?.root}.</span></div>}
          {storageMigration && ['failed','startup_failed','recovery_required','cancelled'].includes(storageMigration.state) && <div className="storage-migration-result failed" role="alert"><strong>No se pudo completar la migración</strong><span>{storageMigration.message} La carpeta original sigue disponible. Puedes seleccionar el destino y volver a intentarlo.</span>{storageMigration.stage && <small>La copia temporal se conserva para recuperación.</small>}</div>}
          {storageInfo && !storageInfo.available && <div className="settings-note warning"><strong>Ubicación no disponible</strong><span>No se puede acceder al directorio de datos configurado. Conecta la unidad o selecciona otra ubicación para recuperar el acceso.</span></div>}
        </section>
        <div className="settings-note settings-card-wide"><strong>Conservación de datos</strong><span>El cambio copia las partidas, análisis, grabaciones y configuración a una carpeta temporal del destino. Solralol verifica la copia antes de cambiar la ubicación. La carpeta anterior se conserva.</span></div>
      </div>}
      {section==='analisis' && <AnalysisSettingsPanel backendReady={backendReady}/>}
      {storagePreview && <div className="storage-modal-backdrop" role="presentation"><section className="storage-modal settings-card" role="dialog" aria-modal="true" aria-labelledby="storage-modal-title"><CardTitle eyebrow="TRASLADO DE DATOS" title="Cambiar ubicación de almacenamiento"/><div className="storage-modal-path"><small>UBICACIÓN ACTUAL</small><span>{storagePreview.source}</span></div><div className="storage-modal-path"><small>NUEVA UBICACIÓN</small><span>{storagePreview.destination}</span></div><div className="storage-modal-summary"><strong>Datos que se trasladarán</strong><span>Historial de partidas, análisis guardados, grabaciones, configuración, cachés y otros archivos de Solralol.</span><span>{formatStorageBytes(storagePreview.totalBytes)} · {storagePreview.fileCount} archivos</span><span>Espacio disponible en destino: {formatStorageBytes(storagePreview.availableBytes)}</span>{storagePreview.recordingActive && <span className="storage-warning">Hay una grabaci&oacute;n activa. Al confirmar, Solralol la finalizar&aacute; antes de cerrarse.</span>}</div><div className="settings-inline-actions"><button className="secondary-button" onClick={()=>setStoragePreview(undefined)}>Cancelar</button><button className="gold-button" onClick={()=>void migrateStorage()} disabled={busy==='storage-migration'}>Mover datos</button></div></section></div>}
      {status && <div className={`settings-status ${status.kind}`} role="status">{status.text}</div>}
      {busy==='save' && <span className="settings-saving" aria-live="polite">Guardando…</span>}
    </>}
  </div>;
}

function CredentialCard({provider,configured,value,setValue,busy,onSave,onClear}:{provider:Provider;configured:boolean;value:string;setValue:(value:string)=>void;busy:boolean;onSave:()=>void;onClear:()=>void}) {
  const riot=provider==='riot';
  return <section className="settings-card"><CardTitle eyebrow={riot?'RIOT GAMES':'GOOGLE AI STUDIO'} title={riot?'Riot API':'IA Gemini'} description={riot?'Clave oficial para sincronizar partidas, perfil y estadísticas de Riot.':'Clave para el reanálisis inteligente de builds, runas y recomendaciones.'}/><ol className="settings-instructions">{(riot?['Abre developer.riotgames.com e inicia sesión.','Genera una Development API Key. Caduca cada 24 horas.','Pega la clave RGAPI y compruébala.']:['Abre aistudio.google.com/apikey.','Crea una clave de API en un proyecto.','Pega la clave y compruébala.']).map((item)=><li key={item}>{item}</li>)}</ol><label className="settings-field"><span>CLAVE DE API</span><input type="password" autoComplete="off" spellCheck={false} value={value} onChange={(event)=>setValue(event.target.value)} placeholder={riot?'RGAPI-…':'AIzaSy…'} aria-label={`Clave ${riot?'Riot':'Gemini'} API`}/></label><div className="settings-inline-actions"><button className="gold-button" onClick={onSave} disabled={busy||!value.trim()}>{busy?'Comprobando…':'Guardar y comprobar'}</button><button className="secondary-button" onClick={onClear} disabled={busy||!configured}>Eliminar clave</button><button className="secondary-button" onClick={()=>void window.solralol.openSettingsUrl(provider)}>Abrir portal ↗</button></div><div className={`credential-status ${configured?'configured':'missing'}`}><i/>{configured?'Hay una clave guardada. El secreto no se muestra aquí.':'No hay una clave configurada.'}</div></section>;
}
function storagePhaseLabel(phase: string) {
  const labels: Record<string,string> = {preparing:'Preparando archivos',validating:'Validando destino',copying:'Copiando datos',verifying:'Verificando archivos',committing:'Aplicando nueva ubicación',reinitializing:'Finalizando'};
  return labels[phase] || 'Preparando archivos';
}
function formatStorageBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes < 0) return 'No disponible';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB','MB','GB','TB']; let value = bytes / 1024; let index = 0;
  while (value >= 1024 && index < units.length-1) { value /= 1024; index++; }
  return `${value.toLocaleString('es-ES',{maximumFractionDigits:1})} ${units[index]}`;
}
function CardTitle({eyebrow,title,description}:{eyebrow:string;title:string;description?:string}) { return <header className="settings-card-title"><span className="eyebrow">{eyebrow}</span><h2>{title}</h2>{description&&<p>{description}</p>}</header>; }
function ToggleRow({title,description,checked,onChange}:{title:string;description?:string;checked:boolean;onChange:(value:boolean)=>void}) { return <label className="settings-toggle-row"><span><strong>{title}</strong>{description&&<small>{description}</small>}</span><input type="checkbox" role="switch" checked={checked} onChange={(event)=>onChange(event.target.checked)}/></label>; }
function SelectRow({title,description,value,options,onChange}:{title:string;description?:string;value:string;options:Array<[string,string]>;onChange:(value:string)=>void}) { return <label className="settings-select-row"><span><strong>{title}</strong>{description&&<small>{description}</small>}</span><select value={value} onChange={(event)=>onChange(event.target.value)}>{options.map(([option,label])=><option key={option} value={option}>{label}</option>)}</select></label>; }
function RangeRow({title,description,value,min,max,step,display,onChange}:{title:string;description?:string;value:number;min:number;max:number;step:number;display:string;onChange:(value:number)=>void}) { return <label className="settings-range-row"><span><strong>{title}</strong>{description&&<small>{description}</small>}</span><input type="range" min={min} max={max} step={step} value={value} onChange={(event)=>onChange(Number(event.target.value))}/><output>{display}</output></label>; }
