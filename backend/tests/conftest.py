from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.domain.models import MappingProfile, ProductCatalog
from app.main import create_app


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with TestingSession() as session:
        session.add(ProductCatalog(
            product_code="3033",
            ticker="3033.HK",
            name_en="CSOP Hang Seng TECH Index ETF",
            name_zh_hant="南方東英恒生科技指數ETF",
            constituent_index_code="HSTECH",
            constituent_index_name="Hang Seng TECH Index",
            benchmark_instrument_code="HSTECHN",
            benchmark_instrument_name="HSTECHN Index",
            benchmark_code="HSTECH",
            benchmark_name="Hang Seng TECH Index",
            valid_from=date(2020, 8, 28),
            template_version="3033-v2",
            design_token_version="3033-v2",
            expected_constituent_count=30,
            formula_profile="hstech-2026.1",
            display_order=10,
            source="TEST_FIXTURE",
        ))
        session.add(ProductCatalog(
            product_code="3037",
            ticker="3037.HK",
            name_en="CSOP Hang Seng Index ETF",
            constituent_index_code="HSI",
            constituent_index_name="Hang Seng Index",
            benchmark_instrument_code="HSI",
            benchmark_instrument_name="Hang Seng Index",
            benchmark_code="HSI",
            benchmark_name="Hang Seng Index",
            valid_from=date(2026, 1, 1),
            template_version="3033-v2",
            design_token_version="3033-v2",
            expected_constituent_count=None,
            formula_profile="total-return-v1",
            display_order=20,
            source="TEST_FIXTURE",
        ))
        session.add(ProductCatalog(
            product_code="TEST",
            ticker="9999.HK",
            name_en="Synthetic Test Fund",
            constituent_index_code="TESTIDX",
            constituent_index_name="Synthetic Test Index",
            benchmark_instrument_code="TESTTR",
            benchmark_instrument_name="Synthetic Test Total Return Index",
            benchmark_code="TESTIDX",
            benchmark_name="Synthetic Test Index",
            valid_from=date(2025, 1, 1),
            template_version="test-v1",
            design_token_version="test-v1",
            expected_constituent_count=2,
            formula_profile="test-index-v1",
            display_order=999,
            source="TEST_FIXTURE",
        ))
        session.add(ProductCatalog(
            product_code="SLOT",
            ticker="SLOT.HK",
            name_en="Slot Ingestion Test Fund",
            constituent_index_code="SLOTIDX",
            constituent_index_name="Slot Ingestion Test Index",
            benchmark_instrument_code="SLOTTR",
            benchmark_instrument_name="Slot Ingestion Test Total Return Index",
            benchmark_code="SLOTIDX",
            benchmark_name="Slot Ingestion Test Index",
            valid_from=date(2025, 1, 1),
            template_version="test-v1",
            design_token_version="test-v1",
            # Matches backend/tests/fixtures/ingestion/, which samples five real constituents.
            expected_constituent_count=5,
            formula_profile="test-index-v1",
            display_order=998,
            source="TEST_FIXTURE",
        ))
        session.add_all([
            MappingProfile(
                profile_id="hsi_constituent_csv",
                dataset_type="index_constituents",
                source_family="HANG_SENG_INDEXES_EOD",
                selector={"extensions": [".csv"], "required_fields": ["security_code", "weight", "close_price"]},
                field_map={
                    "security_code": {"aliases": ["Lcal Cde"]},
                    "name_en": {"aliases": ["Stk Name_E"]},
                    "name_zh_hant": {"aliases": ["Stk Name_TC"]},
                    "close_price": {"aliases": ["Cls Price"]},
                    "currency": {"aliases": ["Lcal Ccy"]},
                    "weight": {"aliases": ["Pct Idx Wgt"]},
                    "as_of_date": {"aliases": ["Prod Dt"]},
                    "trade_date": {"aliases": ["Tradate"]},
                    "source_industry_code": {"aliases": ["Industry"]},
                    "source_sector_code": {"aliases": ["Sector"]},
                },
                unit_map={"weight": "PERCENT"},
                transforms={},
                semantic_metadata={"taxonomy": "HSICS"},
                version=1,
                status="APPROVED",
                approved_by="test-data-steward",
            ),
            MappingProfile(
                profile_id="bloomberg_constituent_returns",
                dataset_type="constituent_returns",
                source_family="BLOOMBERG_MONTHLY_WORKBOOK",
                selector={
                    "extensions": [".xlsx", ".xlsm"],
                    "required_fields": ["return_1m", "return_3m", "return_6m", "return_ytd"],
                    "header_scan_rows": 12,
                    "period_row_offset": -2,
                    "period_end_column": 1,
                },
                field_map={
                    "security_code": {"confirmed_column": 13},
                    "name_en": {"confirmed_column": 14},
                    "return_1m": {"aliases": ["1-month return (%)"]},
                    "return_3m": {"aliases": ["3-month return (%)"]},
                    "return_6m": {"aliases": ["6-month return (%)"]},
                    "return_ytd": {"aliases": ["YTD return (%)"]},
                },
                unit_map={"returns": "PERCENT"},
                transforms={"security_code": "normalize_security_code"},
                semantic_metadata={"series_type": "TOTAL_RETURN", "duplicate_group_policy": "FIRST_COMPLETE_GROUP"},
                version=1,
                status="APPROVED",
                approved_by="test-data-steward",
            ),
            MappingProfile(
                profile_id="bloomberg_gics_reference",
                dataset_type="sector_mapping",
                source_family="BLOOMBERG_GICS_REFERENCE",
                selector={"extensions": [".xlsx", ".xlsm", ".csv"], "required_fields": ["security_code", "sector"], "header_scan_rows": 12},
                field_map={
                    "security_code": {"aliases": ["Code"]},
                    "sector": {"aliases": ["GICS_SECTOR_NAME"]},
                },
                unit_map={},
                transforms={"security_code": "normalize_security_code"},
                semantic_metadata={"taxonomy": "GICS", "reference_only": True},
                version=1,
                status="APPROVED",
                approved_by="test-data-steward",
            ),
            MappingProfile(
                profile_id="approved_sector_overrides",
                dataset_type="sector_overrides",
                source_family="APPROVED_MANUAL_OVERRIDE",
                selector={"extensions": [".csv"], "required_fields": ["security_code", "sector", "reason", "source"]},
                field_map={
                    "security_code": {"aliases": ["security_code"]},
                    "sector": {"aliases": ["sector"]},
                    "reason": {"aliases": ["reason"]},
                    "source": {"aliases": ["source"]},
                },
                unit_map={},
                transforms={"security_code": "normalize_security_code"},
                semantic_metadata={"reference_only": True},
                version=1,
                status="APPROVED",
                approved_by="test-data-steward",
            ),
        ])
        session.commit()
    app = create_app()

    def override_db():
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
