"""SQLAlchemy models, SQLite setup, migration, and initial data."""

from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import json
from config.settings import settings

Base = declarative_base()

class City(Base):
    """A named geographic point used by the location matcher."""

    __tablename__ = "cities"
    id = Column(Integer, primary_key=True)
    city_name = Column(String, unique=True, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    active = Column(Boolean, default=True)

    def __repr__(self):
        """Return a compact diagnostic representation of the city."""
        return f"<City(name='{self.city_name}', lat={self.latitude}, lon={self.longitude})>"

class Website(Base):
    """A configured job listing source and its scraper-specific settings."""

    __tablename__ = "websites"
    id = Column(Integer, primary_key=True)
    url = Column(String, nullable=False)
    company_name = Column(String, nullable=False)
    category = Column(String, default="company_local") # aggregator, company_nationwide, company_local
    active = Column(Boolean, default=True)
    keywords = Column(Text, nullable=True) # JSON or comma-separated
    location = Column(String, nullable=True)
    custom_config = Column(Text, nullable=True) # JSON field for scraper rules

    def __repr__(self):
        """Return a compact diagnostic representation of the source."""
        return f"<Website(name='{self.company_name}', url='{self.url}')>"

class JobOffer(Base):
    """A collected job listing associated with its source and application status."""

    __tablename__ = "job_offers"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    company_name = Column(String)
    location = Column(String)
    url = Column(String, unique=True, nullable=False)
    offer_info = Column(Text, nullable=True)
    score = Column(Integer, default=0)
    url_hash = Column(String, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    status = relationship("OfferStatus", back_populates="offer", uselist=False)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=True)
    website = relationship("Website")

    def __repr__(self):
        """Return a compact diagnostic representation of the offer."""
        return f"<JobOffer(title='{self.title}', company='{self.company_name}')>"

class OfferStatus(Base):
    """User-managed application status and notes for one job offer."""

    __tablename__ = "offer_status"
    id = Column(Integer, primary_key=True)
    offer_id = Column(Integer, ForeignKey("job_offers.id"))
    status = Column(String, default="new") # new, cv_sent, replied, interview, archived
    notes = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    offer = relationship("JobOffer", back_populates="status")

    def __repr__(self):
        """Return a compact diagnostic representation of the application status."""
        return f"<OfferStatus(offer_id={self.offer_id}, status='{self.status}')>"

# Database Engine
engine = create_engine(f"sqlite:///{settings.DB_PATH}")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Create tables, apply supported SQLite migrations, and seed empty tables."""
    Base.metadata.create_all(bind=engine)
    migrate_db()
    seed_data()

def migrate_db():
    """Apply lightweight SQLite migrations for existing local databases."""
    inspector = inspect(engine)
    if "job_offers" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("job_offers")}
    with engine.begin() as connection:
        if "offer_info" not in existing_columns:
            connection.execute(text("ALTER TABLE job_offers ADD COLUMN offer_info TEXT"))

def seed_data():
    """Insert the initial cities and websites when their tables are empty."""
    db = SessionLocal()
    # Seed Cities
    if db.query(City).count() == 0:
        cities_data = [
            ('Dobczyce', 49.8787, 20.0886),
            ('Wieliczka', 49.9872, 20.0647), ('Niepołomice', 50.0336, 20.2183),
            ('Bochnia', 49.9686, 20.4302), ('Nowy Wiśnicz', 49.9145, 20.4633),
            ('Myślenice', 49.8326, 19.9397), ('Kraków', 50.0647, 19.9450),
            ('Świątniki Górne', 49.9304, 19.9547), ('Mszana Dolna', 49.6762, 20.0744),
            ('Brzesko', 49.9691, 20.6062), ('Limanowa', 49.7061, 20.4179),
            ('Skawina', 49.9754, 19.8273), ('Proszowice', 50.1919, 20.2882),
            ('Nowe Brzesko', 50.1378, 20.3831), ('Sułkowice', 49.8422, 19.7972)
        ]
        for name, lat, lon in cities_data:
            db.add(City(city_name=name, latitude=lat, longitude=lon))
    
    # Seed Initial Corporate Websites
    if db.query(Website).count() == 0:
        sites = [
            {"url": "https://www.luxmed.pl/kariera/oferty-pracy", "name": "LUX MED", "cat": "company_nationwide"},
            {"url": "https://www.medicover.pl/praca/", "name": "Medicover", "cat": "company_nationwide"},
            {"url": "https://enel.pl/kariera", "name": "Enel-Med", "cat": "company_nationwide"},
            {"url": "https://scanmed.pl/kariera", "name": "Scanmed", "cat": "company_nationwide"},
            {"url": "https://www.synevo.pl/o-nas/kariera/oferty-pracy/", "name": "Synevo", "cat": "company_nationwide"},
            {"url": "https://kariera.alablaboratoria.pl/oferty-pracy/", "name": "ALAB laboratoria", "cat": "company_nationwide"},
            {"url": "https://www.affidea.pl/pl-PL/kariera-w-affidea/", "name": "Affidea", "cat": "company_nationwide"},
            {"url": "https://pracodawcy.pracuj.pl/company/20426386", "name": "Allmedica", "cat": "pracuj.pl", "location": "Krak\u00f3w"},
            {"url": "https://centrum-radioterapii.pl/kariera/", "name": "Amethyst Centrum Radioterapii", "cat": "company_local"},
            {"url": "https://medicina.pl/kariera/", "name": "SCDZ Medicina", "cat": "company_local"},
            {"url": "https://dworska.pl/kontakt-krakow/kariera", "name": "Szpital Dworska", "cat": "company_local"},
            {"url": "https://krakow.nio.gov.pl/praca/", "name": "NIO Kraków", "cat": "company_local"},
            {"url": "https://www.su.krakow.pl/kariera/oferty-pracy", "name": "Szpital Uniwersytecki", "cat": "company_local", "custom_config": "{\"card_selector\": \"div.cat-item\", \"title_selector\": \"h2 a\"}"},
            {"url": "https://szpitalrydygier.pl/bip/oferty-pracy/", "name": "Szpital Rydygiera", "cat": "company_local"},
            {"url": "https://www.olx.pl/praca/", "name": "OLX", "cat": "aggregator"},
            {"url": "https://www.pracuj.pl/", "name": "Pracuj.pl", "cat": "aggregator"},
            {"url": "https://enel.pl/kariera/oferty-pracy", "name": "enel-med", "cat": "company_nationwide"}
        ]
        for s in sites:
            db.add(Website(
                url=s["url"],
                company_name=s["name"],
                category=s["cat"],
                custom_config=s.get("custom_config"),
                location=s.get("location"),
                keywords=s.get("keywords")
            ))

    allmedica = db.query(Website).filter(Website.company_name == "Allmedica").first()
    if allmedica:
        allmedica.url = "https://pracodawcy.pracuj.pl/company/20426386"
        allmedica.category = "pracuj.pl"
        allmedica.custom_config = None
        allmedica.location = allmedica.location or "Krak\u00f3w"
    
    db.commit()
    db.close()
