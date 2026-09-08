import React, { Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, Route, Routes } from 'host-react-router-dom';

// Same classic-script + init/get contract as the provided host at b33ca51.
const Remote = React.lazy(async () => {
  await new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.type = 'text/javascript';
    script.crossOrigin = 'anonymous';
    script.src = `${new URLSearchParams(location.search).get('remoteOrigin') || ''}/remote/fund-cmt-auto/remoteEntry.js?v=contract`;
    script.onload = resolve;
    script.onerror = reject;
    document.head.append(script);
  });
  await __webpack_init_sharing__('default');
  await window.fundCmtAuto.init(__webpack_share_scopes__.default);
  const factory = await window.fundCmtAuto.get('./App');
  window.contractShareScope = __webpack_share_scopes__.default;
  return factory();
});

const root = createRoot(document.getElementById('root'));
root.render(<React.StrictMode><BrowserRouter>
  <nav><Link to="/host-home">Host home</Link><Link to="/fund-cmt-auto">Fund commentary</Link></nav>
  <button id="host-control">Host control</button>
  <Routes>
    <Route path="/fund-cmt-auto/*" element={<Suspense fallback="Loading remote"><Remote i18n={{ language: 'fr' }} auth={{}} /></Suspense>} />
    <Route path="/host-home" element={<h1>Host home</h1>} />
  </Routes>
</BrowserRouter></React.StrictMode>);
