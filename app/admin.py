"""Active administration endpoints mounted by app.main."""

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
    """Yield a database session scoped to one admin request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class WebsiteSchema(BaseModel):
    """Validated fields used to create or replace a website source."""

    url: str
    company_name: str
    category: str
    active: bool = True
    keywords: str = ""
    location: str = ""
    custom_config: str = "{}"

class CitySchema(BaseModel):
    """Validated fields used to create or replace a city."""

    city_name: str
    latitude: float
    longitude: float
    active: bool = True

class BulkActiveUpdate(BaseModel):
    """Request body for toggling a collection of websites or cities."""

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
    """Return all configured website sources."""
    return db.query(Website).all()

@router.put("/websites/bulk/active")
def bulk_update_websites_active(update: BulkActiveUpdate, db: Session = Depends(get_db)):
    """Set the active flag for the requested website IDs."""
    updated = db.query(Website).filter(Website.id.in_(update.ids)).update(
        {Website.active: update.active}, synchronize_session=False
    )
    db.commit()
    return {"message": f"Updated {updated} websites", "updated": updated}

@router.get("/websites/{website_id}")
def get_website(website_id: int, db: Session = Depends(get_db)):
    """Return one website source or a 404 response."""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    return website

@router.post("/websites")
def add_website(website: WebsiteSchema, db: Session = Depends(get_db)):
    """Create a website source from the validated request body."""
    db_site = Website(**website.model_dump())
    db.add(db_site)
    db.commit()
    db.refresh(db_site)
    return db_site

@router.put("/websites/{website_id}")
def update_website(website_id: int, website: WebsiteSchema, db: Session = Depends(get_db)):
    """Replace all editable fields of a website source."""
    db_site = db.query(Website).filter(Website.id == website_id).first()
    if not db_site:
        raise HTTPException(status_code=404, detail="Website not found")
    
    for key, value in website.model_dump().items():
        setattr(db_site, key, value)
    
    db.commit()
    db.refresh(db_site)
    return db_site

@router.delete("/websites/{website_id}")
def delete_website(website_id: int, db: Session = Depends(get_db)):
    """Delete the website source with the supplied ID."""
    db.query(Website).filter(Website.id == website_id).delete()
    db.commit()
    return {"message": "Website deleted"}

@router.get("/cities")
def list_cities(db: Session = Depends(get_db)):
    """Return all configured cities and their coordinates."""
    return db.query(City).all()

@router.put("/cities/bulk/active")
def bulk_update_cities_active(update: BulkActiveUpdate, db: Session = Depends(get_db)):
    """Set the active flag for the requested city IDs."""
    updated = db.query(City).filter(City.id.in_(update.ids)).update(
        {City.active: update.active}, synchronize_session=False
    )
    db.commit()
    return {"message": f"Updated {updated} cities", "updated": updated}

@router.get("/cities/{city_id}")
def get_city(city_id: int, db: Session = Depends(get_db)):
    """Return one city or a 404 response."""
    city = db.query(City).filter(City.id == city_id).first()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    return city

@router.post("/cities")
def add_city(city: CitySchema, db: Session = Depends(get_db)):
    """Create a city from the validated request body."""
    db_city = City(**city.model_dump())
    db.add(db_city)
    db.commit()
    db.refresh(db_city)
    return db_city

@router.put("/cities/{city_id}")
def update_city(city_id: int, city: CitySchema, db: Session = Depends(get_db)):
    """Replace all editable fields of a city."""
    db_city = db.query(City).filter(City.id == city_id).first()
    if not db_city:
        raise HTTPException(status_code=404, detail="City not found")
    
    for key, value in city.model_dump().items():
        setattr(db_city, key, value)
    
    db.commit()
    db.refresh(db_city)
    return db_city

@router.delete("/cities/{city_id}")
def delete_city(city_id: int, db: Session = Depends(get_db)):
    """Delete the city with the supplied ID."""
    db.query(City).filter(City.id == city_id).delete()
    db.commit()
    return {"message": "City deleted"}

@router.post("/scrape-now")
def trigger_manual_scrape(background_tasks: BackgroundTasks):
    """Queue the scraper suite unless another run is already active."""
    try:
        if not mark_scrape_queued():
            return {"message": "Scraping process is already running", "status": get_scrape_status()}
        background_tasks.add_task(run_all_scrapers, True)
        return {"message": "Scraping process started in background", "status": get_scrape_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scrape-status")
def scrape_status():
    """Return the in-memory progress of the current or most recent scrape."""
    return get_scrape_status()


@router.post("/shutdown")
def shutdown_app():
    """Stop the local background web application process."""
    logger.info("Shutdown requested from admin page.")
    Timer(0.5, lambda: os._exit(0)).start()
    return {"message": "Healthcare HR Job Aggregator is shutting down"}
