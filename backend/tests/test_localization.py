from app.domain.localization import (
    ZH_HANS,
    chinese_content_warnings,
    localized_source_text,
    traditional_to_simplified,
)


def test_simplified_chinese_prefers_explicit_value_then_opencc_and_never_english():
    assert localized_source_text(
        language_mode=ZH_HANS,
        en="Tencent Holdings",
        zh_hans="腾讯控股",
        zh_hant="騰訊控股",
    ) == ("腾讯控股", "SOURCE_ZH_HANS")
    assert localized_source_text(
        language_mode=ZH_HANS,
        en="Tencent Holdings",
        zh_hant="騰訊控股",
    ) == ("腾讯控股", "OPENCC_T2S")
    assert localized_source_text(language_mode=ZH_HANS, en="Tencent Holdings") == ("", "MISSING")
    assert traditional_to_simplified("資訊科技與網絡") == "资讯科技与网络"


def test_missing_chinese_editorial_is_a_non_blocking_warning():
    document = {
        "language_mode": ZH_HANS,
        "sections": {
            "month_in_review": {"blocks": [{"content": ""}]},
            "company_news": [{"title": "", "summary": ""}],
        },
    }

    warning = chinese_content_warnings(document)[0]

    assert warning["severity"] == "WARNING"
    assert warning["status"] == "WARNING"
    assert warning["actual"]["missing_fields"] == [
        "sections.month_in_review.blocks.0.content",
        "sections.company_news.0.title",
        "sections.company_news.0.summary",
        "sections.company_news.0.source_name",
    ]
