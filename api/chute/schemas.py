"""
ORM definitions for Chutes.
"""

from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.dialects.postgresql import ARRAY
from api.database import Base


class Chute(Base):
    __tablename__ = "chutes"

    chute_id = Column(String, primary_key=True, nullable=False)
    validator = Column(String, nullable=False)
    name = Column(String)
    image = Column(String, nullable=False)
    code = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    ref_str = Column(String, nullable=False)
    version = Column(String, nullable=False)
    supported_gpus = Column(ARRAY(String), nullable=False)
    gpu_count = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    ban_reason = Column(String, nullable=True)
    chutes_version = Column(String)

    deployments = relationship("Deployment", back_populates="chute", cascade="all, delete-orphan")
