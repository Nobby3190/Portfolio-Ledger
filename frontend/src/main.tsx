import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
// Bundled so the numerals keep their face offline.
import '@fontsource-variable/bricolage-grotesque/standard.css';
import '@fontsource-variable/orbitron/wght.css';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
