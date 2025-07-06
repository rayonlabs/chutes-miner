"""
Individual GPU ORM.
"""

from pydantic import BaseModel
from sqlalchemy import Column, String, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from chutes_miner.api.database import Base


class VerificationArgs(BaseModel):
    verified: bool


class GPU(Base):
    __tablename__ = "gpus"

    gpu_id = Column(String, primary_key=True, nullable=False)
    validator = Column(String)
    server_id = Column(String, ForeignKey("servers.server_id", ondelete="CASCADE"), nullable=False)
    deployment_id = Column(
        String, ForeignKey("deployments.deployment_id", ondelete="SET NULL"), nullable=True
    )

    device_info = Column(JSONB, nullable=False)
    model_short_ref = Column(String, nullable=False)
    verified = Column(Boolean, default=False)

    server = relationship("Server", back_populates="gpus", lazy="joined")
    deployment = relationship(
        "Deployment", back_populates="gpus", cascade="all, delete-orphan", single_parent=True
    )
