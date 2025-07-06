"""
Server (kubernetes node) tracking ORM.
"""

from pydantic import BaseModel
from sqlalchemy import Column, String, DateTime, Integer, BigInteger, Float, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from chutes_miner.api.database import Base


class ServerArgs(BaseModel):
    name: str
    validator: str
    hourly_cost: float
    gpu_short_ref: str


class Server(Base):
    __tablename__ = "servers"

    server_id = Column(String, primary_key=True)
    validator = Column(String, nullable=False)
    name = Column(String, unique=True, nullable=False)
    ip_address = Column(String)
    verification_port = Column(Integer)
    status = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    labels = Column(JSONB, nullable=False)
    seed = Column(BigInteger)
    gpu_count = Column(Integer, nullable=False)
    cpu_per_gpu = Column(Integer, nullable=False, default=1)
    memory_per_gpu = Column(Integer, nullable=False, default=1)
    hourly_cost = Column(Float, nullable=False)
    locked = Column(Boolean, default=False)

    gpus = relationship("GPU", back_populates="server", lazy="joined", cascade="all, delete-orphan")
    deployments = relationship(
        "Deployment", back_populates="server", lazy="joined", cascade="all, delete-orphan"
    )
