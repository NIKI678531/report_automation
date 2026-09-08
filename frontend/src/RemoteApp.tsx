import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import App from "./App";
import { LocaleProvider } from "./i18n";
import { REMOTE_BASE } from "./remoteConfig";
import tokens from "./styles/tokens.css?inline";
import styles from "./styles.css?inline";
import grid from "react-grid-layout/css/styles.css?inline";
import resize from "react-resizable/css/styles.css?inline";
import inter400 from "@fontsource/inter/latin-400.css?inline";
import inter500 from "@fontsource/inter/latin-500.css?inline";
import inter600 from "@fontsource/inter/latin-600.css?inline";
import inter700 from "@fontsource/inter/latin-700.css?inline";
import mono500 from "@fontsource/roboto-mono/latin-500.css?inline";

const fonts = [inter400, inter500, inter600, inter700, mono500].join("\n");
const surfaceCss = [tokens, grid, resize, styles].join("\n");

/** Webpack host calls container.get('./App') and renders the default component. */
export default function RemoteApp({ standalone = false }: { standalone?: boolean }) {
  const element = useRef<HTMLDivElement>(null);
  const [shadow, setShadow] = useState<ShadowRoot | null>(null);
  useLayoutEffect(() => {
    const target = element.current!;
    setShadow(target.shadowRoot ?? target.attachShadow({ mode: "open" }));
    // Register fonts in the document; this sheet has no element selectors.
    const fontSheet = document.createElement("style");
    fontSheet.dataset.fundCmtFonts = "";
    fontSheet.textContent = fonts;
    document.head.append(fontSheet);
    return () => fontSheet.remove();
  }, []);
  return <div ref={element} data-fund-cmt-auto="">
    {shadow && createPortal(<>
      <style>{surfaceCss}</style>
      <div className="fund-cmt-surface">
        <LocaleProvider manageDocumentLanguage={standalone}>
          <App embedded={!standalone} basename={REMOTE_BASE} />
        </LocaleProvider>
      </div>
    </>, shadow)}
  </div>;
}
