"""
Benchmark questions whose ground truths exist verbatim in the committed
corpus. `must_contain` is a phrase that appears in `expected_source`
(tests/test_fix11_eval.py checks this against data/chroma), so retrieval
hit rate and answer correctness can be scored without a human.
"""

BENCHMARK = [
    {
        "question": "What is the design pressure of pressure vessel V-201?",
        "ground_truth": "The design pressure of V-201 is 15 bar(g), per inspection report INS-2024-087.",
        "expected_source": "inspection_report_V201_2024.txt",
        "must_contain": "Design Pressure: 15 bar(g)",
        "type": "single-fact",
    },
    {
        "question": "What maintenance was performed on pump P-101 under work order WO-2024-0312?",
        "ground_truth": "The mechanical seal and both bearings were replaced, the impeller was inspected, "
                        "alignment was corrected and the seal flush system was refilled; post-maintenance "
                        "vibration was 3.2 mm/s.",
        "expected_source": "work_order_P101_2024.txt",
        "must_contain": "Mechanical seal replaced",
        "type": "single-fact",
    },
    {
        "question": "What caused the bearing seizure on conveyor C-202?",
        "ground_truth": "A blocked line in the C-202 auto-lubrication system stopped grease reaching the "
                        "bearing (BRG-405), which seized from complete lubrication failure.",
        "expected_source": "Vindhya_Steel_Incident_Report_C202.txt",
        "must_contain": "auto-lubrication system for C-202 had a blocked line",
        "type": "single-fact",
    },
    {
        "question": "What is the working volume and design pressure of blast furnace BF-1?",
        "ground_truth": "BF-1 has a working volume of 3200 cubic meters and a design pressure of 2.5 bar.",
        "expected_source": "Vindhya_Steel_BF1_Maintenance_Manual.txt",
        "must_contain": "working volume of 3200 cubic meters",
        "type": "single-fact",
    },
    {
        "question": "What did vibration analysis find on pump P-101 in March 2024 and what was done?",
        "ground_truth": "On 2024-03-15 vibration reached 4.1 mm/s RMS with 2X/3X peaks indicating parallel "
                        "misalignment; laser alignment was completed on 2024-04-02 and loose foundation bolts "
                        "were tightened, bringing it to 1.8 mm/s.",
        "expected_source": "Vindhya_Steel_Vibration_Log_P101.txt",
        "must_contain": "parallel misalignment",
        "type": "multi-hop",
    },
    {
        "question": "What non-conformance did the 2024 compliance audit find on conveyor C-202?",
        "ground_truth": "The emergency pull-cord on the eastern walkway was sagging and needed excess force; "
                        "it must be tightened within 15 days.",
        "expected_source": "Vindhya_Steel_Compliance_Audit_2024.txt",
        "must_contain": "pull-cord",
        "type": "single-fact",
    },
    {
        "question": "What special lockout/tagout instruction applies to conveyors like C-202?",
        "ground_truth": "Belt tension must be released or mechanically blocked to prevent movement from "
                        "gravity or stored elastic energy (SOP VSW-SAF-042, section 4).",
        "expected_source": "Vindhya_Steel_LOTO_SOP.txt",
        "must_contain": "tension is released or mechanically blocked",
        "type": "single-fact",   # high-stakes: expected to be held for human review
    },
]
