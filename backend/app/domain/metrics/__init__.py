"""Pure, deterministic report metrics, split by the report module that consumes them.

This was one 578-line ``domain/calculation.py`` sitting next to ``domain/service/calculations.py``,
a pair of names that gave no clue which one was the arithmetic and which one the orchestration.
The arithmetic now lives here, one file per report module, so an import states which page of the
report it feeds:

===========================  ====================================================
Module file                  Report module (see ``frontend/src/reportModules.ts``)
===========================  ====================================================
``historical_performance``   02 Historical Performance
``constituent_performance``  04 Constituent Performance
``industry_breakdown``       the donut inside 05 Final Analytics
``final_analytics``          05 Final Analytics
``footnotes``                06 Footnotes & Disclosures
===========================  ====================================================

01 Review and 03 Company News have no arithmetic: Review is editorial prose bound in
``domain/document.py``, and news selection is session-bound work in ``domain/service/news.py``.
Neither gets an empty file here.

Three supporting modules are not report modules and are named so they cannot be mistaken for one:
``errors`` (:class:`CalculationError`), ``formatting`` (the versioned display profile) and
``fund_kpis`` (the shared trading-day / AUM / turnover readers that both ``final_analytics`` and
``quality_checks`` derive from — they used to be computed twice, which let the quality check and
the persisted metric disagree). ``quality_checks`` holds the QC and KPI gate, which spans modules
and therefore belongs to none of them.

Nothing here touches a database or a session. Every function takes a payload and returns a value,
and each is versioned by the ``formula_version`` its caller supplies. The session-bound half —
reading the active snapshot, persisting ``MetricValue`` / ``ModuleSnapshot`` / ``QualityCheckResult``
rows with lineage — is ``domain/service/calculations.py``.

Import from the specific module (``from ..metrics.footnotes import build_lineage_footnotes``)
rather than from this package. There is deliberately no flat re-export: a caller should have to
say which report module's arithmetic it depends on.
"""
