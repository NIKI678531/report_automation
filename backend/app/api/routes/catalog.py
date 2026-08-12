"""Reference data shared across reports: products, the HSICS industry master, mapping profiles.

Every write here is ADMIN-only and versioned rather than edited in place, because a report's
lineage points at the catalog row that was effective on its report date.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from sqlalchemy import or_, select

from app.domain import ingestion, service
from app.domain.industry import parse_industry_master_csv
from app.domain.models import IndustryMasterRecord, MappingProfile, ProductCatalog
from app.domain.products import parse_product_catalog_csv
from app.domain.schemas import (
    MappingProfileCreate,
    MappingProfileRead,
    ProductImportRead,
    ProductRead,
)
from .deps import Db, RequestId

router = APIRouter()


@router.get("/products", response_model=list[ProductRead])
def list_products(db: Db, as_of_date: date | None = None, include_inactive: bool = False) -> list[ProductCatalog]:
    return service.list_products(db, as_of_date or date.today(), include_inactive)


@router.post("/products/import", response_model=ProductImportRead)
async def import_products(
    request: Request,
    db: Db,
    x_request_id: RequestId,
    file: UploadFile = File(...),
) -> dict[str, int]:
    if request.state.principal.role != "ADMIN":
        raise HTTPException(status_code=403, detail={"error_code": "PRODUCT_ADMIN_REQUIRED"})
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail={"error_code": "PRODUCT_CATALOG_FORMAT", "message": "Product catalog must be a CSV file."})
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"error_code": "FILE_TOO_LARGE"})
    try:
        rows = parse_product_catalog_csv(data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error_code": "PRODUCT_CATALOG_INVALID", "message": str(error), "severity": "BLOCKING"}) from error
    return service.import_products(db, rows, x_request_id)


@router.post("/industry-master/import", status_code=status.HTTP_201_CREATED)
async def import_industry_master(
    request: Request,
    db: Db,
    x_request_id: RequestId,
    file: UploadFile = File(...),
) -> dict:
    if request.state.principal.role != "ADMIN":
        raise HTTPException(status_code=403, detail={"error_code": "INDUSTRY_ADMIN_REQUIRED"})
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail={"error_code": "INDUSTRY_MASTER_FORMAT", "message": "Industry master must be a CSV file."})
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"error_code": "FILE_TOO_LARGE"})
    try:
        rows = parse_industry_master_csv(data)
    except (UnicodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail={
            "error_code": "INDUSTRY_MASTER_INVALID",
            "message": str(error),
            "severity": "BLOCKING",
            "fix_hint": "Use the standard HSICS industry-master columns and correct all reported hierarchy errors.",
        }) from error
    return service.import_industry_master(db, rows, x_request_id)


@router.get("/industry-master")
def list_industry_master(db: Db, as_of_date: date | None = None) -> list[dict]:
    query = select(IndustryMasterRecord)
    if as_of_date:
        query = query.where(
            IndustryMasterRecord.valid_from <= as_of_date,
            or_(IndustryMasterRecord.valid_to.is_(None), IndustryMasterRecord.valid_to >= as_of_date),
        )
    rows = db.scalars(query.order_by(IndustryMasterRecord.version, IndustryMasterRecord.level, IndustryMasterRecord.code))
    return [{
        "taxonomy": item.taxonomy,
        "version": item.version,
        "level": item.level,
        "code": item.code,
        "parent_code": item.parent_code,
        "name_en": item.name_en,
        "name_zh_hant": item.name_zh_hant,
        "valid_from": item.valid_from,
        "valid_to": item.valid_to,
        "source": item.source,
        "checksum": item.checksum,
    } for item in rows]


@router.get("/mapping-profiles", response_model=list[MappingProfileRead])
def list_mapping_profiles(db: Db, dataset_type: str | None = None, include_drafts: bool = False) -> list[MappingProfile]:
    query = select(MappingProfile)
    if dataset_type:
        query = query.where(MappingProfile.dataset_type == dataset_type)
    if not include_drafts:
        query = query.where(MappingProfile.status == "APPROVED")
    return list(db.scalars(query.order_by(MappingProfile.dataset_type, MappingProfile.profile_id, MappingProfile.version.desc())))


@router.post("/mapping-profiles", response_model=MappingProfileRead, status_code=status.HTTP_201_CREATED)
def create_mapping_profile(
    request: Request,
    command: MappingProfileCreate,
    db: Db,
    x_request_id: RequestId,
) -> MappingProfile:
    if request.state.principal.role != "ADMIN":
        raise HTTPException(status_code=403, detail={"error_code": "MAPPING_ADMIN_REQUIRED"})
    if ingestion.get_spec(command.dataset_type) is None:
        raise HTTPException(status_code=422, detail={
            "error_code": "UNSUPPORTED_DATASET",
            "message": f"Unknown dataset type '{command.dataset_type}'.",
        })
    required_fields = command.selector.get("required_fields")
    extensions = command.selector.get("extensions")
    if not isinstance(required_fields, list) or not required_fields:
        raise HTTPException(status_code=422, detail={
            "error_code": "MAPPING_SELECTOR_INVALID",
            "message": "selector.required_fields must be a non-empty list.",
        })
    if not isinstance(extensions, list) or not extensions:
        raise HTTPException(status_code=422, detail={
            "error_code": "MAPPING_SELECTOR_INVALID",
            "message": "selector.extensions must be a non-empty list.",
        })
    missing_fields = sorted(set(required_fields) - set(command.field_map))
    if missing_fields:
        raise HTTPException(status_code=422, detail={
            "error_code": "MAPPING_FIELDS_MISSING",
            "message": f"field_map is missing selector fields: {', '.join(missing_fields)}.",
        })
    existing = db.scalar(select(MappingProfile).where(
        MappingProfile.profile_id == command.profile_id,
        MappingProfile.version == command.version,
    ))
    if existing:
        raise HTTPException(status_code=409, detail={
            "error_code": "MAPPING_PROFILE_IMMUTABLE",
            "message": "That mapping profile version already exists.",
            "fix_hint": "Create a new version instead of overwriting an approved mapping.",
        })
    profile = MappingProfile(
        **command.model_dump(),
        approved_by=request.state.principal.subject if command.status == "APPROVED" else None,
    )
    db.add(profile)
    db.flush()
    service.audit(db, "mapping_profile.created", "mapping_profile", profile.id, x_request_id, {
        "profile_id": profile.profile_id,
        "version": profile.version,
        "status": profile.status,
    })
    db.commit()
    db.refresh(profile)
    return profile
