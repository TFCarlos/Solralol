"""Estilos Qt del análisis y shell generados con la paleta del logo."""

from string import Template

from _paths import DATA_DIR
from app.ui.sistema_visual import PALETA, RADIO_TARJETA

ESTILO_ANALISIS = Template("""
QDialog#localAnalysisDialog, QDialog#analysisPage {background:transparent; color:$texto;}
QWidget {font-family:"Segoe UI"; font-size:13px; color:$texto;}
QWidget#localAnalysisView {background:transparent;}
QLabel {background:transparent; border:none;}
QLabel#localCaption {color:$secundario; font-size:11px; font-weight:600; letter-spacing:1px;}
QLabel#localSectionTitle, QLabel#localInsightTitle {color:$oro_suave; font-size:13px; font-weight:700; letter-spacing:1px;}
QLabel#localMuted, QLabel#localChampionMeta {color:$secundario; font-size:13px;}
QLabel#localChampionTitle {color:$texto; font-size:30px; font-weight:800; letter-spacing:1px;}
QLabel#localChampionSubtitle {color:$marfil; font-size:15px;}
QLabel#localChampionStat {color:$marfil; font-size:18px; font-weight:700;}
QLabel#localStatCaption {color:$secundario; font-size:11px;}
QLabel#localChampionBadge, QLabel#localStyleValue {color:$oro_suave; background:$calida; border:1px solid $oro_oscuro; border-radius:6px; padding:6px 10px; font-weight:600;}
QLabel#localChampionSampleBadge {color:$marfil; background:#28251d; border:1px solid $oro_oscuro; border-radius:6px; padding:6px 10px; font-weight:600;}
QLabel#localChampionPortrait {background:$base; border:1px solid $oro; border-radius:14px;}
QLabel#localRuneSummary {color:$secundario; font-size:12px;}
QLabel#winrateProgressLabel {color:$secundario; font-size:12px;}
QWidget#updateStatusSlot {background:transparent; border:none;}
QFrame#localFilters {background:rgba(25,32,42,190); border:1px solid $borde; border-radius:12px;}
QFrame#localRunePanel, QFrame#buildCard, QFrame#situationalCard, QFrame#localMatchupsPanel, QFrame#localChartCard, QFrame#localDamageCard, QFrame#localRecommendationsPanel {
 background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 $elevada,stop:1 $superficie);
 border:1px solid $borde; border-top:1px solid $oro_oscuro; border-radius:${radio_tarjeta}px;
}
QFrame#localInsightPanel, QFrame#localSkillOrderPanel {background:rgba(16,21,30,220); border:1px solid $borde; border-radius:12px;}
QFrame#summonersCard, QFrame#startersCard, QFrame#coreOverviewCard {background:rgba(25,32,42,180); border:1px solid $oro_oscuro; border-radius:12px;}
QFrame#localRunePage {background:rgba(5,7,12,95); border:1px solid $borde; border-radius:12px;}
QFrame#localRunePage:hover {background:rgba(84,67,38,65); border-color:$oro;}
QFrame#localRunePage[selected="true"] {background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #30291d,stop:1 $superficie); border:1px solid $oro; border-left:3px solid $oro;}
QFrame#localRunePageEmpty {background:transparent; border:1px dashed $borde; border-radius:12px;}
QLabel#localRunePageTitle {color:$texto; font-size:14px; font-weight:600;}
QLabel#localRuneTreeHeading {color:$marfil; font-size:13px; font-weight:600;}
QLabel#localRuneSectionLabel {color:$tenue; font-size:10px; letter-spacing:0.7px;}
QLabel#localRuneWrBadge {color:$ventaja; background:#192a25; border-radius:5px; padding:5px 8px; font-size:12px;}
QLabel#localRuneGamesBadge {color:$secundario; font-size:11px; padding:4px;}
QFrame#localRuneDivider, QFrame#localRuneVDivider {background:$borde; border:none;}
QFrame#localRuneDivider {max-height:1px;} QFrame#localRuneVDivider {max-width:1px;}
QLabel#localRuneKeystoneIcon {background:$calida; border:1px solid $oro; border-radius:25px;}
QLabel#localRuneNormalIcon {background:$base; border:1px solid $oro_oscuro; border-radius:21px;}
QLabel#localRuneShardIcon {background:$superficie; color:$marfil; border:1px solid $borde; border-radius:${radio_tarjeta}px;}
QLabel#localRuneEmptyTitle {color:$secundario; font-size:14px;}
QLabel#localRuneEmptySubtext {color:$tenue; font-size:12px;}
QLabel#localSkillOrderPriority {color:$oro_suave; font-size:12px; font-weight:600;}
QLabel#localSkillOrderLevel {color:$tenue; font-size:10px;}
QLabel#localSkillOrderRow {background:transparent;}
QLabel#localSkillOrderCell {background:$base; border:1px solid #252e38; border-radius:4px;}
QLabel#localSkillOrderCellActive {background:$oro_oscuro; border:1px solid $oro; border-radius:4px;}
QLabel#localItemIcon {background:$base; border:1px solid $oro_oscuro; border-radius:8px;}
QLabel#localItemName {color:$texto; font-size:13px;}
QWidget#localItemRow {background:transparent; border:none;}
QWidget#localItemRow:hover {background:rgba(182,154,80,16); border-radius:8px;}
QFrame#matchupCardCounter, QFrame#matchupCardGood {background:transparent; border:none; border-bottom:1px solid $borde; border-radius:0;}
QFrame#matchupCardCounter:hover, QFrame#matchupCardGood:hover {background:rgba(182,154,80,12);}
QLabel#matchupChampName {color:$texto; font-size:13px; font-weight:600;}
QLabel#matchupCountersHeader, QLabel#matchupWrCounter {color:$desventaja;}
QLabel#matchupGoodHeader, QLabel#matchupWrGood {color:$ventaja;}
QLabel#matchupGamesSub, QLabel#matchupOverallWr {color:$tenue; font-size:11px;}
QTabWidget#localAnalysisTabs::pane {background:transparent; border:none;}
""").substitute(
    **PALETA,
    flecha=(DATA_DIR / "ui" / "flecha_selector.svg").as_posix(),
    radio_tarjeta=RADIO_TARJETA,
)

ESTILO_SHELL = Template("""
QMainWindow {color:$texto; font-family:"Segoe UI";}
QLabel#brandSubtitle {color:$secundario; font-size:12px;}
QLabel#connectionLabel {color:$oro_suave; font-size:12px;}
QPushButton#closeButton {background:transparent; color:$secundario; border:1px solid $borde; border-radius:8px;}
QPushButton#closeButton:hover {color:$marfil; border-color:$oro; background:$calida;}
""").substitute(PALETA, radio_tarjeta=RADIO_TARJETA)

ESTILO_BARRA = Template("""
QFrame#barraLateral {background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #201b15,stop:0.5 $superficie,stop:1 #090c13); border:1px solid $borde; border-right:1px solid $oro_oscuro; border-radius:${radio_tarjeta}px;}
QLabel#marcaLateral {background:transparent; color:$marfil; font-family:"Segoe UI"; font-size:20px; font-weight:800; letter-spacing:1px;}
QLabel#logoLateral {background:transparent; border:none;}
QLabel#categoriaLateral {color:$tenue; font-size:10px; letter-spacing:2px; padding:8px 10px;}
QFrame#separadorLateral {background:$oro_oscuro; border:none; max-height:1px;}
QPushButton#destinoLateral {min-width:0; min-height:34px; padding:10px 9px; text-align:left; color:$secundario; background:transparent; border:none; border-left:3px solid transparent; border-radius:9px; font-size:13px; font-weight:500;}
QPushButton#destinoLateral:hover {background:rgba(182,154,80,18); color:$marfil;}
QPushButton#destinoLateral:checked {background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #382f20,stop:1 #171b21); border-left:3px solid $oro; color:$marfil; font-weight:600;}
QPushButton#destinoLateral:focus {background:#322b20;}
QPushButton#destinoLateral:disabled {color:$tenue; background:transparent;}
QPushButton#controlBarra {min-width:0; min-height:30px; padding:9px; background:#191b1e; color:$oro_suave; border:1px solid $oro_oscuro; border-radius:9px; font-size:12px;}
QPushButton#controlBarra:hover {background:#342c1e; border-color:$oro; color:$marfil;}
QPushButton#controlBarra:pressed {background:$calida;}
QPushButton#controlBarra:focus {border-color:$oro;}
""").substitute(PALETA, radio_tarjeta=RADIO_TARJETA)
