from __future__ import annotations


CONTROL_WINDOW_STYLE = """
QMainWindow,
QWidget#mainPages,
QWidget#centralWidget,
QWidget#livePage,
QWidget#homePage,
QWidget#settingsPage,
QWidget#recordingsPage,
QWidget#cardsWidget {
    background: transparent;
    color: #e8f0ff;
    font-family: "Segoe UI";
}

QLabel {
    color: #e8f0ff;
}

QLabel#brandMark {
    background: #d9ae4f;
    border-radius: 6px;
}

QLabel#emptyItemSlot {
    background: rgba(5, 12, 24, 175);
    border: 1px dashed rgba(128, 167, 215, 110);
    border-radius: 7px;
}

QLabel#championName {
    color: #f4f7ff;
    font-size: 18px;
    font-weight: 800;
}

QLabel#playerId {
    color: #9caec9;
    font-size: 10px;
}

QLabel#levelLabel {
    min-width: 48px;
    min-height: 28px;
    padding: 3px 7px;
    border: 1px solid rgba(120, 170, 225, 150);
    border-radius: 6px;
    color: #dcecff;
    background: rgba(25, 54, 88, 220);
    font-size: 11px;
    font-weight: 800;
}

QLabel#brandTitle {
    color: #d9ae4f;
    font-size: 24px;
    font-weight: 800;
    letter-spacing: 2px;
}

QLabel#brandSubtitle {
    color: #8fa2bd;
    font-size: 12px;
}

QLabel#connectionLabel {
    color: #9eb4d3;
    font-size: 12px;
}

QFrame#navigation {
    background: rgba(15, 27, 48, 215);
    border: 1px solid rgba(97, 148, 211, 65);
    border-radius: 12px;
}

QPushButton#navButton {
    min-width: 120px;
    padding: 9px 16px;
    border: 1px solid rgba(97, 148, 211, 75);
    border-radius: 8px;
    color: #c9d9ee;
    background: rgba(28, 51, 82, 175);
    font-size: 12px;
    font-weight: 700;
}

QPushButton#navButton:hover {
    color: #ffffff;
    background: rgba(55, 104, 164, 210);
}

QPushButton#navButton:checked {
    color: #111827;
    background: #d9ae4f;
    border-color: #f0cc70;
}

QPushButton#navButton:disabled {
    color: #596c86;
    background: rgba(18, 29, 45, 130);
    border-color: rgba(97, 148, 211, 28);
}

QPushButton#closeButton {
    min-width: 34px;
    min-height: 30px;
    border: 1px solid rgba(97, 148, 211, 90);
    border-radius: 7px;
    color: #dbe7f5;
    background: rgba(28, 46, 72, 180);
    font-size: 18px;
    font-weight: 700;
}

QPushButton#closeButton:hover {
    color: #ffffff;
    background: #9f3543;
}

QFrame#heroCard,
QFrame#sectionCard,
QFrame#metricCard {
    border: 1px solid rgba(97, 148, 211, 62);
    border-radius: 16px;
    background: rgba(15, 27, 48, 195);
}

QFrame#heroCard {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(21, 52, 93, 225),
        stop: 1 rgba(10, 18, 33, 220)
    );
}

QLabel#eyebrow,
QLabel#metricLabel {
    color: #d9ae4f;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1px;
}

QLabel#heroTitle {
    color: #f4f7ff;
    font-size: 30px;
    font-weight: 800;
}

QLabel#heroText,
QLabel#mutedText,
QLabel#metricDetail {
    color: #9caec9;
    font-size: 13px;
}

QLabel#metricValue {
    color: #edf4ff;
    font-size: 18px;
    font-weight: 800;
}

QLabel#sectionTitle {
    color: #dbe8ff;
    font-size: 18px;
    font-weight: 800;
}

QLabel#liveSummary {
    color: #9caec9;
    font-size: 14px;
}

QLabel#liveTime {
    color: #d9ae4f;
    font-size: 22px;
    font-weight: 800;
}

QLabel#settingsLabel {
    color: #cbdcff;
    font-size: 13px;
    font-weight: 700;
}

QPushButton#primaryButton,
QPushButton#secondaryButton,
QPushButton#disabledSyncButton {
    min-height: 34px;
    padding: 8px 14px;
    border-radius: 8px;
    font-weight: 700;
}

QPushButton#primaryButton {
    color: #111827;
    background: #d9ae4f;
    border: 1px solid #f0cc70;
}

QPushButton#primaryButton:hover {
    background: #ebc56a;
}

QPushButton#secondaryButton {
    color: #dbe9ff;
    background: #1b3657;
    border: 1px solid #3e6d9e;
}

QPushButton#secondaryButton:hover {
    background: #285783;
}

/* Botón de sync desactivado permanentemente (práctica / tutorial / personalizada).
   Más apagado que un :disabled normal para dejar claro que no aplica. */
QPushButton#disabledSyncButton {
    color: #3d4f63;
    background: #0e1a26;
    border: 1px solid #1e2e3f;
    font-weight: 600;
    opacity: 0.45;
}

QPushButton#disabledSyncButton:hover {
    background: #0e1a26;
    border: 1px solid #1e2e3f;
}

QPushButton#dangerButton {
    min-height: 34px;
    padding: 8px 14px;
    border-radius: 8px;
    font-weight: 700;
    color: #ffd8d8;
    background: #7a1c27;
    border: 1px solid #aa3544;
}

QPushButton#dangerButton:hover {
    color: #ffffff;
    background: #962835;
    border-color: #c44354;
}

QSlider::groove:horizontal {
    height: 7px;
    border-radius: 3px;
    background: #29476a;
}

QSlider::handle:horizontal {
    width: 15px;
    margin: -4px 0;
    border: 1px solid #f0cc70;
    border-radius: 7px;
    background: #d9ae4f;
}

QScrollArea#settingsScrollArea,
QScrollArea#liveScrollArea,
QScrollArea#scrollArea {
    border: none;
    background: transparent;
}

QWidget#liveCardsContainer,
QWidget#cardsWidget {
    background: transparent;
}

QScrollBar:vertical {
    width: 10px;
    border: none;
    background: transparent;
}

QScrollBar::handle:vertical {
    min-height: 30px;
    border-radius: 5px;
    background: #284466;
}

QScrollBar::handle:vertical:hover {
    background: #3e6d9e;
}

QLabel#settingsGroupTitle {
    margin-top: 6px;
    color: #d9ae4f;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 1px;
}

QLineEdit#apiKeyInput {
    min-height: 36px;
    padding: 7px 10px;
    border: 1px solid rgba(97, 148, 211, 115);
    border-radius: 8px;
    color: #e8f0ff;
    background: rgba(5, 12, 24, 185);
    font-family: "Cascadia Code";
    font-size: 12px;
}

QLineEdit#apiKeyInput:focus {
    border: 1px solid #d9ae4f;
    background: rgba(9, 18, 33, 225);
}

QLabel#apiKeyStatus {
    min-height: 22px;
    font-size: 11px;
}

QLabel#apiKeyStatus[state="saved"] {
    color: #9eb4d3;
}

QLabel#apiKeyStatus[state="checking"] {
    color: #d9ae4f;
}

QLabel#apiKeyStatus[state="valid"] {
    color: #64d9a3;
}

QLabel#apiKeyStatus[state="invalid"] {
    color: #ff7081;
}

QLabel#apiKeyStatus[state="missing"] {
    color: #9caec9;
}

/* Pasos numerados de las tarjetas de API (Riot / Gemini): bloque
   monoespaciado sobre fondo hundido para leerse como una guía. */
QLabel#settingsSteps {
    padding: 10px 14px;
    border: 1px solid rgba(97, 148, 211, 60);
    border-left: 3px solid #d9ae4f;
    border-radius: 8px;
    color: #b8c8e4;
    background: rgba(5, 12, 24, 140);
    font-size: 12px;
    line-height: 160%;
}

/* Los desplegables de Ajustes respiran un poco más y muestran mejor el
   modo de audio elegido, que tiene etiquetas largas. */
QComboBox#analysisCombo {
    min-height: 32px;
    padding: 6px 12px;
}

QFrame#settingsPage QFrame#sectionCard {
    border: 1px solid rgba(97, 148, 211, 75);
    border-radius: 14px;
    background: rgba(10, 20, 36, 200);
}

QLineEdit#riotIdInput {
    min-height: 34px;
    padding: 6px 10px;
    border: 1px solid rgba(97, 148, 211, 115);
    border-radius: 8px;
    color: #e8f0ff;
    background: rgba(5, 12, 24, 185);
    font-size: 12px;
}

QLineEdit#riotIdInput:focus {
    border: 1px solid #d9ae4f;
    background: rgba(9, 18, 33, 225);
}

QLabel#riotTagPrefix {
    color: #d9ae4f;
    font-size: 18px;
    font-weight: 800;
}

QLabel#historyStatus {
    min-height: 21px;
    color: #9caec9;
    font-size: 11px;
}

QLabel#historyStatus[state="loading"] {
    color: #d9ae4f;
}

QLabel#historyStatus[state="success"] {
    color: #64d9a3;
}

QLabel#historyStatus[state="error"] {
    color: #ff7081;
}

QLabel#historyStatus[state="empty"] {
    color: #9caec9;
}

QFrame#matchHistoryRow {
    border: 1px solid rgba(80, 118, 171, 95);
    border-radius: 9px;
    background: rgba(5, 13, 27, 168);
}

QLabel#matchResult {
    font-size: 12px;
    font-weight: 800;
}

QLabel#matchResult[result="victory"] {
    color: #64d9a3;
}

QLabel#matchResult[result="defeat"] {
    color: #ff7081;
}

QLabel#matchChampion {
    color: #e8f0ff;
    font-size: 13px;
    font-weight: 700;
}

QLabel#matchKda {
    color: #d8e4f8;
    font-family: "Cascadia Code";
    font-size: 12px;
}

QLabel#matchCs,
QLabel#matchDuration {
    color: #9eb4d3;
    font-family: "Cascadia Code";
    font-size: 12px;
}

QFrame#matchHistoryRow:hover {
    border: 1px solid rgba(217, 174, 79, 205);
    background: rgba(15, 29, 50, 220);
}

QDialog#matchInspectorDialog {
    background: #07101f;
    color: #e8f0ff;
}

QFrame#matchInspectorHeader {
    min-height: 92px;
    border: 1px solid rgba(116, 163, 220, 145);
    border-radius: 14px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(18, 39, 70, 245),
        stop: 0.58 rgba(9, 22, 41, 245),
        stop: 1 rgba(28, 25, 46, 245)
    );
}

QLabel#championPortrait {
    border: 2px solid #d9ae4f;
    border-radius: 13px;
    color: #d9ae4f;
    background: #102039;
    font-size: 14px;
    font-weight: 900;
}

QLabel#itemIcon {
    min-width: 36px;
    min-height: 36px;
    max-width: 36px;
    max-height: 36px;
    border: 1px solid rgba(217, 174, 79, 210);
    border-radius: 6px;
    color: #b5c6de;
    background: #0b172a;
    font-size: 9px;
}

QLabel#inspectorResult {
    font-size: 13px;
    font-weight: 900;
}

QLabel#inspectorResult[result="victory"] {
    color: #64d9a3;
}

QLabel#inspectorResult[result="defeat"] {
    color: #ff7081;
}

QLabel#inspectorTitle {
    color: #f1f5ff;
    font-size: 16px;
    font-weight: 800;
}

QLabel#inspectorSubtitle,
QLabel#playerStats,
QLabel#itemsCaption {
    color: #9eb4d3;
    font-size: 11px;
}

QLabel#inspectorKda {
    color: #f1f5ff;
    font-family: "Cascadia Code";
    font-size: 16px;
    font-weight: 800;
}

QFrame#objectivesCard {
    border: 1px solid rgba(217, 174, 79, 125);
    border-radius: 12px;
    background: rgba(11, 25, 45, 235);
}

QLabel#objectiveValue {
    font-size: 11px;
    font-weight: 700;
}

QLabel#objectiveValue[team="ally"] {
    color: #70dbaa;
}

QLabel#objectiveValue[team="enemy"] {
    color: #ff8793;
}

QFrame#matchTeamCard {
    border: 1px solid rgba(104, 145, 197, 110);
    border-radius: 10px;
    background: rgba(7, 17, 32, 235);
}

QLabel#teamHeading {
    padding: 2px 4px;
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 1px;
}

QLabel#teamHeading[team="ally"] {
    color: #70dbaa;
}

QLabel#teamHeading[team="enemy"] {
    color: #ff8793;
}

QFrame#matchPlayerRow {
    margin: 0px;
    min-height: 86px;
    border: 1px solid rgba(91, 130, 180, 110);
    border-radius: 11px;
    background: rgba(17, 36, 62, 240);
}

QFrame#matchPlayerRow[player="self"] {
    border: 1px solid rgba(217, 174, 79, 180);
    background: rgba(35, 34, 44, 235);
}

QFrame#matchPlayerRow:hover {
    background: rgba(27, 50, 80, 240);
}

QLabel#playerPosition {
    min-width: 28px;
    color: #d9ae4f;
    font-size: 10px;
    font-weight: 900;
}

QLabel#playerName {
    color: #c3d2e9;
    font-size: 10px;
}

QScrollArea#matchInspectorScroll,
QWidget#matchInspectorContent {
    background: transparent;
    border: none;
}


QDialog#matchInspectorDialog {
    background: #06101f;
    color: #edf4ff;
}

QFrame#matchInspectorHeader {
    min-height: 112px;
    border: 1px solid rgba(116, 163, 220, 170);
    border-radius: 16px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(20, 49, 83, 250), stop:0.55 rgba(8, 23, 43, 250), stop:1 rgba(37, 28, 47, 250));
}

QLabel#championPortrait {
    border: 2px solid #d9ae4f;
    border-radius: 12px;
    color: #d9ae4f;
    background: #102039;
    font-size: 13px;
    font-weight: 900;
}

QLabel#inspectorResult { font-size: 16px; font-weight: 900; }
QLabel#inspectorResult[result="victory"] { color: #70e0ad; }
QLabel#inspectorResult[result="defeat"] { color: #ff8793; }
QLabel#inspectorTitle { color: #f4f7ff; font-size: 19px; font-weight: 900; }
QLabel#inspectorSubtitle { color: #b3c5df; font-size: 13px; }
QLabel#inspectorKda { color: #ffffff; font-family: "Cascadia Code"; font-size: 20px; font-weight: 900; }

QFrame#objectivesCard {
    border: 1px solid rgba(217, 174, 79, 165);
    border-radius: 14px;
    background: rgba(10, 27, 49, 245);
}

QLabel#objectivesTitle {
    color: #e4bd5e;
    font-size: 14px;
    font-weight: 900;
    letter-spacing: 1px;
}

QLabel#objectiveTeam {
    font-size: 14px;
    font-weight: 900;
}

QLabel#objectiveTeam[team="ally"] {
    color: #70e0ad;
}

QLabel#objectiveTeam[team="enemy"] {
    color: #ff8793;
}

QLabel#objectiveIcon {
    border: 1px solid rgba(139, 167, 204, 125);
    border-radius: 8px;
    background: rgba(16, 34, 59, 235);
    font-size: 22px;
}

QLabel#objectiveName {
    color: #c9d6e8;
    font-size: 12px;
    font-weight: 700;
}

QLabel#objectiveCount {
    font-family: "Cascadia Code";
    font-size: 18px;
    font-weight: 900;
}

QLabel#objectiveCount[team="ally"] {
    color: #70e0ad;
}

QLabel#objectiveCount[team="enemy"] {
    color: #ff8793;
}

QLabel#teamHeading { padding: 4px 7px 9px 7px; font-size: 14px; font-weight: 900; letter-spacing: 1px; }
QLabel#teamHeading[team="ally"] { color: #70e0ad; }
QLabel#teamHeading[team="enemy"] { color: #ff8793; }

QFrame#matchPlayerRow {
    min-height: 128px;
    border: 1px solid rgba(91, 130, 180, 115);
    border-radius: 13px;
    background: rgba(17, 36, 62, 240);
}

QFrame#matchPlayerRow[player="self"] {
    border: 1px solid rgba(217, 174, 79, 225);
    background: rgba(42, 40, 49, 245);
}

QFrame#matchPlayerRow:hover { background: rgba(31, 60, 94, 245); }
QLabel#playerPosition { min-width: 31px; color: #e4bd5e; font-size: 12px; font-weight: 900; }

QLabel#playerChampion {
    color: #f4f7ff;
    font-size: 12px;
    font-weight: 900;
}

QLabel#playerName {
    color: #d1dded;
    font-size: 10px;
}

QLabel#playerStats {
    color: #d2deed;
    font-family: "Cascadia Code";
    font-size: 12px;
}

QLabel#itemsCaption {
    color: #bfcee1;
    font-size: 12px;
}

QScrollArea#matchInspectorScroll, QWidget#matchInspectorContent { background: transparent; border: none; }

QFrame#objectiveTeamPanel {
    min-height: 145px;
    border: 1px solid rgba(108, 145, 193, 145);
    border-radius: 11px;
    background: rgba(5, 17, 33, 215);
}

QFrame#objectiveTeamPanel[team="ally"] {
    border-color: rgba(87, 205, 153, 160);
}

QFrame#objectiveTeamPanel[team="enemy"] {
    border-color: rgba(244, 112, 126, 160);
}

QLabel#compactObjectiveCount {
    min-width: 13px;
    color: #d6e2f1;
    font-family: "Cascadia Code";
    font-size: 11px;
    font-weight: 900;
}

QLabel#compactObjectiveCount[team="ally"] {
    color: #70e0ad;
}

QLabel#compactObjectiveCount[team="enemy"] {
    color: #ff8793;
}

QLabel#filterLabel {
    color: #d9ae4f;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
}

QLineEdit#analysisInput,
QComboBox#analysisCombo {
    min-height: 34px;
    padding: 6px 9px;
    border: 1px solid rgba(97, 148, 211, 115);
    border-radius: 8px;
    color: #e8f0ff;
    background: rgba(5, 12, 24, 185);
}

QFrame#analysisSourceRow {
    border: 1px solid rgba(86, 126, 179, 95);
    border-radius: 9px;
    background: rgba(6, 15, 29, 160);
}

QFrame#analysisSourceRow:hover {
    border: 1px solid rgba(217, 174, 79, 180);
    background: rgba(15, 29, 50, 215);
}

QLabel#analysisSourceTitle {
    color: #f0f5ff;
    font-size: 14px;
    font-weight: 800;
}

QLabel#analysisStatus {
    min-height: 22px;
    color: #9eb4d3;
    font-size: 11px;
}

QLabel#analysisStatus[state="success"] {
    color: #64d9a3;
}

QLabel#analysisStatus[state="error"] {
    color: #ff7081;
}

QFrame#analysisSourcesBar {
    border: 1px solid rgba(86, 126, 179, 95);
    border-radius: 9px;
    background: rgba(6, 15, 29, 170);
}

QPushButton#analysisSourceButton {
    min-height: 30px;
    padding: 5px 10px;
    border: 1px solid rgba(97, 148, 211, 100);
    border-radius: 7px;
    color: #b8c9e0;
    background: rgba(12, 29, 51, 180);
    font-size: 11px;
    font-weight: 700;
}

QPushButton#analysisSourceButton:hover {
    border-color: rgba(217, 174, 79, 185);
    color: #e8f0ff;
}

QPushButton#analysisSourceButton:checked {
    border-color: #d9ae4f;
    color: #f3d276;
    background: rgba(76, 60, 30, 185);
}

QWebEngineView#analysisWebView {
    border: 1px solid rgba(86, 126, 179, 110);
    border-radius: 10px;
    background: #ffffff;
}

QFrame#recommendationPanel {
    border: 1px solid rgba(217, 174, 79, 145);
    border-radius: 12px;
    background: #071221;
}

QFrame#recommendationHeader {
    border: 1px solid rgba(89, 127, 177, 120);
    border-radius: 9px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(20, 49, 83, 235), stop:1 rgba(37, 28, 47, 235));
}

QLabel#recommendationTitle {
    color: #f4f7ff;
    font-size: 20px;
    font-weight: 900;
}

QLabel#recommendationStyle {
    color: #e4bd5e;
    font-size: 14px;
    font-weight: 800;
}

QLabel#recommendationGold {
    color: #5ee7a5;
    font-size: 15px;
    font-weight: 900;
}

QComboBox#recommendationStyleSelector {
    min-width: 170px;
    padding: 5px 8px;
    border: 1px solid rgba(217, 174, 79, 150);
    border-radius: 5px;
    color: #f0d37b;
    background: rgba(9, 22, 41, 210);
}

QPushButton#recommendationBackButton {
    max-width: 150px;
    padding: 7px 10px;
    border: 1px solid rgba(89, 127, 177, 150);
    border-radius: 5px;
    color: #c6d8ef;
    background: rgba(20, 49, 83, 210);
}

QPushButton#recommendationBackButton:hover {
    border-color: #d9ae4f;
    color: #f3d276;
}

QLabel#recommendationRouteTitle {
    color: #f4f7ff;
    font-size: 20px;
    font-weight: 900;
}

QFrame#recommendationItemRow {
    min-height: 64px;
    border: 1px solid rgba(89, 127, 177, 100);
    border-radius: 7px;
    background: rgba(14, 31, 53, 220);
}

QFrame#recommendationNextPurchase {
    min-height: 86px;
    border: 1px solid rgba(35, 205, 137, 170);
    border-radius: 9px;
    background: rgba(10, 50, 47, 225);
}

QLabel#recommendationLargeIcon {
    border: 1px solid rgba(217, 174, 79, 170);
    border-radius: 7px;
    background: rgba(5, 15, 28, 230);
}

QFrame#recommendationPlayerHeader {
    border: 1px solid rgba(86, 126, 179, 130);
    border-radius: 8px;
    background: rgba(5, 22, 40, 235);
}

QLabel#recommendationPortrait {
    border: 2px solid #d9ae4f;
    border-radius: 8px;
}

QLabel#recommendationPlayerName {
    color: #f4f7ff;
    font-size: 17px;
    font-weight: 900;
}

QLabel#recommendationPlayerGold {
    min-width: 90px;
    color: #5ee7a5;
    font-size: 17px;
    font-weight: 900;
}

QLabel#recommendationPlayerMeta,
QLabel#recommendationSectionTitle {
    color: #b6c9e3;
    font-size: 11px;
    font-weight: 800;
}

QFrame#recommendationInventory {
    border: 1px solid rgba(86, 126, 179, 100);
    border-radius: 8px;
    background: rgba(9, 25, 45, 220);
}

QLabel#recommendationInventoryIcon {
    border: 1px solid rgba(217, 174, 79, 140);
    border-radius: 5px;
    background: #071221;
}

QLabel#recommendationMuted {
    color: #8298b8;
}

QLabel#recommendationCompatibilityNote {
    padding: 9px 11px;
    border-left: 3px solid #d9ae4f;
    color: #e4bd5e;
    background: rgba(80, 61, 25, 120);
}

QLabel#recommendationItemName {
    color: #eef4ff;
    font-size: 14px;
    font-weight: 800;
}

QLabel#recommendationNote,
QLabel#recommendationReason {
    color: #a8bbd5;
    font-size: 13px;
}

QFrame#recommendationBuildCard,
QFrame#recommendationSituational {
    border: 1px solid rgba(89, 127, 177, 110);
    border-radius: 9px;
    background: rgba(14, 31, 53, 220);
}

QFrame#recommendationBuildCard:hover {
    border-color: rgba(217, 174, 79, 190);
    background: rgba(22, 43, 70, 235);
}

QFrame#recommendationSituational {
    border-color: rgba(100, 217, 163, 130);
    background: rgba(13, 43, 43, 190);
}

QLabel#recommendationBuildTitle {
    color: #eef4ff;
    font-size: 14px;
    font-weight: 900;
}

QLabel#recommendationBadge {
    padding: 3px 7px;
    border: 1px solid rgba(217, 174, 79, 170);
    border-radius: 5px;
    color: #f0d37b;
    background: rgba(80, 61, 25, 165);
    font-size: 9px;
    font-weight: 900;
}

QLabel#recommendationItems {
    color: #d8e6f8;
    font-family: "Cascadia Code";
    font-size: 11px;
}

QLabel#recommendationEmptyState {
    padding: 14px;
    border: 1px dashed rgba(97, 148, 211, 110);
    border-radius: 7px;
    color: #9eb4d3;
    background: rgba(9, 22, 41, 130);
}

QLabel#analysisStatus[state="idle"] {
    color: #9eb4d3;
}

QLabel#analysisStatus[state="loading"] {
    color: #d9ae4f;
}

QLabel#savedGamesStatus {
    min-height: 22px;
    color: #9eb4d3;
    font-size: 11px;
}

QScrollArea#savedGamesScroll,
QWidget#savedGamesContent {
    border: none;
    background: transparent;
}

QLabel#savedGamesEmpty {
    min-height: 180px;
    padding: 26px;
    border: 1px dashed rgba(97, 148, 211, 110);
    border-radius: 12px;
    color: #9eb4d3;
    background: rgba(6, 15, 29, 130);
}

QFrame#savedGameRow {
    border: 1px solid #293c56;
    border-left: 4px solid #64748b;
    border-radius: 12px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #112139, stop:1 #0b1423);
}

QFrame#savedGameRow[result="win"] {
    border-left-color: #4adea0;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #102d2c, stop:0.45 #102033, stop:1 #0b1423);
}

QFrame#savedGameRow[result="loss"] {
    border-left-color: #f07d8a;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #30202e, stop:0.45 #142033, stop:1 #0b1423);
}

QFrame#savedGameRow:hover {
    border-top-color: #607698;
    border-right-color: #607698;
    border-bottom-color: #607698;
}

QLabel#savedGameResult {
    padding: 5px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 800;
    color: #acbdd3;
    background: #243247;
    border: 1px solid #3b4e68;
}

QLabel#savedGameResult[result="win"] {
    color: #71edb1;
    background: #163e34;
    border-color: #2d6b54;
}

QLabel#savedGameResult[result="loss"] {
    color: #ff9ca7;
    background: #482631;
    border-color: #77404c;
}

/* Overrides locales: los botones generales incluyen padding y min-height
   que aumentaban la altura fijada por la tarjeta. */
QFrame#savedGameRow QPushButton {
    min-height: 34px;
    max-height: 34px;
    padding: 0 8px;
    font-size: 11px;
}

QFrame#savedGameRow QPushButton#dangerButton {
    color: #dba0aa;
    background: transparent;
    border: 1px solid #68414c;
}

QFrame#savedGameRow QPushButton#dangerButton:hover {
    color: #ffe4e8;
    background: #572733;
    border-color: #b65d70;
}

QFrame#savedGameRow QPushButton#dangerButton:disabled {
    color: #68778d;
    background: transparent;
    border-color: #334155;
}

QLabel#savedGameChampIcon {
    border: 2px solid #65748c;
    border-radius: 8px;
    background: #091321;
    color: #d9ae4f;
    font-size: 24px;
    font-weight: 800;
}

QLabel#savedGameTitle {
    color: #eef4ff;
    font-size: 18px;
    font-weight: 800;
}

QLabel#savedGameDetail {
    color: #a3b4cc;
    font-size: 12px;
}

QLabel#savedGameSync {
    font-size: 10px;
    font-weight: 800;
    padding: 3px 9px;
    border-radius: 6px;
}

QLabel#savedGameSync[state="live_only"],
QLabel#savedGameSync[state="pending"] {
    color: #facc15;
    background: rgba(217, 174, 79, 40);
    border: 1px solid rgba(217, 174, 79, 110);
}

QLabel#savedGameSync[state="not_found"] {
    color: #94a3b8;
    background: rgba(100, 116, 139, 30);
    border: 1px solid rgba(100, 116, 139, 90);
}

QLabel#savedGameSync[state="synced"] {
    color: #96c8f6;
    background: rgba(59, 130, 246, 25);
    border: 1px solid rgba(96, 165, 250, 85);
}

QLabel#savedGameSync[state="failed"] {
    color: #f87171;
    background: rgba(239, 68, 68, 40);
    border: 1px solid rgba(239, 68, 68, 110);
}

QFrame#recordingPlayerCard {
    border: 1px solid rgba(97, 148, 211, 62);
    border-radius: 16px;
    background: rgba(15, 27, 48, 195);
}

QScrollArea#recordingsScroll,
QWidget#recordingsContent {
    border: none;
    background: transparent;
}

QLabel#recordingsStatus {
    min-height: 22px;
    color: #9eb4d3;
    font-size: 11px;
}

QLabel#recordingsStatus[state="live"] {
    color: #ff9ca7;
    font-weight: 800;
}

QLabel#recordingsEmpty {
    min-height: 180px;
    padding: 26px;
    border: 1px dashed rgba(97, 148, 211, 110);
    border-radius: 12px;
    color: #9eb4d3;
    background: rgba(6, 15, 29, 130);
}

QFrame#recordingRow {
    border: 1px solid #293c56;
    border-left: 4px solid #4adea0;
    border-radius: 12px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #102d2c, stop:0.45 #102033, stop:1 #0b1423);
}

QFrame#recordingRow:hover {
    border-top-color: #607698;
    border-right-color: #607698;
    border-bottom-color: #607698;
}

QLabel#recordingTitle {
    color: #eef4ff;
    font-size: 16px;
    font-weight: 800;
}

QLabel#recordingDetail {
    color: #a3b4cc;
    font-size: 12px;
}

QLabel#recordingBadge {
    padding: 5px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 800;
    color: #acbdd3;
    background: #243247;
    border: 1px solid #3b4e68;
}

QLabel#recordingBadge[state="live"] {
    color: #ffb3c0;
    background: #482631;
    border-color: #77404c;
}

QLabel#recordingBadge[state="pending"] {
    color: #facc15;
    background: rgba(217, 174, 79, 40);
    border: 1px solid rgba(217, 174, 79, 110);
}

QFrame#recordingRow QPushButton {
    min-height: 34px;
    max-height: 34px;
    padding: 0 8px;
    font-size: 11px;
}

QLabel#recordingPlayerTitle {
    color: #f4f7ff;
    font-size: 15px;
    font-weight: 800;
}

QLabel#recordingPlayerTime {
    color: #d9ae4f;
    font-size: 13px;
    font-weight: 800;
}

QLabel#recordingMarkerLegend {
    color: #8fa2bd;
    font-size: 11px;
}

QSlider#recordingSlider::groove:horizontal {
    height: 11px;
    border-radius: 5px;
    background: #22385a;
    border: 1px solid rgba(97, 148, 211, 45);
}

QSlider#recordingSlider::sub-page:horizontal {
    height: 11px;
    border-radius: 5px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #8a6420, stop: 1 #e7b84a
    );
}

QSlider#recordingSlider::handle:horizontal {
    width: 16px;
    margin: -5px 0;
    border: 2px solid #f6e3a1;
    border-radius: 8px;
    background: #d9ae4f;
}

QPushButton#recordingPlayButton {
    min-height: 34px;
    padding: 8px 14px;
    border-radius: 8px;
    font-weight: 700;
    color: #dbe9ff;
    background: #1b3657;
    border: 1px solid #3e6d9e;
}

QPushButton#recordingPlayButton:hover {
    background: #285783;
}

QPushButton#recordingPlayButton:disabled {
    color: #596c86;
    background: rgba(18, 29, 45, 130);
    border-color: rgba(97, 148, 211, 28);
}

QSlider#recordingVolume {
    max-width: 120px;
}

QListWidget#recordingMarkerList {
    background: rgba(6, 15, 29, 160);
    border: 1px solid rgba(97, 148, 211, 65);
    border-radius: 8px;
    color: #cbdcff;
    font-size: 11px;
    outline: none;
}

QListWidget#recordingMarkerList::item {
    padding: 4px 8px;
    border-bottom: 1px solid rgba(97, 148, 211, 30);
}

QListWidget#recordingMarkerList::item:hover {
    background: rgba(55, 104, 164, 120);
    color: #ffffff;
}

QVideoWidget#recordingVideo {
    border-radius: 10px;
    background: #05090f;
}

QFrame#recordingKdaCard {
    border: 1px solid rgba(97, 148, 211, 90);
    border-radius: 8px;
    background: rgba(8, 17, 31, 205);
}

QLabel#recordingKdaEyebrow {
    color: #7f93b1;
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 1px;
    border: none;
    background: transparent;
}

QLabel#recordingKdaValue {
    color: #eef4ff;
    font-size: 11px;
    font-weight: 900;
    border: none;
    background: transparent;
}

QLabel#recordingKdaObjectives {
    color: #d9ae4f;
    font-size: 10px;
    font-weight: 800;
    border: none;
    background: transparent;
}

QDialog#liveMatchAnalysisDialog {
    background: #07101f;
    color: #e8f0ff;
}

QFrame#liveAnalysisHeader {
    min-height: 64px;
    border: 1px solid rgba(97, 148, 211, 155);
    border-radius: 12px;
    background: qlineargradient(
        x1: 0,
        y1: 0,
        x2: 1,
        y2: 1,
        stop: 0 rgba(20, 49, 83, 245),
        stop: 0.58 rgba(8, 23, 43, 245),
        stop: 1 rgba(37, 28, 47, 245)
    );
}

QLabel#liveAnalysisTitle {
    color: #f4f7ff;
    font-size: 16px;
    font-weight: 900;
}

QLabel#liveAnalysisSubtitle {
    color: #aec0da;
    font-size: 11px;
}

QLabel#liveAnalysisBadge {
    padding: 5px 8px;
    border: 1px solid rgba(217, 174, 79, 155);
    border-radius: 6px;
    color: #e7c56c;
    background: rgba(87, 67, 31, 125);
    font-size: 10px;
    font-weight: 900;
}

QLabel#liveAnalysisBadge[state="synced"] {
    border-color: rgba(100, 217, 163, 160);
    color: #70e0ad;
    background: rgba(32, 100, 75, 125);
}

QPushButton#liveRoleButton {
    min-height: 32px;
    padding: 6px 12px;
    border: 1px solid rgba(97, 148, 211, 105);
    border-radius: 7px;
    color: #b8c9e0;
    background: rgba(12, 29, 51, 190);
    font-size: 11px;
    font-weight: 800;
}

QPushButton#liveRoleButton:hover {
    border-color: rgba(217, 174, 79, 190);
    color: #e8f0ff;
}

QPushButton#liveRoleButton:checked {
    border-color: #d9ae4f;
    color: #f3d276;
    background: rgba(76, 60, 30, 185);
}

QFrame#livePlayerPanel {
    border: 1px solid rgba(89, 127, 177, 125);
    border-radius: 12px;
    background: rgba(7, 18, 35, 235);
}

QFrame#livePlayerPanel[side="ally"] {
    border-color: rgba(63, 177, 233, 160);
}

QFrame#livePlayerPanel[side="enemy"] {
    border-color: rgba(234, 88, 109, 160);
}

QLabel#livePlayerPortrait {
    border: 2px solid #d9ae4f;
    border-radius: 9px;
    color: #d9ae4f;
    background: #102039;
    font-size: 11px;
    font-weight: 900;
}

QLabel#livePlayerChampion {
    color: #f3f6ff;
    font-size: 15px;
    font-weight: 900;
}

QLabel#livePlayerName {
    color: #b7c8df;
    font-size: 10px;
}

QLabel#livePlayerRole {
    color: #d9ae4f;
    font-size: 10px;
    font-weight: 900;
}

QFrame#liveMetricSummary {
    border: 1px solid rgba(89, 127, 177, 95);
    border-radius: 8px;
    background: rgba(14, 31, 53, 210);
}

QLabel#liveMetricLine {
    color: #d5e1f1;
    font-family: "Cascadia Code";
    font-size: 11px;
}

QFrame#liveTimelinePanel {
    border: 1px solid rgba(217, 174, 79, 155);
    border-radius: 12px;
    background: rgba(7, 16, 29, 245);
}

QLabel#liveTimelineTitle {
    color: #e8c975;
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 1px;
}

QLabel#liveTimelineHint {
    color: #93a9c8;
    font-size: 10px;
}

QScrollArea#liveTimelineScroll {
    border: none;
    background: transparent;
}

QFrame#liveTimelineRow {
    border: 1px solid rgba(80, 118, 171, 72);
    border-radius: 7px;
    background: rgba(15, 31, 53, 175);
}

QFrame#liveTimelineRow[side="ally"] {
    border-left: 3px solid #3abcf5;
}

QFrame#liveTimelineRow[side="enemy"] {
    border-right: 3px solid #f4576c;
}

QLabel#liveEventIcon {
    border: 1px solid rgba(217, 174, 79, 145);
    border-radius: 4px;
    color: #e6c66e;
    background: rgba(14, 31, 53, 225);
    font-size: 14px;
    font-weight: 900;
}

QLabel#liveEventTime {
    min-width: 48px;
    color: #d9ae4f;
    font-family: "Cascadia Code";
    font-size: 10px;
    font-weight: 800;
}

QLabel#liveEventLabel {
    color: #d7e4f5;
    font-size: 11px;
}

QLabel#liveTimelineEmpty,
QLabel#liveAnalysisEmpty {
    min-height: 150px;
    color: #9eb4d3;
    font-size: 12px;
}

QWidget#comparisonChart {
    border: 1px solid rgba(78, 116, 166, 105);
    border-radius: 8px;
    background: rgba(8, 19, 34, 205);
}

QLabel#liveTimelineHint {
    color: #93a9c8;
    font-size: 10px;
    padding: 6px 0 0 0;
}

QWidget#versusChart {
    border: 1px solid rgba(78, 116, 166, 105);
    border-radius: 8px;
    background: rgba(8, 19, 34, 220);
}

QPushButton#timelineFilterButton {
    min-height: 28px;
    padding: 5px 10px;
    border: 1px solid rgba(97, 148, 211, 105);
    border-radius: 7px;
    color: #b8c9e0;
    background: rgba(12, 29, 51, 190);
    font-size: 10px;
    font-weight: 800;
}

QPushButton#timelineFilterButton:hover {
    border-color: rgba(217, 174, 79, 190);
    color: #e8f0ff;
}

QPushButton#timelineFilterButton:checked {
    border-color: #d9ae4f;
    color: #f3d276;
    background: rgba(76, 60, 30, 185);
}

QWidget#versusChart {
    min-height: 178px;
    border: 1px solid rgba(78, 116, 166, 105);
    border-radius: 8px;
    background: rgba(8, 19, 34, 220);
}

QFrame#liveInfoPanel,
QFrame#liveAwardsPanel {
    border: 1px solid rgba(89, 127, 177, 105);
    border-radius: 8px;
    background: rgba(14, 31, 53, 210);
}

QLabel#livePanelTitle {
    color: #d9ae4f;
    font-size: 10px;
    font-weight: 900;
}

QLabel#liveAchievementBadge {
    padding: 4px 7px;
    border: 1px solid rgba(217, 174, 79, 145);
    border-radius: 5px;
    color: #f0cf78;
    background: rgba(76, 60, 30, 160);
    font-size: 10px;
    font-weight: 800;
}

QFrame#liveTimelineEvent {
    min-height: 32px;
    border-bottom: 1px solid rgba(89, 127, 177, 75);
    background: transparent;
}

QFrame#liveTimelineEvent:hover {
    background: rgba(65, 106, 158, 80);
}

QFrame#liveTimelineEvent QLabel {
    padding: 4px 7px;
}

QLabel#liveEventTime {
    min-width: 55px;
    color: #d9ae4f;
    font-family: "Cascadia Code";
    font-size: 10px;
    font-weight: 900;
}

QPushButton#timelineFilterButton {
    min-height: 28px;
    padding: 5px 10px;
    border: 1px solid rgba(97, 148, 211, 105);
    border-radius: 7px;
    color: #b8c9e0;
    background: rgba(12, 29, 51, 190);
    font-size: 10px;
    font-weight: 800;
}

QPushButton#timelineFilterButton:checked {
    border-color: #d9ae4f;
    color: #f3d276;
    background: rgba(76, 60, 30, 185);
}

QLabel#liveMetricLine {
    color: #dce8f8;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 11px;
}

QLabel#liveMetricEstimate {
    margin-top: 4px;
    color: #8fa7c7;
    font-size: 9px;
}

QLabel#liveAchievementBadge {
    font-size: 11px;
    font-weight: 700;
    padding: 5px 8px;
    border-radius: 6px;
}

QLabel#liveAchievementBadge[type="early"] {
    color: #2dd4bf;
    background: rgba(45, 212, 191, 35);
    border: 1px solid rgba(45, 212, 191, 110);
}

QLabel#liveAchievementBadge[type="mid"] {
    color: #fbbf24;
    background: rgba(251, 191, 36, 35);
    border: 1px solid rgba(251, 191, 36, 110);
}

QLabel#liveAchievementBadge[type="late"] {
    color: #c084fc;
    background: rgba(192, 132, 252, 35);
    border: 1px solid rgba(192, 132, 252, 110);
}

QLabel#liveAchievementBadge[type="victory"] {
    color: #4ade80;
    background: rgba(74, 222, 128, 35);
    border: 1px solid rgba(74, 222, 128, 110);
}

QLabel#liveAchievementBadge[type="offense"] {
    color: #fb923c;
    background: rgba(251, 146, 60, 35);
    border: 1px solid rgba(251, 146, 60, 110);
}

QLabel#liveAchievementBadge[type="defense"] {
    color: #38bdf8;
    background: rgba(56, 189, 248, 35);
    border: 1px solid rgba(56, 189, 248, 110);
}

QLabel#liveAchievementBadge[type="default"] {
    color: #f0cf78;
    background: rgba(217, 174, 79, 35);
    border: 1px solid rgba(217, 174, 79, 110);
}

QLabel#livePlayerRank {
    min-width: 38px;
    padding: 4px 6px;
    border: 1px solid rgba(217, 174, 79, 170);
    border-radius: 5px;
    color: #f0d37b;
    background: rgba(80, 61, 25, 165);
    font-size: 10px;
    font-weight: 900;
}

QLabel#liveChartTie {
    min-height: 18px;
    padding: 3px 7px;
    border: 1px solid rgba(217, 174, 79, 150);
    border-radius: 5px;
    color: #f0d37b;
    background: rgba(80, 61, 25, 145);
    font-size: 9px;
    font-weight: 900;
}

QLabel#liveChartsEmpty {
    padding: 10px;
    border: 1px dashed rgba(100, 135, 180, 100);
    border-radius: 7px;
    color: #8fa7c7;
    background: rgba(9, 22, 41, 130);
    font-size: 10px;
}

QLabel#savedGameSyncMessage {
    max-width: 560px;
    color: #9db2d0;
    font-size: 10px;
}

QPushButton#liveRoleButton,
QPushButton#recommendationTabButton,
QPushButton#aiTabButton {
    min-height: 34px;
    padding: 6px 14px;
    border: 1px solid rgba(97, 148, 211, 110);
    border-radius: 8px;
    color: #c9d9ee;
    background: rgba(14, 31, 53, 195);
    font-size: 11px;
    font-weight: 700;
}

QPushButton#liveRoleButton:hover,
QPushButton#recommendationTabButton:hover {
    border-color: rgba(217, 174, 79, 180);
    color: #ffffff;
    background: rgba(30, 58, 94, 210);
}

QPushButton#liveRoleButton:checked,
QPushButton#recommendationTabButton:checked {
    border: 1px solid #f0cc70;
    color: #111827;
    background: #d9ae4f;
    font-weight: 800;
}

QPushButton#aiTabButton {
    min-height: 34px;
    padding: 6px 14px;
    border: 1px solid rgba(138, 92, 246, 160);
    border-radius: 8px;
    color: #e2d9f3;
    background: rgba(45, 24, 86, 185);
    font-size: 11px;
    font-weight: 800;
}

QPushButton#aiTabButton:hover {
    border-color: #a78bfa;
    color: #ffffff;
    background: rgba(76, 40, 140, 210);
}

QPushButton#aiTabButton:checked {
    border-color: #f0cc70;
    color: #111827;
    background: #d9ae4f;
}

QFrame#aiHeaderCard {
    border: 1px solid rgba(138, 92, 246, 140);
    border-radius: 10px;
    background: rgba(18, 12, 38, 220);
}

QLabel#aiHeaderTitle {
    color: #c4b5fd;
    font-size: 15px;
    font-weight: 800;
}

QLabel#aiLogPathLabel {
    color: #94a3b8;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 11px;
}

QTextBrowser#aiAnalysisTextBrowser {
    border: 1px solid rgba(138, 92, 246, 100);
    border-radius: 10px;
    padding: 16px;
    background: rgba(9, 14, 28, 235);
    color: #e2e8f0;
    font-size: 13px;
    line-height: 1.6;
}

QFrame#aiIntroCard {
    border: 1px solid rgba(138, 92, 246, 120);
    border-radius: 12px;
    background: rgba(15, 20, 38, 210);
}

QPushButton#primaryAiButton {
    min-height: 36px;
    padding: 8px 18px;
    border: 1px solid #a78bfa;
    border-radius: 8px;
    color: #ffffff;
    background: rgba(109, 40, 217, 220);
    font-size: 12px;
    font-weight: 800;
}

QPushButton#primaryAiButton:hover {
    background: rgba(124, 58, 237, 240);
    border-color: #ddd6fe;
}

QPushButton#secondaryAiButton {
    min-height: 32px;
    padding: 6px 14px;
    border: 1px solid rgba(148, 163, 184, 120);
    border-radius: 7px;
    color: #cbd5e1;
    background: rgba(30, 41, 59, 180);
    font-size: 11px;
    font-weight: 700;
}

QPushButton#secondaryAiButton:hover {
    border-color: #94a3b8;
    color: #ffffff;
    background: rgba(51, 65, 85, 210);
}

/* ---------- Pestaña «Partida en vivo» ---------- */

QFrame#liveStatusCard {
    border: 1px solid rgba(217, 174, 79, 105);
    border-radius: 16px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(24, 54, 92, 225),
        stop: 0.55 rgba(11, 21, 38, 232),
        stop: 1 rgba(42, 27, 22, 225)
    );
}

QLabel#liveEyebrow {
    color: #d9ae4f;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 2px;
}

QLabel#liveDot {
    border: none;
    border-radius: 4px;
}

QLabel#liveDot[state="live"] {
    background: #4ade80;
}

QLabel#liveDot[state="idle"] {
    background: #5b6a80;
}

QFrame#liveClock {
    border: 1px solid rgba(217, 174, 79, 90);
    border-radius: 10px;
    background: rgba(9, 17, 30, 195);
}

QLabel#liveClockCaption {
    color: #8fa2bd;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1px;
}

QFrame#liveTeamPanel {
    border: 1px solid rgba(90, 130, 180, 65);
    border-radius: 16px;
    background: rgba(10, 18, 31, 150);
}

QFrame#liveTeamPanel[side="ally"] {
    border-color: rgba(74, 150, 255, 100);
    background: rgba(11, 25, 44, 180);
}

QFrame#liveTeamPanel[side="enemy"] {
    border-color: rgba(240, 96, 118, 100);
    background: rgba(31, 14, 23, 180);
}

QLabel#liveTeamTag {
    color: #9dc7ff;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 1px;
}

QFrame#liveTeamPanel[side="enemy"] QLabel#liveTeamTag {
    color: #ffb3c0;
}

QLabel#liveTeamSide {
    color: #7d8ea6;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 8px;
    border: 1px solid rgba(120, 160, 210, 70);
    border-radius: 8px;
}

QLabel#liveTeamSummary {
    color: #a9bad2;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}

/* ---------- Tarjeta de jugador ---------- */

QFrame#playerCard,
QFrame#playerCardMe {
    background: transparent;
}

QLabel#cardChampionIcon {
    border: 1px solid rgba(120, 170, 225, 130);
    border-radius: 10px;
    background: rgba(5, 11, 21, 190);
    color: #dbe8ff;
    font-size: 15px;
    font-weight: 800;
}

QFrame[team="order"] QLabel#cardChampionIcon {
    border-color: rgba(90, 165, 255, 170);
}

QFrame[team="chaos"] QLabel#cardChampionIcon {
    border-color: rgba(240, 110, 130, 170);
}

QFrame#playerCardMe QLabel#cardChampionIcon {
    border: 2px solid rgba(217, 174, 79, 215);
}

QLabel#cardChampionName {
    color: #f4f7ff;
    font-size: 16px;
    font-weight: 800;
}

QLabel#cardPlayerId {
    color: #93a5bf;
    font-size: 10px;
}

QLabel#cardRoleChip {
    color: #cdddf2;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 1px 6px;
    border: 1px solid rgba(130, 170, 220, 90);
    border-radius: 7px;
    background: rgba(20, 40, 66, 190);
}

QLabel#cardLevelBadge {
    color: #dcecff;
    font-size: 11px;
    font-weight: 800;
    padding: 3px 9px;
    border: 1px solid rgba(120, 170, 225, 140);
    border-radius: 9px;
    background: rgba(24, 52, 86, 225);
}

QFrame[team="chaos"] QLabel#cardLevelBadge {
    border-color: rgba(240, 120, 140, 140);
    background: rgba(62, 25, 38, 225);
}

QLabel#cardMeBadge {
    color: #241a05;
    font-size: 10px;
    font-weight: 800;
    padding: 2px 9px;
    border: 1px solid #f0cc70;
    border-radius: 9px;
    background: #d9ae4f;
}

QFrame#cardDivider {
    background: rgba(120, 160, 210, 45);
}

QFrame#cardStat {
    border: 1px solid rgba(105, 145, 195, 60);
    border-radius: 9px;
    background: rgba(6, 14, 26, 165);
}

QLabel#cardStatLabel {
    color: #8fa2bd;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1px;
}

QLabel#cardStatValue {
    color: #eef5ff;
    font-size: 13px;
    font-weight: 800;
}

QFrame#cardRunes {
    border: 1px solid rgba(140, 110, 190, 85);
    border-radius: 9px;
    background: rgba(18, 12, 32, 175);
}

QLabel#cardRuneIcon {
    border: 1px solid rgba(180, 150, 235, 135);
    border-radius: 13px;
    background: rgba(9, 6, 18, 210);
    color: #d9c6ff;
    font-size: 12px;
}

QLabel#cardRuneTreeIcon {
    border: 1px solid rgba(140, 160, 200, 95);
    border-radius: 9px;
    background: rgba(9, 6, 18, 200);
    color: #9fb0c8;
    font-size: 9px;
}

QLabel#cardRuneKeystone {
    font-size: 11px;
    font-weight: 800;
}

QLabel#cardRuneSeparator {
    color: #6f7f96;
    font-size: 12px;
    font-weight: 800;
}

QFrame#cardChips {
    border: 1px solid rgba(105, 145, 195, 55);
    border-radius: 9px;
    background: rgba(6, 13, 24, 150);
}

QLabel#cardChip {
    border: 1px solid rgba(105, 145, 195, 70);
    border-radius: 6px;
    background: rgba(12, 24, 42, 205);
    color: #cfdcee;
    font-size: 10px;
    font-weight: 800;
}

QLabel#cardChip[kind="hp"] { color: #7ee787; border-color: rgba(126, 231, 135, 115); }
QLabel#cardChip[kind="ad"] { color: #ffab73; border-color: rgba(255, 171, 115, 115); }
QLabel#cardChip[kind="ap"] { color: #8ab4ff; border-color: rgba(138, 180, 255, 115); }
QLabel#cardChip[kind="armor"] { color: #ffd479; border-color: rgba(255, 212, 121, 115); }
QLabel#cardChip[kind="mr"] { color: #c79bff; border-color: rgba(199, 155, 255, 115); }
QLabel#cardChip[kind="crit"] { color: #ffd479; border-color: rgba(255, 212, 121, 115); }
QLabel#cardChip[kind="lethality"] { color: #ffab73; border-color: rgba(255, 171, 115, 115); }
QLabel#cardChip[kind="pen"] { color: #8ab4ff; border-color: rgba(138, 180, 255, 115); }
QLabel#cardChip[kind="lifesteal"] { color: #7ee787; border-color: rgba(126, 231, 135, 115); }
QLabel#cardChip[kind="grievous"] { color: #ff8080; border-color: rgba(255, 128, 128, 115); }
QLabel#cardChip[kind="more"] { color: #a9bad2; border-color: rgba(169, 186, 210, 115); }

QLabel#cardChipsEmpty {
    color: #7d8ea6;
    font-size: 10px;
}

QLabel#cardInventoryTitle {
    color: #d9ae4f;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 2px;
}

QLabel#cardInventoryCount {
    color: #8fa2bd;
    font-size: 10px;
    font-weight: 700;
}

QLabel#itemSlot,
QLabel#trinketSlot,
QLabel#bootsQuestSlot,
QLabel#pinkWardQuestSlot {
    border: 1px solid rgba(125, 165, 215, 95);
    border-radius: 7px;
    background: rgba(5, 12, 22, 190);
}

QLabel#itemSlot:hover,
QLabel#trinketSlot:hover,
QLabel#bootsQuestSlot:hover,
QLabel#pinkWardQuestSlot:hover {
    border-color: rgba(217, 174, 79, 190);
}
/* ---- Ventana independiente de repaso post-partida ---- */

QMainWindow#postgameReplayWindow,
QWidget#postgameRoot {
    background: #07111f;
}

QFrame#postgameHeader {
    border: 1px solid rgba(97, 148, 211, 70);
    border-radius: 14px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0c1b30, stop:0.6 #102738, stop:1 #0b1423);
}

QLabel#postgameTitle {
    color: #f4f7ff;
    font-size: 19px;
    font-weight: 800;
}

QLabel#postgameSubtitle {
    color: #9eb4d3;
    font-size: 12px;
}

QLabel#postgameBadge {
    padding: 6px 12px;
    border-radius: 7px;
    color: #acbdd3;
    font-size: 11px;
    font-weight: 800;
    background: #243247;
    border: 1px solid #3b4e68;
}

QLabel#postgameBadge[state="synced"] {
    color: #4adea0;
    background: rgba(23, 70, 60, 190);
    border-color: rgba(74, 222, 160, 130);
}

QFrame#postgamePlayerCard {
    border: 1px solid rgba(97, 148, 211, 62);
    border-radius: 16px;
    background: rgba(15, 27, 48, 195);
}

QVideoWidget#postgameVideo {
    border-radius: 10px;
    background: #05090f;
}

/* Ventana dedicada de pantalla completa: vídeo arriba y, abajo, la MISMA
   barra de marcadores + fila de transporte movidas desde la tarjeta. */
QWidget#postgameFullscreenWindow,
QWidget#postgameFullscreenVideoHost {
    background: #000000;
}

QFrame#postgameFullscreenBar {
    background: rgba(9, 16, 30, 242);
    border-top: 1px solid rgba(97, 148, 211, 80);
}

QSlider#postgameMarkerSlider::groove:horizontal {
    height: 12px;
    border-radius: 6px;
    background: #22385a;
    border: 1px solid rgba(97, 148, 211, 45);
}

QSlider#postgameMarkerSlider::sub-page:horizontal {
    height: 12px;
    border-radius: 6px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #8a6420, stop: 1 #e7b84a
    );
}

QSlider#postgameMarkerSlider::handle:horizontal {
    width: 16px;
    margin: -5px 0;
    border: 2px solid #f6e3a1;
    border-radius: 8px;
    background: #d9ae4f;
}

QLabel#postgameTime {
    color: #d9ae4f;
    font-size: 13px;
    font-weight: 800;
}

QLabel#postgameMarkerLegend {
    color: #8fa2bd;
    font-size: 11px;
}

QLabel#postgameStatus {
    min-height: 22px;
    color: #9eb4d3;
    font-size: 11px;
}

QFrame#postgameSidebarHeader {
    border: 1px solid rgba(97, 148, 211, 55);
    border-radius: 12px;
    background: rgba(11, 22, 38, 200);
}

QLabel#postgameSidebarTitle {
    color: #eef4ff;
    font-size: 14px;
    font-weight: 800;
}

QLabel#postgameSidebarBadge {
    padding: 4px 9px;
    border-radius: 6px;
    color: #9eb4d3;
    font-size: 10px;
    font-weight: 800;
    background: #1c2a3e;
    border: 1px solid #33475f;
}

QLabel#postgameSidebarBadge[state="synced"] {
    color: #4adea0;
    border-color: rgba(74, 222, 160, 120);
}

QTabWidget#postgameTabs::pane {
    border: 1px solid rgba(97, 148, 211, 55);
    border-radius: 10px;
    background: rgba(8, 17, 31, 190);
}

QTabWidget#postgameTabs QTabBar::tab {
    padding: 8px 16px;
    color: #9db3ca;
    background: #0d2237;
    border: 1px solid #234663;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}

QTabWidget#postgameTabs QTabBar::tab:selected {
    color: #101a27;
    background: #d9ae4f;
    font-weight: 800;
}

QTableWidget#postgameScoreTable {
    border: 1px solid rgba(97, 148, 211, 60);
    border-radius: 8px;
    color: #cbdcff;
    background: rgba(6, 15, 29, 170);
    alternate-background-color: rgba(16, 37, 59, 150);
    gridline-color: rgba(97, 148, 211, 45);
    font-size: 11px;
}

QTableWidget#postgameScoreTable::item:selected {
    color: #101a27;
    background: #d9ae4f;
}

QTableWidget#postgameScoreTable QHeaderView::section {
    color: #d9ae4f;
    background: #153452;
    border: 0;
    padding: 6px;
    font-size: 10px;
    font-weight: 800;
}

QLabel#postgameStatsLine {
    color: #a3b4cc;
    font-size: 11px;
}

QLabel#postgameReviewEmpty {
    padding: 16px;
    border: 1px dashed rgba(97, 148, 211, 110);
    border-radius: 10px;
    color: #9eb4d3;
    background: rgba(6, 15, 29, 130);
}

QScrollArea#postgameReviewScroll,
QWidget#postgameReviewContent {
    border: none;
    background: transparent;
}

QFrame#postgameEventRow {
    border: 1px solid rgba(97, 148, 211, 45);
    border-radius: 9px;
    background: rgba(14, 26, 44, 190);
}

QFrame#postgameEventRow:hover {
    border-color: rgba(217, 174, 79, 150);
    background: rgba(21, 39, 64, 210);
}

QLabel#postgameEventTime {
    color: #d9ae4f;
    font-size: 11px;
    font-weight: 800;
}

QLabel#postgameEventTitle {
    color: #eef4ff;
    font-size: 12px;
    font-weight: 700;
}

QLabel#postgameEventTitle[evaluation="1"] { color: #7ee7a6; }
QLabel#postgameEventTitle[evaluation="-1"] { color: #ff9ca7; }

QLabel#postgameEventDetail {
    color: #b9c8dc;
    font-size: 11px;
}

QLabel#postgameEventFeedback {
    color: #8fa2bd;
    font-size: 10px;
}

QLabel#postgameEventNote {
    color: #f0cc70;
    font-size: 10px;
    font-weight: 700;
}

QLabel#postgameEventPlayer {
    color: #d9ae4f;
    font-size: 10px;
    font-weight: 700;
}

QComboBox#postgamePlayerCombo {
    min-height: 28px;
    padding: 2px 8px;
    border: 1px solid #3b4e68;
    border-radius: 7px;
    color: #dbe9ff;
    background: #16273d;
}

QPushButton#postgameScopeButton {
    min-height: 28px;
    padding: 2px 10px;
    border: 1px solid #3b4e68;
    border-radius: 7px;
    color: #b9c8dc;
    background: #16273d;
    font-size: 11px;
}

QPushButton#postgameScopeButton:checked {
    color: #101a27;
    background: #d9ae4f;
    border-color: #f0cc70;
    font-weight: 800;
}


QScrollArea#postgameOverviewScroll,
QWidget#postgameOverviewContent {
    border: none;
    background: transparent;
}

QScrollArea#postgameOverviewScroll QScrollBar:vertical {
    background: rgba(8, 17, 31, 160);
    width: 10px;
    margin: 0px;
    border: none;
    border-radius: 5px;
}

QScrollArea#postgameOverviewScroll QScrollBar::handle:vertical {
    background: rgba(97, 148, 211, 120);
    min-height: 28px;
    border-radius: 5px;
}

QScrollArea#postgameOverviewScroll QScrollBar::handle:vertical:hover {
    background: rgba(217, 174, 79, 180);
}

QScrollArea#postgameOverviewScroll QScrollBar::add-line:vertical,
QScrollArea#postgameOverviewScroll QScrollBar::sub-line:vertical,
QScrollArea#postgameOverviewScroll QScrollBar::add-page:vertical,
QScrollArea#postgameOverviewScroll QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0px;
    border: none;
}

QFrame#postgamePlayerCard {
    background: rgba(12, 22, 40, 225);
}

QFrame#postgamePlayerCard:hover {
    background: rgba(20, 36, 62, 235);
}

QLabel#postgameChampionIcon {
    border: none;
    background: transparent;
    color: #eef4ff;
    font-size: 13px;
    font-weight: 800;
}

QLabel#postgameChampionName {
    color: #f2f7ff;
    font-size: 12px;
    font-weight: 800;
    border: none;
}

QLabel#postgameResultFlag {
    border: none;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 900;
    padding: 0px 4px;
    min-width: 12px;
}

QLabel#postgameResultFlag[result="win"] {
    color: #06251a;
    background: #4ade80;
}

QLabel#postgameResultFlag[result="loss"] {
    color: #2a0b0f;
    background: #f07d8a;
}

QLabel#postgameRoleBadge {
    color: #d9ae4f;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 0.5px;
    min-height: 14px;
    border: none;
    background: transparent;
}

QLabel#postgameLevelBadge {
    color: #9fb4d4;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 0.5px;
    min-height: 14px;
    border: none;
    background: transparent;
}

QFrame#postgameKdaPill {
    border: 1px solid rgba(97, 148, 211, 90);
    border-radius: 7px;
    background: rgba(8, 17, 31, 205);
}

QLabel#postgameKdaCaption {
    color: #7f93b1;
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 1px;
    border: none;
}

QLabel#postgameStatKda {
    font-size: 12px;
    font-weight: 900;
    border: none;
}

QFrame#postgameCardDivider {
    border: none;
    background: rgba(97, 148, 211, 60);
    max-height: 1px;
}

QFrame#postgameStatChip {
    border: 1px solid rgba(97, 148, 211, 60);
    border-radius: 7px;
    background: rgba(16, 32, 54, 200);
}

QLabel#postgameStatCaption {
    color: #8fa2bd;
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 1px;
    border: none;
}

QLabel#postgameStatCs,
QLabel#postgameStatGold,
QLabel#postgameStatVision {
    font-size: 12px;
    font-weight: 900;
    border: none;
}

QLabel#postgameBuildCaption {
    color: #7f93b1;
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 1px;
    border: none;
}

QLabel#postgameBuildCount {
    color: #6f83a1;
    font-size: 8px;
    font-weight: 800;
    border: none;
}

QLabel#postgameItemIcon {
    border: 1px solid rgba(97, 148, 211, 70);
    border-radius: 5px;
    background: rgba(10, 20, 34, 230);
    color: #9fb4d4;
    font-size: 9px;
    font-weight: 800;
}

QLabel#postgameItemIcon[filled="0"] {
    border: 1px dashed rgba(97, 148, 211, 55);
    background: rgba(10, 20, 34, 140);
    color: rgba(120, 140, 170, 140);
}

"""
