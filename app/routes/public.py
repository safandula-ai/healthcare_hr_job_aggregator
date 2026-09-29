"""Legacy unmounted copy of offer endpoints; active routes are in app.public."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional
from models.database import SessionLocal, JobOffer, OfferStatus, Website
from pydantic import BaseModel
from utils.profile_matcher import ProfileMatcher

router = APIRouter(tags=["Public"])

# Dependency to get DB session
def get_db():
    """Yield a database session for one legacy public request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class StatusUpdate(BaseModel):
    """Request body for updating one offer's application status."""

    status: str
    notes: Optional[str] = None

class BulkStatusUpdate(BaseModel):
    """Request body for applying one status to multiple offers."""

    offer_ids: List[int]
    status: str

def _match_text(offer: JobOffer) -> str:
    """Combine searchable fields from an offer."""
    return " ".join(
        part for part in [offer.title, offer.company_name, offer.location, offer.offer_info] if part
    )

def _offer_list_item(offer: JobOffer, matcher: ProfileMatcher) -> dict:
    """Serialize an offer and calculate its current match score."""
    source = offer.website
    return {
        "id": offer.id,
        "title": offer.title,
        "company_name": offer.company_name,
        "source_name": source.company_name if source else None,
        "source_category": source.category if source else None,
        "location": offer.location,
        "url": offer.url,
        "offer_info": offer.offer_info,
        "score": matcher.calculate_score(_match_text(offer), location_text=offer.location),
        "created_at": offer.created_at,
        "scraped_at": offer.scraped_at,
        "website_id": offer.website_id,
        "status": offer.status,
    }

def _status_query(db: Session, status: str, source: Optional[str] = None, company: Optional[str] = None):
    """Build a query filtered by status, source, and employer."""
    source = source.strip() if isinstance(source, str) and source.strip() else None
    company = company.strip() if isinstance(company, str) and company.strip() else None
    query = (
        db.query(JobOffer)
        .join(OfferStatus)
        .outerjoin(Website, JobOffer.website_id == Website.id)
        .filter(OfferStatus.status == status)
    )
    if source:
        query = query.filter(Website.company_name.ilike(f"%{source}%"))
    if company:
        query = query.filter(JobOffer.company_name.ilike(f"%{company}%"))
    return query

def _apply_score_filters(
    items: list[dict],
    min_score: Optional[int],
    max_score: Optional[int],
    zero_score: bool = False,
) -> list[dict]:
    """Filter serialized offers by score or the zero-score view."""
    if zero_score:
        return [item for item in items if item["score"] < 1]
    items = [item for item in items if item["score"] >= 1]
    if min_score is not None:
        items = [item for item in items if item["score"] >= min_score]
    if max_score is not None:
        items = [item for item in items if item["score"] <= max_score]
    return items

def _sort_items(items: list[dict], sort: str) -> list[dict]:
    """Sort serialized offers by date or match score."""
    def date_bucket(item: dict):
        """Return a sortable date value from the offer's creation timestamp."""
        created_at = item["created_at"]
        return created_at.date() if hasattr(created_at, "date") else created_at

    if sort == "score_asc":
        return sorted(items, key=lambda item: (item["score"], item["created_at"]))
    if sort == "score_desc":
        return sorted(items, key=lambda item: (item["score"], item["created_at"]), reverse=True)
    if sort == "date_asc":
        return sorted(items, key=lambda item: item["created_at"])
    return sorted(items, key=lambda item: (date_bucket(item), item["score"], item["created_at"]), reverse=True)

@router.get("/offer-filter-options")
def get_offer_filter_options(db: Session = Depends(get_db)):
    """Distinct values used by dashboard filter dropdowns."""
    sources = [
        row[0]
        for row in (
            db.query(Website.company_name)
            .join(JobOffer, JobOffer.website_id == Website.id)
            .filter(Website.company_name.isnot(None))
            .distinct()
            .order_by(func.lower(Website.company_name))
            .all()
        )
        if row[0]
    ]
    companies = [
        row[0]
        for row in (
            db.query(JobOffer.company_name)
            .filter(JobOffer.company_name.isnot(None))
            .filter(JobOffer.company_name != "")
            .distinct()
            .order_by(func.lower(JobOffer.company_name))
            .all()
        )
        if row[0]
    ]
    return {"sources": sources, "companies": companies}

@router.get("/offers")
def get_offers(
    status: str = "new",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1),
    sort: str = Query("date_desc"),
    min_score: Optional[int] = Query(None, ge=0, le=100),
    max_score: Optional[int] = Query(None, ge=0, le=100),
    source: Optional[str] = Query(None),
    company: Optional[str] = Query(None),
    zero_score: bool = Query(False),
    db: Session = Depends(get_db)
):
    """Paginated list of job offers filtered by status."""
    sort = sort if isinstance(sort, str) else "date_desc"
    min_score = min_score if isinstance(min_score, int) else None
    max_score = max_score if isinstance(max_score, int) else None
    offset = (page - 1) * size
    matcher = ProfileMatcher()
    statuses = ["new", "zero", "cv_sent", "replied", "interview", "archived"]

    status_counts = {}
    for status_name in statuses:
        query_status = "new" if status_name == "zero" else status_name
        status_offers = _status_query(db, query_status, source=source, company=company).all()
        status_items = [_offer_list_item(offer, matcher) for offer in status_offers]
        status_counts[status_name] = len(_apply_score_filters(
            status_items,
            min_score,
            max_score,
            zero_score=(status_name == "zero"),
        ))

    query_status = "new" if status == "zero" else status
    offers = _status_query(db, query_status, source=source, company=company).all()
    items = [_offer_list_item(offer, matcher) for offer in offers]
    items = _apply_score_filters(items, min_score, max_score, zero_score=(status == "zero" or zero_score))
    items = _sort_items(items, sort)
    total = len(items)
    page_items = items[offset:offset + size]
    return {
        "total": total,
        "status_counts": status_counts,
        "page": page,
        "size": size,
        "offers": page_items,
    }

@router.get("/offers/{offer_id}")
def get_offer_detail(offer_id: int, db: Session = Depends(get_db)):
    """Get full details of a specific job offer."""
    offer = db.query(JobOffer).filter(JobOffer.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    matcher = ProfileMatcher()
    match_details = matcher.get_match_details(_match_text(offer), location_text=offer.location)
    source = offer.website
    return {
        "id": offer.id,
        "title": offer.title,
        "company_name": offer.company_name,
        "source_name": source.company_name if source else None,
        "source_category": source.category if source else None,
        "location": offer.location,
        "url": offer.url,
        "offer_info": offer.offer_info,
        "score": match_details["score"],
        "created_at": offer.created_at,
        "scraped_at": offer.scraped_at,
        "website_id": offer.website_id,
        "status": {
            "status": offer.status.status if offer.status else None,
            "notes": offer.status.notes if offer.status else None,
            "updated_at": offer.status.updated_at if offer.status else None,
        },
        "match_details": match_details,
    }

@router.put("/offers/{offer_id}")
def update_offer_status(offer_id: int, update: StatusUpdate, db: Session = Depends(get_db)):
    """Update the application status of a single offer."""
    status_rec = db.query(OfferStatus).filter(OfferStatus.offer_id == offer_id).first()
    if not status_rec:
        raise HTTPException(status_code=404, detail="Status record not found")
    
    status_rec.status = update.status
    if update.notes is not None:
        status_rec.notes = update.notes
    
    db.commit()
    return {"message": "Status updated successfully"}

@router.put("/offers/bulk/status")
def bulk_update_status(update: BulkStatusUpdate, db: Session = Depends(get_db)):
    """Update status for multiple offers at once."""
    db.query(OfferStatus).filter(OfferStatus.offer_id.in_(update.offer_ids)).update(
        {OfferStatus.status: update.status}, synchronize_session=False
    )
    db.commit()
    return {"message": f"Updated {len(update.offer_ids)} offers"}
