from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timedelta
import uuid

# Initialize FastAPI app
app = FastAPI()

# Database setup
DATABASE_URL = "sqlite:///./baggage.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# Define the database model
class BagScan(Base):
    __tablename__ = "bag_scans"
    scan_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    bag_tag_id = Column(String, index=True)
    destination_gate = Column(String, index=True)
    location_scanned = Column(String)
    scan_timestamp = Column(DateTime, default=datetime.utcnow)

# Create the database table
Base.metadata.create_all(bind=engine)

# Request model for logging scans
class ScanRequest(BaseModel):
    bag_tag_id: str
    destination_gate: str
    location_scanned: str

# Response model for logging scans
class ScanResponse(BaseModel):
    scan_internal_id: str
    status: str

# Endpoint to log a new scan
@app.post("/baggage/scan", response_model=ScanResponse)
def log_scan(scan: ScanRequest):
    db = SessionLocal()
    new_scan = BagScan(
        bag_tag_id=scan.bag_tag_id,
        destination_gate=scan.destination_gate,
        location_scanned=scan.location_scanned
    )
    db.add(new_scan)
    db.commit()
    db.refresh(new_scan)
    db.close()
    return {"scan_internal_id": new_scan.scan_id, "status": "logged"}

# Get scans by bag ID (optionally only latest)
@app.get("/baggage/scans/bag/{bag_tag_id}")
def get_scans_by_bag(bag_tag_id: str, latest: bool = Query(False)):
    db = SessionLocal()
    query = db.query(BagScan).filter(BagScan.bag_tag_id == bag_tag_id).order_by(BagScan.scan_timestamp.desc())
    scans = query.all()
    db.close()
    if latest:
        if not scans:
            raise HTTPException(status_code=404, detail="No scans found")
        return scans[0]
    return scans

# Get all scans going to a specific gate
@app.get("/baggage/scans/gate/{destination_gate}")
def get_scans_by_gate(destination_gate: str):
    db = SessionLocal()
    scans = db.query(BagScan).filter(BagScan.destination_gate == destination_gate).order_by(BagScan.scan_timestamp.desc()).all()
    db.close()
    return scans

# Get active bags en-route to a gate within a time window
@app.get("/baggage/active/gate/{destination_gate}")
def get_active_bags(destination_gate: str, since_minutes: int = 60):
    db = SessionLocal()
    cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
    scans = db.query(BagScan).filter(
        BagScan.destination_gate == destination_gate,
        BagScan.scan_timestamp >= cutoff
    ).order_by(BagScan.scan_timestamp.desc()).all()
    db.close()

    # Keep only the most recent scan per bag
    unique_bags = {}
    for scan in scans:
        if scan.bag_tag_id not in unique_bags:
            unique_bags[scan.bag_tag_id] = {
                "bag_tag_id": scan.bag_tag_id,
                "last_scan_at": scan.scan_timestamp,
                "last_location": scan.location_scanned
            }
    return list(unique_bags.values())

# Get unique bag counts per gate in a given time window
@app.get("/baggage/stats/gate-counts")
def get_gate_counts(since_minutes: int = 60):
    db = SessionLocal()
    cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
    scans = db.query(BagScan).filter(BagScan.scan_timestamp >= cutoff).all()
    db.close()

    gate_counts = {}
    seen = set()
    for scan in scans:
        key = (scan.destination_gate, scan.bag_tag_id)
        if key not in seen:
            seen.add(key)
            gate_counts[scan.destination_gate] = gate_counts.get(scan.destination_gate, 0) + 1

    return [{"destination_gate": gate, "unique_bag_count": count} for gate, count in gate_counts.items()]
