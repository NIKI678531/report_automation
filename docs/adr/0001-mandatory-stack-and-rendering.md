# ADR-0001: Mandatory application stack and rendering source

Status: Accepted

The product frontend is React with TypeScript. The business API is Python FastAPI under `/api/v1`. All report formats consume the same finalized `ReportDocument` and `3033-v1` design-token version. The canonical HTML is the source for browser preview and Chromium PDF printing; DOCX maps the same semantic blocks into editable Word structures.

No authoritative financial calculation is performed in the browser. Replacing React, FastAPI, or the canonical rendering path requires a new ADR and full 3033 regression evidence.
