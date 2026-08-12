"""Effective-dated reference data: the product catalog and the HSICS industry master.

Both are approved inputs that exist independently of any one report, so they sit below the
report lifecycle in the dependency order.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import IndustryMasterRecord, ProductCatalog, utcnow
from .audit import audit


def import_industry_master(db: Session, rows: list[dict], request_id: str) -> dict[str, int | str]:
    taxonomy = rows[0]["taxonomy"]
    version = rows[0]["version"]
    valid_from = rows[0]["valid_from"]
    valid_to = rows[0]["valid_to"]
    existing_versions = list(db.scalars(select(IndustryMasterRecord).where(
        IndustryMasterRecord.taxonomy == taxonomy,
        IndustryMasterRecord.version != version,
    )))
    for existing in existing_versions:
        existing_end = existing.valid_to or date.max
        incoming_end = valid_to or date.max
        if valid_from <= existing_end and existing.valid_from <= incoming_end:
            raise HTTPException(status_code=422, detail={
                "error_code": "INDUSTRY_VERSION_OVERLAP",
                "message": f"HSICS version {version} overlaps effective version {existing.version}.",
                "severity": "BLOCKING",
                "fix_hint": "Use non-overlapping valid_from/valid_to ranges for taxonomy versions.",
            })
    created = 0
    unchanged = 0
    for row in rows:
        existing = db.scalar(select(IndustryMasterRecord).where(
            IndustryMasterRecord.taxonomy == row["taxonomy"],
            IndustryMasterRecord.version == row["version"],
            IndustryMasterRecord.level == row["level"],
            IndustryMasterRecord.code == row["code"],
        ))
        if existing:
            if existing.checksum != row["checksum"]:
                raise HTTPException(status_code=409, detail={
                    "error_code": "INDUSTRY_MASTER_IMMUTABLE",
                    "message": f"{row['level']} {row['code']} already exists with different content.",
                    "fix_hint": "Import corrected content under a new taxonomy version.",
                })
            unchanged += 1
            continue
        db.add(IndustryMasterRecord(**row))
        created += 1
    audit(db, "industry_master.imported", "industry_master", version, request_id, {
        "taxonomy": taxonomy, "version": version, "created": created, "unchanged": unchanged,
    })
    db.commit()
    return {"taxonomy": taxonomy, "version": version, "created": created, "unchanged": unchanged}


def list_products(db: Session, as_of_date, include_inactive: bool = False) -> list[ProductCatalog]:
    query = select(ProductCatalog).where(
        ProductCatalog.valid_from <= as_of_date,
        or_(ProductCatalog.valid_to.is_(None), ProductCatalog.valid_to >= as_of_date),
    )
    if not include_inactive:
        query = query.where(ProductCatalog.is_active.is_(True))
    return list(db.scalars(query.order_by(ProductCatalog.display_order, ProductCatalog.name_en)))


def resolve_product(db: Session, product_code: str, report_date) -> ProductCatalog:
    product = db.scalar(
        select(ProductCatalog)
        .where(
            ProductCatalog.product_code == product_code,
            ProductCatalog.is_active.is_(True),
            ProductCatalog.valid_from <= report_date,
            or_(ProductCatalog.valid_to.is_(None), ProductCatalog.valid_to >= report_date),
        )
        .order_by(ProductCatalog.valid_from.desc())
    )
    if not product:
        raise HTTPException(status_code=422, detail={
            "error_code": "PRODUCT_NOT_AVAILABLE",
            "message": f"Product {product_code} is not configured for {report_date.isoformat()}.",
            "severity": "BLOCKING",
            "fix_hint": "Import an approved product catalog entry with an effective date covering the report date.",
        })
    return product


def import_products(db: Session, rows: list[dict], request_id: str) -> dict[str, int]:
    created = 0
    updated = 0
    now = utcnow()
    for row in rows:
        product = db.scalar(select(ProductCatalog).where(
            ProductCatalog.product_code == row["product_code"],
            ProductCatalog.valid_from == row["valid_from"],
        ))
        if product:
            for field, value in row.items():
                setattr(product, field, value)
            product.source_updated_at = now
            updated += 1
        else:
            db.add(ProductCatalog(**row, source_updated_at=now))
            created += 1
    audit(db, "product_catalog.imported", "product_catalog", "approved-import", request_id, {
        "created": created,
        "updated": updated,
        "total": len(rows),
    })
    db.commit()
    return {"created": created, "updated": updated, "total": len(rows)}
