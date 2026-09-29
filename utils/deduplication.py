"""Detect previously stored offers by their URL."""

import hashlib
from sqlalchemy.orm import Session
from models.database import SessionLocal, JobOffer

class Deduplicator:
    """Detect previously stored offers by hashing their canonical URL string."""

    def __init__(self, db_session: Session = None):
        """Use the supplied session or open a short-lived session per lookup."""
        # If a session is provided, use it. Otherwise, create a new one for utility use.
        self._db_session = db_session

    def _get_db(self):
        """Helper to get a new DB session if not already provided."""
        if self._db_session:
            return self._db_session
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _generate_url_hash(self, url: str) -> str:
        """Return a stable SHA-1 digest used by the database uniqueness check."""
        return hashlib.sha1(url.encode('utf-8')).hexdigest()

    def is_duplicate(self, url: str) -> bool:
        """
        Checks if a job offer with the given URL (or its hash) already exists in the database.
        """
        url_hash = self._generate_url_hash(url)
        db: Session = self._db_session if self._db_session else next(self._get_db())
        return db.query(JobOffer).filter(JobOffer.url_hash == url_hash).first() is not None
