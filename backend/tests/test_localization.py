from app.domain.localization import (
    ZH_HANS,
    ZH_HANT,
    chinese_content_warnings,
    localized_source_text,
    simplified_to_traditional,
    term,
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


def test_traditional_chinese_prefers_explicit_value_then_hong_kong_opencc_and_never_english():
    assert localized_source_text(
        language_mode=ZH_HANT,
        en="Tencent Holdings",
        zh_hans="腾讯控股",
        zh_hant="騰訊控股",
    ) == ("騰訊控股", "SOURCE_ZH_HANT")
    assert localized_source_text(
        language_mode=ZH_HANT,
        en="Tencent Holdings",
        zh_hans="腾讯控股",
    ) == ("騰訊控股", "OPENCC_S2T")
    assert localized_source_text(language_mode=ZH_HANT, en="Tencent Holdings") == ("", "MISSING")
    assert simplified_to_traditional("软件后台与网络") == "軟件後台與網絡"


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


def test_report_headings_use_the_product_ticker_in_all_languages():
    expected = {
        "EN": (
            "The Performance of 3033.HK Constituents",
            "Top 10 3033.HK Constituents*",
            "3033.HK Sectors Breakdown*",
        ),
        ZH_HANS: ("3033.HK 成分股表现", "3033.HK 十大成分股*", "3033.HK 行业分布*"),
        ZH_HANT: ("3033.HK 成分股表現", "3033.HK 十大成分股*", "3033.HK 行業分佈*"),
    }

    for language_mode, headings in expected.items():
        assert (
            term("constituent_performance", language_mode, product="3033.HK"),
            term("top10", language_mode, product="3033.HK"),
            term("sector_breakdown", language_mode, product="3033.HK"),
        ) == headings
