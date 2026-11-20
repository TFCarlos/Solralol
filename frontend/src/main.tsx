import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './pages/App';
import { RecordingReviewWindow } from './pages/RecordingReviewWindow';
import { SoloQDeepAnalysisWindow } from './pages/SoloQDeepAnalysisWindow';
import { LiveOverlayPanel } from './pages/LiveOverlayPanel';
import './styles.css';
import './live-preparation.css';

const reviewId = new URLSearchParams(window.location.search).get('review');
const analysisId = new URLSearchParams(window.location.search).get('analysis');
const overlayPanel = new URLSearchParams(window.location.search).get('overlay');
if (overlayPanel && ['gold','alerts','purchase','recall','ability'].includes(overlayPanel)) {
  document.documentElement.classList.add('live-overlay-document');
  document.body.classList.add('live-overlay-document');
}
createRoot(document.getElementById('root')!).render(overlayPanel && ['gold','alerts','purchase','recall','ability'].includes(overlayPanel) ? <LiveOverlayPanel panel={overlayPanel as 'gold'|'alerts'|'purchase'|'recall'|'ability'} /> : analysisId ? <SoloQDeepAnalysisWindow matchId={analysisId} /> : reviewId ? <RecordingReviewWindow recordingId={reviewId} /> : <React.StrictMode><App /></React.StrictMode>);
