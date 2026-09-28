from sqlalchemy import Column, Integer, String
from db.database import Base

class Package(Base):
    __tablename__ = "packages"

    id = Column(Integer, primary_key=True, index=True)
    package_type = Column(String(255), index=True)