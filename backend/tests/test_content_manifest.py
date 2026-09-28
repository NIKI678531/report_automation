from copy import deepcopy

from app.domain.document import checksum, content_manifests_match, render_content_manifest
from app.rendering.disclaimer import DISCLAIMER_CHECKSUM, DISCLAIMER_VERSION


def _content() -> dict:
    return {
        "language_mode": "EN",
        "module_bindings": {"analytics": "snapshot-1"},
        "sections": {
            "historical_performance": {"rows": [{"name": "Fund", "return_1m": "0.01"}]},
            "company_news": [{"title": "Approved news", "summary": "Approved summary"}],
            "constituents": [{"security_code": "700", "weight": "0.10"}],
            "analytics": {"top10": [{"security_code": "700", "weight": "0.10"}]},
            "footnotes": {"historical": "As of month end."},
        },
        "next_rebalancing_date": "2026-09-07",
    }


def test_content_manifest_accepts_legacy_english_schema() -> None:
    current = render_content_manifest(_content())
    legacy = {key: value for key, value in current.items() if key not in {"checksum", "language_mode"}}
    legacy["checksum"] = checksum(legacy)

    assert legacy["checksum"] != current["checksum"]
    assert content_manifests_match(legacy, current)


def test_content_manifest_still_rejects_real_cross_format_drift() -> None:
    expected = render_content_manifest(_content())
    drifted = deepcopy(expected)
    drifted["section_checksums"]["company_news"] = "different-content"
    drifted["checksum"] = checksum({key: value for key, value in drifted.items() if key != "checksum"})

    assert not content_manifests_match(expected, drifted)


def test_content_manifest_does_not_treat_legacy_manifest_as_non_english() -> None:
    current = render_content_manifest({**_content(), "language_mode": "ZH_HANS"})
    legacy = {key: value for key, value in current.items() if key not in {"checksum", "language_mode"}}
    legacy["checksum"] = checksum(legacy)

    assert not content_manifests_match(legacy, current)


def test_manifest_without_fixed_disclaimer_identity_does_not_match_current_export() -> None:
    legacy = render_content_manifest(_content())
    current = {key: value for key, value in legacy.items() if key != "checksum"}
    current.update({
        "disclaimer_version": DISCLAIMER_VERSION,
        "disclaimer_checksum": DISCLAIMER_CHECKSUM,
    })
    current["checksum"] = checksum(current)

    assert not content_manifests_match(legacy, current)
