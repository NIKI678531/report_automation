from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.domain.models import ProductCatalog
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
            product_code="TEST",
            ticker="TEST.HK",
            name_en="Synthetic Test Fund",
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
        session.commit()
    app = create_app()

    def override_db():
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
