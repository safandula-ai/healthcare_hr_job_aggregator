"""Legacy unmounted copy of admin endpoints; active routes are in app.admin."""

import logging
import os
from threading import Timer

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from typing import List
from models.database import SessionLocal, Website, City, JobOffer
from pydantic import BaseModel
from scrapers.run_scrapers import get_scrape_status, mark_scrape_queued, run_all_scrapers

router = APIRouter(tags=["Admin"])
logger = logging.getLogger("admin")

def get_db():
    """Yield a database session for one legacy admin request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class WebsiteSchema(BaseModel):
    """Fields accepted when creating a website source."""

    url: str
    company_name: str
    category: str
    active: bool = True
    keywords: str = ""
    location: str = ""
    custom_config: str = "{}"

class CitySchema(BaseModel):
    """Fields accepted when creating a city."""

    city_name: str
    latitude: float
    longitude: float
    active: bool = True

class BulkActiveUpdate(BaseModel):
    """Request body for changing active flags on multiple records."""

    ids: List[int]
    active: bool

@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Summary statistics for the admin dashboard."""
    return {
        "total_offers": db.query(JobOffer).count(),
        "active_websites": db.query(Website).filter(Website.active == True).count(),
        "active_cities": db.query(City).filter(City.active == True).count()
    }

@router.get("/websites")
def list_websites(db: Session = Depends(get_db)):
    """Return all website sources."""
    return db.query(Website).all()

@router.post("/websites")
def add_website(website: WebsiteSchema, db: Session = Depends(get_db)):
    """Create a website source."""
    db_site = Website(**website.dict())
    db.add(db_site)
    db.commit()
    db.refresh(db_site)
    return db_site

@router.put("/websites/bulk/active")
def bulk_update_websites_active(update: BulkActiveUpdate, db: Session = Depends(get_db)):
    """Set the active flag on the requested website IDs."""
    updated = db.query(Website).filter(Website.id.in_(update.ids)).update(
        {Website.active: update.active}, synchronize_session=False
    )
    db.commit()
    return {"message": f"Updated {updated} websites", "updated": updated}

@router.delete("/websites/{website_id}")
def delete_website(website_id: int, db: Session = Depends(get_db)):
    """Delete a website source by ID."""
    db.query(Website).filter(Website.id == website_id).delete()
    db.commit()
    return {"message": "Website deleted"}

@router.get("/cities")
def list_cities(db: Session = Depends(get_db)):
    """Return all configured cities."""
    return db.query(City).all()

@router.post("/cities")
def add_city(city: CitySchema, db: Session = Depends(get_db)):
    """Create a city record."""
    db_city = City(**city.dict())
    db.add(db_city)
    db.commit()
    db.refresh(db_city)
    return db_city

@router.put("/cities/bulk/active")
def bulk_update_cities_active(update: BulkActiveUpdate, db: Session = Depends(get_db)):
    """Set the active flag on the requested city IDs."""
    updated = db.query(City).filter(City.id.in_(update.ids)).update(
        {City.active: update.active}, synchronize_session=False
    )
    db.commit()
    return {"message": f"Updated {updated} cities", "updated": updated}

@router.post("/scrape-now")
def trigger_manual_scrape(background_tasks: BackgroundTasks):
    """Trigger the full scraper suite as a background task."""
    try:
        if not mark_scrape_queued():
            return {"message": "Scraping process is already running", "status": get_scrape_status()}
        background_tasks.add_task(run_all_scrapers, True)
        return {"message": "Scraping process started in background", "status": get_scrape_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scrape-status")
def scrape_status():
    """Return the current in-memory scraper status."""
    return get_scrape_status()


@router.post("/shutdown")
def shutdown_app():
    """Stop the local background web application process."""
    logger.info("Shutdown requested from admin page.")
    Timer(0.5, lambda: os._exit(0)).start()
    return {"message": "AP Job Aggregator is shutting down"}
