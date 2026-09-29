"""Resolve offer locations and calculate their distance impact."""

import math
import unicodedata
import re
from sqlalchemy.orm import Session
from models.database import SessionLocal, City
from config.settings import settings

class LocationMatcher:
    """Resolve offer locations against known cities and score their distance."""

    LOCATION_OVERRIDES = {
        "proszowice": {"drive_minutes": 50, "road_km": 42},
        "batowice": {"drive_minutes": 50, "road_km": 40},
    }

    KRAKOW_SOUTHEAST_TERMS = {
        "bieżanów", "biezanow", "prokocim", "podgórze", "podgorze",
        "płaszów", "plaszow", "rybitwy", "nowa huta", "czyżyny", "czyzyny",
        "łagiewniki", "lagiewniki", "borek fałęcki", "borek falecki"
    }
    KRAKOW_NORTHWEST_TERMS = {
        "bronowice", "krowodrza", "prądnik biały", "pradnik bialy",
        "zwierzyniec", "azory", "tonie", "wola justowska"
    }

    def __init__(self):
        """Load the configured center coordinates and search radius."""
        self.base_lat = settings.BASE_LOCATION_LAT
        self.base_lon = settings.BASE_LOCATION_LON
        self.search_radius_km = settings.SEARCH_RADIUS_KM

    def _get_db(self):
        """Helper to get a new DB session."""
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _normalize_location_text(self, text: str) -> str:
        """Normalize accents, punctuation, whitespace, and known encoding errors."""
        text = self._repair_mojibake(text or "")
        normalized = unicodedata.normalize('NFKD', text)
        ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
        cleaned = re.sub(r'[^\w\s]', ' ', ascii_text).lower()
        return re.sub(r'\s+', ' ', cleaned).strip()

    def _location_name_in_text(self, normalized_name: str, normalized_text: str) -> bool:
        """Check for a whole city or district name in normalized text."""
        if not normalized_name or not normalized_text:
            return False
        pattern = r"(?<!\w)" + re.escape(normalized_name).replace(r"\ ", r"\s+") + r"(?!\w)"
        return re.search(pattern, normalized_text) is not None

    def _override_for_text(self, normalized_text: str) -> dict | None:
        """Return fixed commute estimates for locations with configured overrides."""
        for name, data in self.LOCATION_OVERRIDES.items():
            if self._location_name_in_text(name, normalized_text):
                return data
        return None

    def _repair_mojibake(self, text: str) -> str:
        """Repair common UTF-8 text decoded as Windows-1250 in older seed data."""
        if not text:
            return ""
        if any(marker in text for marker in ("Ă", "Ĺ", "Ĺ‚", "Ĺ›", "Ä")):
            try:
                repaired = text.encode("cp1250", errors="strict").decode("utf-8", errors="strict")
                if repaired:
                    return repaired
            except Exception:
                pass
        return text

    def _haversine_distance(self, lat1, lon1, lat2, lon2):
        """
        Calculate the distance between two points on Earth using the Haversine formula.
        Returns distance in kilometers.
        """
        R = 6371  # Radius of Earth in kilometers

        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        dlon = lon2_rad - lon1_rad
        dlat = lat2_rad - lat1_rad

        a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        distance = R * c
        return distance

    def is_within_radius(self, job_location_text: str) -> bool:
        """
        Checks if a job location is within the defined search radius from the base location.
        Performs fuzzy matching against known cities in the database.
        """
        db = SessionLocal()
        try:
            if not job_location_text:
                return False

            normalized_job_location = self._normalize_location_text(job_location_text)

            override = self._override_for_text(normalized_job_location)
            if override and override.get("road_km") is not None:
                return override["road_km"] <= self.search_radius_km

            cities = db.query(City).filter(City.active == True).all()
            for city in cities:
                normalized_city_name = self._normalize_location_text(city.city_name)
                if self._location_name_in_text(normalized_city_name, normalized_job_location):
                    distance = self._haversine_distance(
                        self.base_lat,
                        self.base_lon,
                        city.latitude,
                        city.longitude,
                    )
                    return distance <= self.search_radius_km
            return False
        finally:
            db.close()
        return False

    def get_distance_km(self, job_location_text: str) -> float | None:
        """Return distance from the base city for the first known city in text."""
        if not job_location_text:
            return None

        normalized_job_location = self._normalize_location_text(job_location_text)
        db = SessionLocal()
        try:
            override = self._override_for_text(normalized_job_location)
            if override and override.get("road_km") is not None:
                return override["road_km"]

            cities = db.query(City).filter(City.active == True).all()
            for city in cities:
                normalized_city_name = self._normalize_location_text(city.city_name)
                if self._location_name_in_text(normalized_city_name, normalized_job_location):
                    return self._haversine_distance(
                        self.base_lat,
                        self.base_lon,
                        city.latitude,
                        city.longitude,
                    )
            return None
        finally:
            db.close()

    def get_commute_minutes(self, job_location_text: str) -> int | None:
        """Return a rough one-way commute estimate for scoring."""
        if not job_location_text:
            return None

        normalized_job_location = self._normalize_location_text(job_location_text)
        override = self._override_for_text(normalized_job_location)
        if override and override.get("drive_minutes") is not None:
            return override["drive_minutes"]

        distance = self.get_distance_km(job_location_text)
        if distance is None:
            return None

        # Haversine is an optimistic estimate for commute decisions around the configured search center.
        return round(distance * 1.6)

    def _distance_penalty(self, distance_km: float | None, commute_minutes: int | None) -> int | None:
        """Calculate the distance-related score penalty, if there is enough data."""
        def scaled_penalty(value: float, start: float, midpoint: float, end: float) -> float | None:
            """Scale a distance or commute value into a gradual penalty."""
            if value < start:
                return None
            if value <= midpoint:
                return 1 + ((value - start) / max(midpoint - start, 1) * 29)
            return 30 + ((min(value, end) - midpoint) / max(end - midpoint, 1) * 70)

        penalties = []
        if distance_km is not None:
            penalty = scaled_penalty(distance_km, 26, 50, 100)
            if penalty is not None:
                penalties.append(penalty)
        if commute_minutes is not None:
            penalty = scaled_penalty(commute_minutes, 31, 60, 120)
            if penalty is not None:
                penalties.append(penalty)
        if not penalties:
            return None
        return -round(max(penalties))

    def score_adjustment(self, job_location_text: str) -> int:
        """Return the bounded point adjustment for a job's location."""
        """
        Convert location quality into a score adjustment.
        Close cities around the configured search center get a boost; distant cities lose points gradually.
        Krakow's south/east side is preferred over north/west when district text is present.
        """
        if not job_location_text:
            return 0

        normalized = self._normalize_location_text(job_location_text)
        distance = self.get_distance_km(job_location_text)
        commute_minutes = self.get_commute_minutes(job_location_text)
        adjustment = 0

        distance_penalty = self._distance_penalty(distance, commute_minutes)
        if distance_penalty is not None:
            adjustment += distance_penalty
        elif commute_minutes is not None:
            if commute_minutes <= 20:
                adjustment += 40
            elif commute_minutes <= 30:
                adjustment += 25
            elif commute_minutes <= 40:
                adjustment += 6
            elif commute_minutes <= 50:
                adjustment += 0
            else:
                adjustment -= 25

        if self._location_name_in_text("krakow", normalized):
            if any(self._normalize_location_text(term) in normalized for term in self.KRAKOW_SOUTHEAST_TERMS):
                adjustment += 8
            if any(self._normalize_location_text(term) in normalized for term in self.KRAKOW_NORTHWEST_TERMS):
                adjustment -= 8

        return max(-100, min(45, adjustment))

    def extract_known_city(self, text: str) -> str | None:
        """Try to extract a known active city name from raw text."""
        if not text:
            return None

        normalized_text = self._normalize_location_text(text)
        db = SessionLocal()
        try:
            cities = db.query(City).filter(City.active == True).all()
            for city in cities:
                normalized_city_name = self._normalize_location_text(city.city_name)
                if self._location_name_in_text(normalized_city_name, normalized_text):
                    return city.city_name
            return None
        finally:
            db.close()
