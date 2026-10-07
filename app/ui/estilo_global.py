"""Hoja única de controles, superficies y estados para toda la aplicación Qt."""

from string import Template

from _paths import DATA_DIR
from app.ui.sistema_visual import PALETA, RADIOS, TIPOGRAFIA

ESTILO_GLOBAL = Template("""
QWidget {font-family:"Segoe UI"; font-size:${cuerpo}px; color:$texto;}
QLabel {background:transparent; border:none;}
QMainWindow, QDialog, QWidget[superficie="ventana"] {
 background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 $calida,stop:0.45 $base,stop:1 $superficie);
}
QScrollArea, QStackedWidget {background:transparent; border:none;}
QScrollArea > QWidget > QWidget {background:transparent;}
QWidget[superficie="transparente"] {background:transparent; border:none;}
QFrame[superficie="tarjeta"], QWidget[superficie="tarjeta"], QGroupBox {
 background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 $elevada,stop:1 $superficie);
 border:1px solid $borde; border-top-color:$oro_oscuro; border-radius:${tarjeta}px;
}
QFrame[superficie="compacta"], QWidget[superficie="compacta"] {
 background:$superficie; border:1px solid $oro_oscuro; border-radius:${compacto}px;
}
QFrame[superficie="interactiva"] {background:$superficie; border:1px solid $borde; border-radius:${compacto}px;}
QFrame[superficie="interactiva"]:hover {background:$hover; border-color:$oro;}
QFrame#situationalCategory {background:$elevada; border:1px solid $borde_sutil; border-radius:${compacto}px;}
QFrame#situationalCategoryDivider {background:$borde_sutil; border:none;}
QWidget#situationalItemRow {background:transparent; border:none;}
QLabel#situationalItemName {color:$texto; font-size:${metadatos}px;}
QWidget[superficie="destacada"] {background:$activo; border:1px solid $oro; border-radius:${tarjeta}px;}
QWidget[superficie="separador"] {background:$borde; border:none;}
QFrame[superficie="separador"][estado="exito"] {background:$ventaja;}
QFrame[superficie="separador"][estado="error"] {background:$desventaja;}
QFrame[superficie="separador"][estado="informacion"] {background:$teal;}
QFrame[superficie="separador"][estado="advertencia"] {background:$oro;}
QFrame[seleccionado="true"] {border:1px solid $oro; border-left:3px solid $oro;}
QFrame[estado="exito"] {border-left:2px solid $ventaja;}
QFrame[estado="error"] {border-left:2px solid $desventaja;}
QFrame#draftBanSlot {background:$base; border:1px solid $borde; border-radius:${compacto}px;}
QFrame#draftBanSlot[equipo="aliado"] {border-color:$teal;}
QFrame#draftBanSlot[equipo="enemigo"] {border-color:$desventaja;}
QFrame#draftBanSlot[ocupado="true"] {background:$superficie; border-color:$oro_oscuro;}
QFrame#draftBanSeparator {background:$borde; border:none;}
QFrame#cardLoadout {background:transparent; border:none;}
QFrame#cardCombatStats {background:rgba(16,21,30,150); border:1px solid $borde_sutil; border-radius:${pequeno}px;}
QFrame#cardLoadoutDivider {background:$borde_sutil; border:none;}
QLabel#cardChampionIcon {background:$base; border:1px solid $borde; border-radius:${pequeno}px;}
QLabel#cardSpellIcon {background:$base; border:1px solid $borde_sutil; border-radius:${pequeno}px; color:$oro_suave; font-weight:700; padding:0px;}
QLabel#cardSpellIcon[missing="true"] {background:$elevada; border:1px dashed $oro_oscuro; color:$oro_suave; font-size:${metadatos}px;}
QLabel#cardChampionName {color:$marfil; font-size:${cuerpo}px; font-weight:700;}
QLabel#cardPlayerId {color:$secundario; font-size:${cuerpo}px;}
QLabel#cardRoleChip {color:$oro_suave; background:$calida; border:1px solid $oro_oscuro; border-radius:${pequeno}px; padding:1px 5px; font-size:${metadatos}px; font-weight:600;}
QLabel#cardLevelBadge {color:$oro_suave; font-size:${nivel_live_estandar}px; font-weight:600; padding:1px 4px; background:$calida; border:1px solid $oro_oscuro; border-radius:${pequeno}px; min-width:0px;}
QLabel#cardLevelBadge[densidad="compacta"] {font-size:${nivel_live_compacto}px;}
QLabel#cardLevelBadge[densidad="estandar"] {font-size:${nivel_live_estandar}px;}
QLabel#cardLevelBadge[densidad="amplia"] {font-size:${nivel_live_amplio}px;}
QLabel#cardKDA {min-width:70px; color:$marfil; font-size:${cuerpo}px; font-weight:700;}
QLabel#cardMeBadge {color:$oro_suave; background:$calida; border:1px solid $oro; border-radius:${pequeno}px; padding:2px 5px; font-size:${metadatos}px; font-weight:700;}
QLabel#cardCombatValue {color:$texto; font-size:12px;}
QLabel#cardInventoryTitle, QLabel#cardInventoryCount {color:$secundario; font-size:${metadatos}px;}
QLabel#cardRuneKeystoneIcon {background:$calida; border:1px solid $oro; border-radius:${pequeno}px; color:$oro_suave; padding:0px;}
QLabel#cardRuneIcon {background:$base; border:1px solid $borde_sutil; border-radius:${pequeno}px; color:$secundario; padding:0px;}
QLabel#cardLoadoutEmpty {color:$tenue; font-size:${metadatos}px;}
QLabel#itemSlot, QLabel#trinketSlot, QLabel#bootsQuestSlot, QLabel#pinkWardQuestSlot {background:$base; border:1px solid $borde_sutil; border-radius:${pequeno}px;}
QFrame#savedGameRow {background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 $elevada,stop:1 $superficie); border:1px solid $borde; border-top:1px solid $oro_oscuro; border-radius:${tarjeta}px;}
QFrame#savedGameRow[result="win"] {border-left:3px solid $ventaja;}
QFrame#savedGameRow[result="loss"] {border-left:3px solid $desventaja;}
QLabel#savedGameChampIcon {background:$base; border:1px solid $oro; border-radius:12px;}
QLabel#savedGameEnemyIcon {background:$base; border:1px solid $desventaja; border-radius:6px;}
QLabel#savedGameMatchup {color:$oro_suave; font-size:13px; font-weight:600;}
QLabel#savedGameResult[result="win"] {color:$ventaja; font-weight:700; font-size:13px;}
QLabel#savedGameResult[result="loss"] {color:$desventaja; font-weight:700; font-size:13px;}
QLabel#savedGameResult[result="unknown"] {color:$secundario; font-weight:600; font-size:13px;}
QLabel#homeAnalyzableBadge {color:$oro_suave; font-weight:700; border:1px solid $oro_oscuro; border-radius:6px; padding:3px 6px;}
QPushButton#homeAnalyzableBadge {color:$oro_suave; font-weight:700; border:1px solid $oro_oscuro; border-radius:6px; padding:3px 6px; background:transparent;}
QPushButton#homeAnalyzableBadge:hover {color:$marfil; border-color:$oro; background:rgba(182,154,80,24);}
QPushButton#homeAnalyzableBadge:disabled {color:$secundario; border-color:$borde_sutil;}
QLabel#homeHeatmapCell {background:$superficie; color:$secundario; border:1px solid $borde_sutil; border-radius:6px;}
QLabel#homeHeatmapCell[intensity="1"] {background:$calida; color:$secundario;}
QLabel#homeHeatmapCell[intensity="2"] {background:$oro_oscuro; color:$marfil;}
QLabel#homeHeatmapCell[intensity="3"] {background:$oro; color:$base;}
QLabel#homeHeatmapCell[intensity="4"] {background:$oro_suave; color:$base;}
QProgressBar#homeAnalyticsBar {min-height:10px; max-height:10px; background:$base; border:1px solid $borde_sutil; border-radius:5px; text-align:center;}
QProgressBar#homeAnalyticsBar::chunk {background:$oro; border-radius:4px;}
QLabel#homePlaystylePrimary {color:$marfil; font-size:${seccion}px; font-weight:800;}
QLabel#homeSubheading {color:$oro_suave; font-size:${metadatos}px; font-weight:700; padding-top:4px;}
QLabel#homeModeChip {color:$marfil; background:$superficie; border:1px solid $borde_sutil; border-radius:8px; padding:3px 7px;}
QLabel#homeBarLabel, QLabel#homeCompactText {color:$secundario; font-size:${metadatos}px;}
QLabel#homeKda {color:$marfil; font-weight:700;}
QScrollArea#homeHistoryScroll {background:transparent; border:none;}
QFrame#homeTeammateRow, QFrame#homeMatchupRow {background:$elevada; border:1px solid $borde_sutil; border-radius:9px;}
QFrame#homeTeammateAvatar, QFrame#homeMasteryIconFrame {background:$base; border:1px solid $oro_oscuro; border-radius:12px;}
QLabel#homeTeammateAvatarImage {background:transparent; border:none; border-radius:8px; color:$oro_suave;}
QLabel#homeTeammateName, QLabel#homeMatchupName {color:$marfil; font-weight:600;}
QLabel#homeOpponentName {color:$marfil;}
QLabel#homeOpponentUnknown {color:$secundario; font-weight:700;}
QLabel#homeEnemyTeamOverflow {color:$oro_suave; background:$superficie; border:1px solid $borde_sutil; border-radius:7px; padding:3px 5px; font-weight:700;}
QLabel#savedGameMatchup[state="probable"] {color:$oro_suave;}
QLabel#homeTeammateMeta, QLabel#homeCoverage {color:$secundario; font-size:${metadatos}px;}
QLabel#homeTeammateWinrate {color:$marfil; font-weight:800; font-size:${metadatos}px;}
QLabel#homeTeammateDelta[sentiment="positive"] {color:$ventaja;}
QLabel#homeTeammateDelta[sentiment="negative"] {color:$desventaja;}
QLabel#homeTeammateDelta[sentiment="neutral"] {color:$secundario;}
QLabel#homeDuoBadge {color:$oro_suave; background:$calida; border:1px solid $oro_oscuro; border-radius:6px; padding:2px 5px; font-size:10px; font-weight:700;}
QLabel#homeMatchupWinrate {color:$secundario; background:$superficie; border:1px solid $borde_sutil; border-radius:7px; padding:4px 6px; font-weight:700;}
QLabel#homeMatchupWinrate[result="hard"] {color:$desventaja; background:rgba(129,58,58,35); border-color:rgba(129,58,58,90);}
QLabel#homeMatchupWinrate[result="favorable"] {color:$ventaja; background:rgba(45,105,81,35); border-color:rgba(45,105,81,90);}
QWidget#homeMatchupsHost {background:transparent;}
QWidget#homeMatchupGroup {background:transparent;}
QLabel#homeMasteryName {color:$marfil; font-size:${metadatos}px; font-weight:600;}
QLabel#homeMasteryPoints, QLabel#homeCollectionLabel {color:$secundario; font-size:${metadatos}px;}
QLabel#homeCollectionMetric {color:$marfil; font-weight:800;}
QProgressBar#homeCollectionProgress {background:$base; border:1px solid $borde_sutil; border-radius:4px;}
QProgressBar#homeCollectionProgress::chunk {background:$oro; border-radius:3px;}
QFrame#homeCollectionSeparator {color:$borde_sutil; max-height:1px;}
QLabel#homeChallengeTier {color:$oro_suave; background:$calida; border:1px solid $oro_oscuro; border-radius:7px; padding:3px 7px; font-weight:700;}
QLabel#homeActiveTitle {color:$marfil; background:$elevada; border:1px solid $borde_sutil; border-radius:7px; padding:5px 8px; font-weight:600;}
QLabel[result="victory"], QLabel[state="ready"] {color:$ventaja;}
QLabel[result="defeat"], QLabel[state="error"] {color:$desventaja;}
QLabel[state="loading"] {color:$oro_suave;}
QLabel#liveDot {background:$tenue; border-radius:4px;}
QLabel#liveDot[state="live"] {background:$ventaja;}
QGroupBox {margin-top:18px; padding:20px;}
QGroupBox::title {subcontrol-origin:margin; left:20px; padding:0 6px; color:$oro_suave; font-weight:600;}
QLabel[nivel="aplicacion"] {font-size:${aplicacion}px; color:$marfil; font-weight:800;}
QLabel[nivel="pagina"] {font-size:${pagina}px; color:$marfil; font-weight:700;}
QLabel[nivel="seccion"] {font-size:${seccion}px; color:$oro_suave; font-weight:600;}
QLabel[nivel="tarjeta"] {font-size:${titulo_tarjeta}px; color:$marfil; font-weight:600;}
QLabel[nivel="metrica"] {font-size:${metrica}px; color:$marfil; font-weight:700;}
QLabel[nivel="etiqueta"] {font-size:${etiqueta}px; color:$oro_suave; font-weight:600;}
QLabel[nivel="metadatos"], QLabel[nivel="ayuda"] {font-size:${metadatos}px; color:$secundario;}
QLabel[nivel="estado"] {font-size:${estado}px; color:$secundario; padding:8px 12px; background:$superficie; border:1px solid $borde; border-radius:${control}px;}
QLabel[nivel="badge"] {font-size:${badge}px; color:$oro_suave; padding:4px 8px; background:$calida; border:1px solid $oro_oscuro; border-radius:${pequeno}px;}
QLabel[estado="exito"] {color:$ventaja; border:none;}
QLabel[estado="error"] {color:$desventaja; border:none;}
QLabel[estado="advertencia"] {color:$advertencia; border:none;}
QLabel[estado="informacion"] {color:$informacion; border:none;}
QLabel[estado="cargando"] {color:$oro_suave; border:none;}
QLabel[nivel="estado"] {border:1px solid $borde; border-radius:${control}px;}
QLabel[nivel="badge"] {border:1px solid $oro_oscuro; border-radius:${pequeno}px;}
QLabel:disabled {color:$texto_deshabilitado;}
QAbstractButton {outline:none;}
QPushButton, QToolButton {
 min-height:24px; padding:6px 12px; background:$superficie; color:$oro_suave;
 border:1px solid $oro_oscuro; border-radius:${control}px; font-weight:600;
}
QPushButton:hover, QToolButton:hover {background:$hover; border-color:$oro; color:$marfil;}
QPushButton:pressed, QToolButton:pressed {background:$calida; border-color:$oro_suave;}
QPushButton:focus, QToolButton:focus {border:2px solid $oro_suave; padding:5px 11px;}
QPushButton:checked, QToolButton:checked {background:$activo; border-color:$oro; color:$marfil;}
QPushButton[variante="primaria"], QPushButton#primaryButton {background:$activo; border-color:$oro; color:$marfil;}
QPushButton[variante="primaria"]:hover, QPushButton#primaryButton:hover {background:$hover; border-color:$oro_suave;}
QPushButton[variante="fantasma"], QToolButton[variante="fantasma"] {background:transparent; border-color:transparent;}
QPushButton[variante="fantasma"]:hover, QToolButton[variante="fantasma"]:hover {background:$hover; border-color:$oro_oscuro;}
QPushButton[variante="peligro"], QPushButton#dangerButton {color:$desventaja; border-color:$desventaja;}
QPushButton[variante="peligro"]:hover, QPushButton#dangerButton:hover {background:$calida; border-color:$desventaja;}
QPushButton[variante="icono"], QToolButton[variante="icono"] {min-width:24px; min-height:24px; padding:6px;}
QPushButton[estado="exito"] {color:$ventaja; border-color:$ventaja;}
QPushButton[estado="exito"]:hover {background:$hover; border-color:$ventaja;}
QPushButton[estado="error"] {color:$desventaja; border-color:$desventaja;}
QPushButton[estado="error"]:hover {background:$calida; border-color:$desventaja;}
QPushButton[cargando="true"], QToolButton[cargando="true"] {color:$oro_suave; background:$calida; border-style:dashed;}
QPushButton:disabled, QToolButton:disabled {background:$deshabilitado; color:$texto_deshabilitado; border-color:$borde_sutil;}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {
 min-height:28px; padding:5px 12px; background:$superficie; color:$texto;
 border:1px solid $borde; border-radius:${control}px; selection-background-color:$oro_oscuro; selection-color:$marfil;
}
QComboBox {padding-right:34px;}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {border-color:$oro_oscuro;}
QComboBox:focus, QComboBox:on, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {border:1px solid $oro; background:$hover;}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {background:$deshabilitado; color:$texto_deshabilitado; border-color:$borde_sutil;}
QComboBox[estado="error"], QLineEdit[estado="error"], QTextEdit[estado="error"] {border-color:$desventaja;}
QComboBox[cargando="true"] {border-color:$oro; border-style:dashed;}
QComboBox::drop-down {subcontrol-origin:padding; subcontrol-position:top right; width:28px; border:none; background:transparent;}
QComboBox::down-arrow {image:url("$flecha"); width:12px; height:8px;}
QComboBox QAbstractItemView {background:$superficie; color:$texto; border:1px solid $oro_oscuro; padding:6px; outline:none; selection-background-color:$activo; selection-color:$marfil;}
QComboBox QAbstractItemView::item {min-height:30px; padding:4px 10px;}
QComboBox QAbstractItemView::item:hover {background:$hover;}
QSpinBox::up-button, QDoubleSpinBox::up-button {subcontrol-position:top right; width:22px; border:none; background:$elevada;}
QSpinBox::down-button, QDoubleSpinBox::down-button {subcontrol-position:bottom right; width:22px; border:none; background:$elevada;}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {image:url("$arriba"); width:10px; height:7px;}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {image:url("$flecha"); width:10px; height:7px;}
QTextEdit, QPlainTextEdit, QTextBrowser {background:$superficie; color:$texto; border:1px solid $borde; border-radius:${control}px; padding:12px; selection-background-color:$oro_oscuro; selection-color:$marfil;}
QTextEdit:disabled, QPlainTextEdit:disabled {color:$texto_deshabilitado; background:$deshabilitado;}
QCheckBox, QRadioButton {spacing:8px; min-height:30px; background:transparent;}
QCheckBox::indicator, QRadioButton::indicator {width:18px; height:18px; background:$base; border:1px solid $secundario; border-radius:4px;}
QRadioButton::indicator {border-radius:10px;}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {border-color:$oro; background:$hover;}
QCheckBox::indicator:checked {background:$activo; border-color:$oro; image:url("$marca");}
QCheckBox::indicator:indeterminate {background:$oro_oscuro; image:url("$menos");}
QRadioButton::indicator:checked {background:$activo; border:2px solid $oro; image:url("$punto");}
QCheckBox:focus, QRadioButton:focus {color:$marfil; background:$hover; border:1px solid $oro_oscuro; border-radius:4px;}
QCheckBox:disabled, QRadioButton:disabled {color:$texto_deshabilitado;}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {background:$deshabilitado; border-color:$borde;}
QCheckBox[interruptor="true"]::indicator {width:36px; height:20px; border-radius:10px; image:url("$switch_off");}
QCheckBox[interruptor="true"]::indicator:checked {background:$oro_oscuro; image:url("$switch_on");}
QSlider {min-height:28px; background:transparent;}
QSlider::groove:horizontal {height:6px; background:$borde; border-radius:3px;}
QSlider::sub-page:horizontal {background:$oro; border-radius:3px;}
QSlider::add-page:horizontal {background:$borde; border-radius:3px;}
QSlider::handle:horizontal {width:16px; margin:-6px 0; border-radius:8px; background:$marfil; border:2px solid $oro;}
QSlider::handle:horizontal:hover, QSlider::handle:horizontal:pressed {background:$oro_suave; border-color:$marfil;}
QSlider::handle:horizontal:focus {border-color:$marfil;}
QSlider::groove:vertical {width:6px; background:$borde; border-radius:3px;}
QSlider::add-page:vertical {background:$oro;}
QSlider::handle:vertical {height:16px; margin:0 -6px; border-radius:8px; background:$marfil; border:2px solid $oro;}
QSlider::handle:vertical:hover, QSlider::handle:vertical:pressed {background:$oro_suave;}
QSlider:focus {background:$hover; border-radius:${control}px;}
QSlider::handle:disabled {background:$texto_deshabilitado; border-color:$borde;}
QSlider::sub-page:disabled, QSlider::add-page:vertical:disabled {background:$tenue;}
QScrollBar:vertical {background:transparent; width:10px; margin:2px;}
QScrollBar:horizontal {background:transparent; height:10px; margin:2px;}
QScrollBar::handle:vertical {background:$oro_oscuro; min-height:36px; border-radius:3px;}
QScrollBar::handle:horizontal {background:$oro_oscuro; min-width:36px; border-radius:3px;}
QScrollBar::handle:hover, QScrollBar::handle:pressed {background:$oro;}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {width:0;}
QScrollBar::add-page, QScrollBar::sub-page {background:transparent;}
QScrollBar:disabled {background:$deshabilitado;}
QTabWidget::pane {background:transparent; border:1px solid $borde; border-radius:${control}px; top:-1px;}
QTabBar::tab {background:transparent; color:$secundario; padding:12px 18px; border:none; border-bottom:2px solid transparent;}
QTabBar::tab:hover {background:$hover; color:$marfil;}
QTabBar::tab:selected {background:$activo; color:$marfil; border-bottom-color:$oro; font-weight:600;}
QTabBar::tab:disabled {color:$texto_deshabilitado;}
QTabBar:focus {border:1px solid $oro_oscuro;}
QTableView, QListView, QTreeView {background:$superficie; alternate-background-color:$elevada; color:$texto; border:1px solid $borde; border-radius:${control}px; padding:6px; gridline-color:$borde_sutil; outline:none; selection-background-color:$activo; selection-color:$marfil;}
QTableView::item, QListView::item, QTreeView::item {padding:6px; border:none;}
QListView::item, QTreeView::item {min-height:28px;}
QTableView::item:hover, QListView::item:hover, QTreeView::item:hover {background:$hover;}
QTableView::item:selected, QListView::item:selected, QTreeView::item:selected {background:$activo; color:$marfil;}
QTableView:focus, QListView:focus, QTreeView:focus {border-color:$oro;}
QHeaderView::section, QTableCornerButton::section {background:$elevada; color:$oro_suave; border:none; border-bottom:1px solid $oro_oscuro; padding:10px; font-weight:600;}
QHeaderView::section:hover {background:$hover;}
QHeaderView::up-arrow {image:url("$arriba"); width:10px; height:7px;}
QHeaderView::down-arrow {image:url("$flecha"); width:10px; height:7px;}
QProgressBar {min-height:12px; background:$base; border:1px solid $borde; border-radius:6px; text-align:center; color:$marfil;}
QProgressBar::chunk {background:$oro; border-radius:5px;}
QProgressBar:disabled {color:$texto_deshabilitado; background:$deshabilitado;}
QToolTip {background:$elevada; color:$marfil; font-size:${tooltip}px; border:1px solid $oro_oscuro; padding:8px;}
QMenu, QMenuBar {background:$superficie; color:$texto; border:1px solid $oro_oscuro; padding:6px;}
QMenu::item {padding:8px 24px; border-radius:4px;}
QMenu::item:selected, QMenuBar::item:selected {background:$activo; color:$marfil;}
QMenu::item:disabled {color:$texto_deshabilitado;}
QMenu::separator {height:1px; background:$borde; margin:6px;}
QStatusBar {background:$superficie; color:$secundario; padding:6px; border-top:1px solid $borde;}
QStatusBar::item {border:none;}
QSplitter::handle {background:$borde_sutil; width:6px; height:6px;}
QSplitter::handle:hover {background:$oro_oscuro;}
QToolBar {background:$superficie; border:none; padding:6px; spacing:6px;}
QMessageBox, QFileDialog, QInputDialog {background:$superficie;}
QMessageBox QLabel {min-width:180px;}
QWidget#startupWindow {border:1px solid $oro_oscuro; border-radius:${modal}px;}
QLabel#emptyItemSlot {background:rgba(5,7,12,100); border:1px dashed $borde_sutil; border-radius:${pequeno}px;}
QWidget#recordingVideo, QWidget#postgameVideo {background:$base;}
QFrame#overlayCard {background:$superficie; border:1px solid $oro_oscuro; border-radius:${compacto}px;}
""").substitute(
    **PALETA,
    **RADIOS,
    **{clave: valor for clave, valor in TIPOGRAFIA.items() if clave != "tarjeta"},
    titulo_tarjeta=TIPOGRAFIA["tarjeta"],
    **{
        nombre: (DATA_DIR / "ui" / archivo).as_posix()
        for nombre, archivo in {
            "flecha": "flecha_selector.svg",
            "arriba": "flecha_arriba.svg",
            "marca": "marca.svg",
            "menos": "menos.svg",
            "punto": "punto.svg",
            "switch_off": "switch_off.svg",
            "switch_on": "switch_on.svg",
        }.items()
    },
)
