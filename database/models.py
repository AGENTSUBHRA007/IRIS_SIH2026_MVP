"""
Database models — SQLAlchemy 2.0 ORM.
"""

from sqlalchemy import Column, String, Float, Integer, DateTime, Text, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

Base = declarative_base()


class TwinSnapshot(Base):
    __tablename__ = 'twin_snapshots'

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    tick = Column(Integer)
    health_score = Column(Float)
    failure_probability = Column(Float)
    anomaly_score = Column(Float)
    rul_hours = Column(Float)
    rul_source = Column(String(50))
    belt_advisory = Column(String(50))
    temperature_c = Column(Float)
    vibration_mms = Column(Float)
    tension_tight_N = Column(Float)
    safety_factor = Column(Float)
    sag_ratio_pct = Column(Float)
    load_fraction = Column(Float)
    n_damage_events = Column(Integer)
    is_compliant = Column(Boolean)
    state_json = Column(Text)  # Full JSON dump for detailed retrieval


class DetectionEvent(Base):
    __tablename__ = 'detection_events'

    id = Column(String(50), primary_key=True)
    job_id = Column(String(50), nullable=True, index=True)
    frame_index = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    class_name = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=False)
    severity = Column(String(20), nullable=False)
    bbox_x1 = Column(Float)
    bbox_y1 = Column(Float)
    bbox_x2 = Column(Float)
    bbox_y2 = Column(Float)
    length_cm = Column(Float)
    rul_impact_hours = Column(Float)
    source = Column(String(20), nullable=False)  # 'live' | 'video_upload'


class MaintenanceEvent(Base):
    __tablename__ = 'maintenance_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    event_type = Column(String(50))
    description = Column(Text)
    performed_by = Column(String(100))
    health_before = Column(Float)
    health_after = Column(Float)


def get_engine(database_url: str = None):
    """Create database engine."""
    url = database_url or "sqlite:///data/ps26008_twin.db"
    return create_engine(url, echo=False)


def create_tables(engine):
    """Create all tables."""
    Base.metadata.create_all(engine)


def get_session(engine):
    """Get a database session."""
    Session = sessionmaker(bind=engine)
    return Session()
