from __future__ import annotations


CONTROL_WINDOW_STYLE = """
QMainWindow,
QWidget#mainPages,
QWidget#centralWidget,
QWidget#livePage,
QWidget#homePage,
QWidget#settingsPage,
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
    border: 1px solid rgba(128, 167, 215, 125);
    border-radius: 4px;
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
QPushButton#secondaryButton {
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

QScrollArea#savedGamesScroll {
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
    border: 1px solid rgba(86, 126, 179, 100);
    border-radius: 10px;
    background: rgba(6, 15, 29, 170);
}

QFrame#savedGameRow:hover {
    border: 1px solid rgba(217, 174, 79, 190);
    background: rgba(15, 29, 50, 215);
}

QLabel#savedGameTitle {
    color: #eef4ff;
    font-size: 14px;
    font-weight: 800;
}

QLabel#savedGameDetail {
    color: #a8bbd5;
    font-size: 11px;
}

QLabel#savedGameSync {
    font-size: 10px;
    font-weight: 700;
}

QLabel#savedGameSync[state="live_only"] {
    color: #d9ae4f;
}

QLabel#savedGameSync[state="pending"] {
    color: #d9ae4f;
}

QLabel#savedGameSync[state="synced"] {
    color: #64d9a3;
}

QLabel#savedGameSync[state="failed"] {
    color: #ff7081;
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

"""
