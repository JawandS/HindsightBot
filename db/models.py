import enum
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SAEnum, Index
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class VerdictStatus(str, enum.Enum):
    UNRESOLVED = "unresolved"
    CAME_TRUE = "came_true"
    CAME_FALSE = "came_false"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    predictions = relationship("Prediction", back_populates="collection")


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        Index("ix_predictions_status_next_check_at", "status", "next_check_at"),
    )

    id = Column(Integer, primary_key=True)
    collection_id = Column(Integer, ForeignKey("collections.id"), nullable=False)
    text = Column(Text, nullable=False)
    status = Column(SAEnum(VerdictStatus, name="verdict_status", values_callable=lambda obj: [e.value for e in obj]), default=VerdictStatus.UNRESOLVED, nullable=False)
    summary = Column(Text)
    next_check_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    collection = relationship("Collection", back_populates="predictions")
    investigations = relationship(
        "Investigation", back_populates="prediction",
        order_by="Investigation.investigated_at.desc()"
    )
    jobs = relationship("Job", back_populates="prediction")


class Investigation(Base):
    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True)
    prediction_id = Column(Integer, ForeignKey("predictions.id"), nullable=False)
    verdict = Column(SAEnum(VerdictStatus, name="verdict_status", values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    summary = Column(Text)
    investigated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    prediction = relationship("Prediction", back_populates="investigations")
    sources = relationship("Source", back_populates="investigation")


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False)
    url = Column(Text, nullable=False)
    title = Column(String(500))
    relevance_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    investigation = relationship("Investigation", back_populates="sources")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    prediction_id = Column(Integer, ForeignKey("predictions.id"), nullable=False)
    status = Column(SAEnum(JobStatus, name="job_status", values_callable=lambda obj: [e.value for e in obj]), default=JobStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)

    prediction = relationship("Prediction", back_populates="jobs")
