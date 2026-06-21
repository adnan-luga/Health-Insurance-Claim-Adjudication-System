from ..extraction.extractors import endorsements
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, Text, Integer, JSON
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

class Base(DeclarativeBase):
    pass

class PolicyRuleSetRecord(Base):
    __tablename__="policy_rulesets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(100), index=True)
    version_hash: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    document_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    compiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    ruleset_json: Mapped[dict] = mapped_column(JSONB)

    rule_count: Mapped[int] = mapped_column(Integer)
    exclusion_count: Mapped[int] = mapped_column(Integer)
    endorsement_count: Mapped[int] = mapped_column(Integer)

    warning_count: Mapped[int] = mapped_column(Integer)
    compilation_warnings: Mapped[list] = mapped_column(JSON)
    schema_version: Mapped[str] = mapped_column(String(20))

