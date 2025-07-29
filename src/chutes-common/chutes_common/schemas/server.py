"""
Server (kubernetes node) tracking ORM.
"""

from typing import Optional
from pydantic import BaseModel
from sqlalchemy import Column, String, DateTime, Integer, BigInteger, Float, Boolean, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from chutes_common.schemas import Base


class ServerArgs(BaseModel):
    name: str
    validator: str
    hourly_cost: float
    gpu_short_ref: str
    agent_api: Optional[str] = None


class Server(Base):
    __tablename__ = "servers"

    server_id = Column(String, primary_key=True)
    validator = Column(String, nullable=False)
    name = Column(String, unique=True, nullable=False)
    ip_address = Column(String)
    agent_api = Column(String, nullable=True)
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
    kubeconfig = Column(Text, nullable=True) # Make this false if enforicng migration

    gpus = relationship("GPU", back_populates="server", lazy="joined", cascade="all, delete-orphan")
    deployments = relationship(
        "Deployment",
        back_populates="server",
        lazy="joined",
        cascade="all, delete-orphan",
    )
