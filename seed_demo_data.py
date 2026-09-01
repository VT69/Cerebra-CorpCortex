import os
import requests
import tempfile
import time

API_URL = "https://industrialiq-api.onrender.com"

DOCUMENTS = [
    {
        "filename": "Vindhya_Steel_BF1_Maintenance_Manual.txt",
        "content": """
VINDHYA STEEL WORKS
Plant: Kalinganagar Facility
Document: Blast Furnace BF-1 Maintenance Manual
Date: 2024-01-15
Equipment ID: BF-1

1. SYSTEM OVERVIEW
Blast Furnace BF-1 has a working volume of 3200 cubic meters. It operates at a design pressure of 2.5 bar. The cooling system utilizes closed-circuit demineralized water.

2. MAINTENANCE SCHEDULE
- Daily: Inspect tuyere cooling water flow.
- Weekly: Check top gas analyzer calibration.
- Monthly: Lubricate charging bell mechanism using high-temperature grease (Spec: VSW-HTG-99).

3. FAILURE MODES & TROUBLESHOOTING
- High Hearth Temperature: Indicates refractory wear. Immediate action: Reduce blast temperature and inject titanium-bearing material.
- Cooling Water Leak: Detected by hydrogen spike in top gas. Action: Isolate suspected stave immediately.
"""
    },
    {
        "filename": "Vindhya_Steel_Incident_Report_C202.txt",
        "content": """
VINDHYA STEEL WORKS - INCIDENT REPORT
Incident ID: INC-2024-089
Date: 2024-03-12
Location: Sinter Plant, Conveyor Belt C-202
Reported By: Rajesh Sharma, Shift In-Charge
Severity: Near Miss (High Potential)

DESCRIPTION
At 14:30 hours, during routine operation, a loud screeching noise was heard from the drive pulley of Conveyor Belt C-202. The operator immediately hit the emergency stop. Upon inspection, it was found that the main bearing (Part # BRG-405) had seized due to complete lubrication failure. 

ROOT CAUSE ANALYSIS
The auto-lubrication system for C-202 had a blocked line. The blockage prevented grease from reaching the bearing. The daily inspection checklist did not include a physical verification of grease flow at the bearing housing.

CORRECTIVE ACTIONS
1. Replaced the seized bearing and cleared the auto-lube line.
2. Updated the maintenance checklist to include visual confirmation of grease at the bearing point.
3. Scheduled ultrasonic vibration analysis for all critical conveyor drives monthly.
"""
    },
    {
        "filename": "Vindhya_Steel_Compliance_Audit_2024.txt",
        "content": """
VINDHYA STEEL WORKS
External Compliance Audit Report
Standard: Factory Act 1948 & State Rules
Date: 2024-02-28
Auditor: National Safety Council (NSC)

FINDINGS & OBSERVATIONS
1. Equipment Safety (Section 21)
- Blast Furnace BF-1: Compliant. All interlocking systems on the charging mechanism are functional.
- Conveyor C-202: Non-conformance noted. The emergency pull-cord along the eastern walkway was sagging and required excess force to actuate. Must be tightened within 15 days.

2. Confined Space Entry (Section 36)
- The gas monitoring logs for the Gas Cleaning Plant (GCP) were reviewed. All records are in order. The calibration of portable CO monitors is up to date.

3. Pressure Vessels (Section 31)
- Compressor Air Receiver AR-105: Hydro-test certificate is valid until 2026. Safety relief valves were calibrated last month. Compliant.
"""
    },
    {
        "filename": "Vindhya_Steel_LOTO_SOP.txt",
        "content": """
VINDHYA STEEL WORKS
Standard Operating Procedure (SOP)
Title: Lockout/Tagout (LOTO) Procedure for Rotating Equipment
SOP No: VSW-SAF-042

1. PURPOSE
To ensure that machines and equipment are isolated from all potentially hazardous energy before employees perform servicing or maintenance activities.

2. SCOPE
Applies to all rotating equipment at the Kalinganagar facility, including pumps, compressors, and conveyors.

3. PROCEDURE
3.1. Preparation: Identify all energy sources (electrical, mechanical, pneumatic).
3.2. Notification: Inform the Shift In-Charge and affected operators.
3.3. Shutdown: Stop the equipment using normal operating controls.
3.4. Isolation: Physically isolate energy sources (e.g., open breakers, close valves).
3.5. Lock and Tag: Apply personal safety locks and "Do Not Operate" tags to isolation devices.
3.6. Verification: Attempt to start the equipment to verify complete isolation.

4. SPECIAL INSTRUCTIONS FOR CONVEYORS
For conveyor systems like C-202, ensure that tension is released or mechanically blocked to prevent unexpected movement due to gravity or stored elastic energy.
"""
    },
    {
        "filename": "Vindhya_Steel_Vibration_Log_P101.txt",
        "content": """
VINDHYA STEEL WORKS
Condition Monitoring Log
Equipment: Boiler Feed Water Pump P-101
Method: Ultrasonic Vibration Analysis
Analyst: Amit Patel

LOG ENTRIES
- 2024-01-10: Overall vibration 2.4 mm/s RMS. Normal operation. Spectrum shows dominant 1X peak.
- 2024-02-12: Overall vibration 2.6 mm/s RMS. Normal operation.
- 2024-03-15: Overall vibration 4.1 mm/s RMS. Alert limit exceeded.
  - Spectrum Analysis: Elevated 2X and 3X peaks observed. Phase analysis indicates parallel misalignment across the coupling.
  - Recommendation: Schedule laser alignment during the next planned shutdown. Check foundation bolts for tightness.

- 2024-04-02: Maintenance performed. Laser alignment completed. Foundation bolts tightened (2 were found loose).
- 2024-04-05: Post-maintenance reading: 1.8 mm/s RMS. Alignment is excellent. Return to normal monitoring schedule.
"""
    }
]

def seed_data():
    print("Starting data generation for Vindhya Steel Works...")
    temp_dir = tempfile.mkdtemp()
    
    for doc in DOCUMENTS:
        filepath = os.path.join(temp_dir, doc["filename"])
        with open(filepath, "w") as f:
            f.write(doc["content"])
        
        print(f"Uploading {doc['filename']}...")
        with open(filepath, "rb") as f:
            files = {"file": (doc["filename"], f, "text/plain")}
            data = {"doc_type": "generic"}
            try:
                res = requests.post(f"{API_URL}/ingest", files=files, data=data, timeout=120)
                if res.status_code == 200:
                    resp_data = res.json()
                    if resp_data.get("status") == "skipped":
                        print(f"  -> Skipped (already exists)")
                    else:
                        print(f"  -> Success! Chunks: {resp_data.get('chunks')}, Nodes: {resp_data.get('nodes')}")
                else:
                    print(f"  -> Failed: {res.status_code} {res.text[:200]}")
            except Exception as e:
                print(f"  -> Error connecting to API: {e}")
        
        # Longer pause to avoid rate limits
        print("  Waiting 10s before next upload...")
        time.sleep(10)

    print("Finished seeding data.")

if __name__ == "__main__":
    seed_data()
