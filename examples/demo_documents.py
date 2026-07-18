"""Demo — Document Super-Agents showcase.

Runs all three document agents (PPT, Word, PDF) plus the Quality Assessor.
Generates sample files in output/ and prints VP-level assessment reports.

Usage:
    python examples/demo_documents.py

Optional env vars for real stock images:
    UNSPLASH_ACCESS_KEY=<your-key>   # https://unsplash.com/developers
    PEXELS_API_KEY=<your-key>        # https://www.pexels.com/api/
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from future_agents.agents.pdf_agent import PDFAgent
from future_agents.agents.ppt_agent import PPTAgent
from future_agents.agents.quality_assessor_agent import QualityAssessorAgent
from future_agents.agents.word_agent import WordAgent
from future_agents.core.base_agent import TaskContext


# ── Sample content ────────────────────────────────────────────────────────────

TOPIC = "AI-Driven Healthcare: Transforming Patient Care"

PPT_PARAMS = {
    "title": TOPIC,
    "subtitle": "Innovation at the intersection of AI and Medicine",
    "author": "Dr. Alex Rivera, Chief Innovation Officer",
    "color_theme": "teal",
    "output_name": "ai_healthcare_presentation",
    "introduction": (
        "Artificial Intelligence is revolutionizing healthcare — from early disease detection "
        "to personalized treatment plans. This presentation explores the key pillars of AI "
        "adoption in clinical and operational settings."
    ),
    "topics": [
        {
            "title": "AI in Diagnostics",
            "bullets": [
                "Computer vision for radiology: 94.5% accuracy on X-ray analysis",
                "NLP-powered EHR mining surfaces hidden risk factors",
                "Real-time pathology slide analysis reduces turnaround by 60%",
                "Multi-modal AI combines imaging + lab + genomic data",
                "Clinician-in-the-loop design ensures safety and accountability",
            ],
            "notes": "Emphasize FDA-cleared tools only. Quote peer-reviewed studies.",
        },
        {
            "title": "Predictive Analytics & Population Health",
            "bullets": [
                "Sepsis prediction models with 12-hour advance warning",
                "Readmission risk scoring integrated into discharge workflows",
                "SDOH data enrichment for equity-aware care plans",
                "Real-world evidence from 50M+ patient records",
                "Continuous learning pipelines re-train monthly on new data",
            ],
            "notes": "Highlight equity focus — different models for different populations.",
        },
        {
            "title": "Operational AI & Efficiency",
            "bullets": [
                "Intelligent scheduling reduces patient wait times by 35%",
                "Supply chain optimization cuts waste by $2.4M per 1,000 beds",
                "AI-assisted prior authorization: 80% automation rate",
                "Staff burnout reduction through intelligent workload balancing",
                "24/7 AI triage chat reduces ED visits by 18%",
            ],
        },
        {
            "title": "Ethics, Governance & Inclusivity",
            "bullets": [
                "Algorithmic bias audits conducted quarterly",
                "Diverse training datasets — 40+ countries represented",
                "Patient consent framework for AI-driven decisions",
                "HIPAA + GDPR compliant data pipelines by design",
                "Explainability layer: every prediction includes rationale",
            ],
        },
        {
            "title": "Implementation Roadmap",
            "bullets": [
                "Phase 1 (Q1–Q2): Infrastructure readiness + data governance",
                "Phase 2 (Q3): Pilot with 3 high-impact use cases",
                "Phase 3 (Q4): Scale to system-wide deployment",
                "Phase 4 (Year 2): Continuous improvement + new use cases",
                "KPIs: clinical outcomes, cost savings, staff satisfaction",
            ],
        },
    ],
    "architecture": [
        {"label": "Data Ingestion", "color": (0x00, 0x96, 0x88)},
        {"label": "AI Platform", "color": (0x00, 0x69, 0x6C)},
        {"label": "Clinical Apps", "color": (0x26, 0xA6, 0x9A)},
        {"label": "Analytics Hub", "color": (0x80, 0xCB, 0xC4)},
    ],
    "architecture_description": (
        "Unified data lake → HIPAA-compliant AI training → Real-time inference APIs → "
        "Clinical decision support integrated into EMR workflows"
    ),
    "summary": [
        "AI delivers measurable improvements across diagnostics, operations, and population health",
        "Inclusive, bias-audited models ensure equitable care for all patient populations",
        "Phased implementation minimizes disruption while maximizing ROI",
        "Strong governance framework addresses ethical, legal, and privacy requirements",
        "Immediate next step: Executive sponsor alignment and data governance assessment",
    ],
}

WORD_PARAMS = {
    "title": TOPIC,
    "subtitle": "A Strategic White Paper for Healthcare Leadership",
    "author": "Dr. Alex Rivera",
    "organization": "HealthTech Innovation Group",
    "color_theme": "executive_green",
    "output_name": "ai_healthcare_whitepaper",
    "sections": [
        {
            "heading": "Executive Summary",
            "content": (
                "Artificial Intelligence is no longer a future concept in healthcare — it is "
                "actively deployed across leading health systems worldwide. This white paper "
                "synthesizes evidence from 200+ peer-reviewed studies and 50 implementation "
                "case studies to provide a definitive strategic guide for healthcare executives "
                "evaluating AI adoption."
            ),
            "bullets": [
                "AI in diagnostics achieves 94.5% accuracy in radiology tasks",
                "Predictive analytics reduces 30-day readmissions by 22%",
                "Operational AI delivers $2.4M annual savings per 1,000 beds",
                "Governance frameworks are critical to sustainable adoption",
            ],
        },
        {
            "heading": "Current Landscape",
            "content": (
                "The global AI in healthcare market reached $22B in 2024 and is projected to "
                "exceed $188B by 2030 (CAGR 36%). Adoption is accelerating across three vectors: "
                "clinical decision support, operational automation, and patient engagement. "
                "Leading health systems including Mayo Clinic, Cleveland Clinic, and Kaiser "
                "Permanente have each deployed more than 20 AI models in production."
            ),
            "subsections": [
                {
                    "heading": "Diagnostic AI",
                    "content": (
                        "FDA-cleared diagnostic AI tools now cover radiology, dermatology, "
                        "ophthalmology, and pathology. Multi-modal models that combine imaging, "
                        "genomics, and clinical notes are demonstrating superior sensitivity and "
                        "specificity compared to single-modality approaches."
                    ),
                },
                {
                    "heading": "Operational AI",
                    "content": (
                        "Process automation powered by AI is addressing the $935B in annual "
                        "administrative waste in US healthcare. Intelligent scheduling, AI-assisted "
                        "prior authorization, and supply chain optimization represent the highest-ROI "
                        "near-term opportunities."
                    ),
                },
            ],
            "table": {
                "headers": ["AI Domain", "Top Use Case", "Reported ROI", "Maturity"],
                "rows": [
                    ["Diagnostics", "Radiology AI", "42% time savings", "High"],
                    ["Predictive", "Sepsis Alert", "28% mortality reduction", "High"],
                    ["Operational", "Scheduling AI", "$1.8M/year per site", "Medium"],
                    ["Patient Engagement", "AI Triage Chat", "18% ED deflection", "Medium"],
                    ["Research", "Drug Discovery", "60% faster screening", "Emerging"],
                ],
            },
        },
        {
            "heading": "Equity & Inclusivity in AI",
            "content": (
                "Algorithmic bias in healthcare AI represents one of the most critical risks to "
                "equitable care. Training data that underrepresents minority populations, women, "
                "or patients with disabilities can systematically disadvantage already vulnerable "
                "groups. Leading organizations have instituted mandatory bias audits, diverse data "
                "acquisition programs, and explainability requirements for all clinical AI tools."
            ),
            "bullets": [
                "Mandatory bias audits before any model enters production",
                "Diverse annotation teams across race, gender, age, and geography",
                "Patient advisory boards include underrepresented community members",
                "Disparate impact analysis reported quarterly to governance committees",
            ],
        },
        {
            "heading": "Implementation Framework",
            "content": (
                "Successful AI implementation in healthcare requires a structured approach "
                "spanning governance, infrastructure, change management, and continuous evaluation. "
                "The following four-phase framework has been validated across 25 health system "
                "implementations."
            ),
            "table": {
                "headers": ["Phase", "Timeline", "Key Activities", "Success Metric"],
                "rows": [
                    ["1. Foundation", "Q1–Q2", "Data governance, infrastructure", "Readiness score ≥ 80%"],
                    ["2. Pilot", "Q3", "3 use cases, 2 sites", "Clinical adoption > 70%"],
                    ["3. Scale", "Q4", "System-wide rollout", "ROI positive within 12mo"],
                    ["4. Optimize", "Year 2+", "Continuous learning, new cases", "NPS > 8/10"],
                ],
            },
        },
        {
            "heading": "Risk & Governance",
            "content": (
                "Every AI implementation carries technical, clinical, ethical, and regulatory risk. "
                "A proactive governance framework addresses each dimension before deployment, "
                "ensuring that AI augments rather than undermines clinical judgment."
            ),
            "bullets": [
                "AI Oversight Committee with clinical, technical, legal, and patient representation",
                "Model cards published for every production AI model",
                "Incident response plan for AI-related adverse events",
                "Annual third-party audit of all production models",
                "Clear human-in-the-loop requirements for high-stakes decisions",
            ],
        },
    ],
    "summary": (
        "AI represents a generational opportunity to improve clinical outcomes, reduce costs, "
        "and advance health equity. Success requires disciplined governance, inclusive design, "
        "phased implementation, and sustained executive commitment. Organizations that invest "
        "now in the right foundations will achieve durable competitive and clinical advantage. "
        "We recommend initiating an AI Readiness Assessment within the next 60 days."
    ),
}

PDF_PARAMS = {
    "title": TOPIC,
    "subtitle": "Evidence-Based Insights for Healthcare Leaders",
    "author": "Dr. Alex Rivera",
    "organization": "HealthTech Innovation Group",
    "people_type": "healthcare",
    "color_theme": "health",
    "output_name": "ai_healthcare_report",
    "introduction": (
        "This report presents a comprehensive analysis of AI applications in modern healthcare, "
        "drawing on real-world implementations, clinical trial data, and expert interviews "
        "across 15 health systems in 8 countries. Our findings demonstrate that AI — when "
        "implemented responsibly with diverse, inclusive datasets and strong governance — "
        "can materially improve clinical outcomes, patient experience, and operational efficiency."
    ),
    "chapters": [
        {
            "title": "The AI Diagnostic Revolution",
            "content": (
                "Computer vision and deep learning have achieved — and in some cases exceeded — "
                "specialist-level accuracy in medical imaging interpretation. The FDA has cleared "
                "over 520 AI/ML-enabled medical devices as of 2024, with radiology representing "
                "75% of approvals."
            ),
            "sections": [
                {
                    "heading": "Radiology AI in Practice",
                    "content": (
                        "AI-assisted chest X-ray interpretation at Stanford Medical Center reduced "
                        "radiologist turnaround time by 56% while maintaining 97% diagnostic "
                        "concordance. Similar results have been replicated at 40+ institutions globally."
                    ),
                },
                {
                    "heading": "Pathology & Genomics Integration",
                    "content": (
                        "Digital pathology AI systems can analyze whole-slide images in under 90 "
                        "seconds — a process that typically takes a pathologist 20–30 minutes. "
                        "Combined with genomic biomarker data, these systems improve cancer "
                        "subtype classification accuracy by 31%."
                    ),
                },
            ],
            "bullets": [
                "94.5% sensitivity for diabetic retinopathy detection (IDx-DR, FDA cleared)",
                "12-minute average AI chest CT read vs 45-minute conventional workflow",
                "41% reduction in diagnostic errors when AI and clinician review together",
            ],
        },
        {
            "title": "Predictive Analytics & Population Health",
            "content": (
                "Predictive AI models trained on longitudinal patient data can identify high-risk "
                "individuals months before adverse events, enabling proactive intervention that "
                "saves lives and reduces costs."
            ),
            "sections": [
                {
                    "heading": "Early Warning Systems",
                    "content": (
                        "Sepsis prediction models provide 12-hour advance warning with 85% "
                        "sensitivity and 78% specificity — performance that has been shown to "
                        "reduce sepsis mortality by 18% in randomized trials."
                    ),
                },
            ],
            "bullets": [
                "22% reduction in 30-day readmissions using AI risk stratification",
                "SDOH-enriched models improve equity across racial and socioeconomic groups",
                "Real-world evidence from 50M+ de-identified patient records",
            ],
        },
        {
            "title": "Equity, Ethics & Governance",
            "content": (
                "The most sophisticated AI model provides no value — and may cause harm — if it "
                "perpetuates or amplifies existing disparities in healthcare. Embedding equity "
                "into every phase of AI development is a moral imperative and a strategic necessity."
            ),
            "sections": [
                {
                    "heading": "Bias Detection & Mitigation",
                    "content": (
                        "Disparate impact analysis must be conducted across race, gender, age, "
                        "geography, and disability status before any model enters clinical use. "
                        "Re-weighting, re-sampling, and adversarial debiasing techniques should "
                        "be applied when disparities are detected."
                    ),
                },
                {
                    "heading": "Patient Consent & Transparency",
                    "content": (
                        "Patients have a right to know when AI contributes to their care decisions. "
                        "Clear consent frameworks, plain-language model cards, and appeal mechanisms "
                        "are essential components of trustworthy AI in healthcare."
                    ),
                },
            ],
            "bullets": [
                "Mandatory diverse annotation teams — 40+ countries represented",
                "Quarterly bias audit reports published to governance board",
                "All models include explainability output for clinical review",
                "Patient advisory councils co-design AI consent processes",
            ],
        },
        {
            "title": "The Path Forward: Strategic Recommendations",
            "content": (
                "Based on our analysis of 25 health system AI programs, we offer the following "
                "prioritized recommendations for executives initiating or accelerating their "
                "AI journey."
            ),
            "sections": [
                {
                    "heading": "Immediate Actions (0–90 Days)",
                    "content": (
                        "Conduct an AI Readiness Assessment covering data quality, infrastructure, "
                        "talent, and governance maturity. Appoint an AI Governance Committee with "
                        "cross-functional representation including clinicians, patients, and ethicists."
                    ),
                },
                {
                    "heading": "Medium-Term Priorities (6–18 Months)",
                    "content": (
                        "Launch 2–3 high-impact pilots in diagnostics or operational efficiency. "
                        "Establish a data platform capable of supporting AI at scale. "
                        "Build internal AI literacy through structured training programs."
                    ),
                },
            ],
            "bullets": [
                "Prioritize use cases with clear ROI AND equity benefit",
                "Partner with academic medical centers for clinical validation",
                "Publish model performance data to build trust with clinicians and patients",
            ],
        },
    ],
    "conclusion": (
        "AI in healthcare is not a question of if, but how. The organizations that move "
        "deliberately — with strong governance, inclusive design, and a relentless focus on "
        "clinical outcomes — will set the standard for the next decade of medicine. "
        "The opportunity is extraordinary. The responsibility is even greater. "
        "We invite you to partner with us on this journey."
    ),
}


# ── Runner ────────────────────────────────────────────────────────────────────

async def run_demo():
    print("\n" + "=" * 70)
    print("  DOCUMENT SUPER-AGENTS DEMO")
    print("  PPT Agent  •  Word Agent  •  PDF Agent  •  Quality Assessor")
    print("=" * 70)

    ppt_agent = PPTAgent(output_dir="output/ppt")
    word_agent = WordAgent(output_dir="output/word")
    pdf_agent = PDFAgent(output_dir="output/pdf")
    assessor = QualityAssessorAgent()

    generated = {}

    # ── 1. PowerPoint ────────────────────────────────────────────
    print("\n[1/4] Generating PowerPoint presentation...")
    result = await ppt_agent.execute(TaskContext(intent="ppt.create", parameters=PPT_PARAMS))
    if result.outcome.value == "success":
        path = result.data["file_path"]
        generated["pptx"] = path
        print(f"  ✓ PPT created: {path}")
        print(f"  ✓ Slides: {result.data['slide_count']}  |  Theme: {result.data['theme']}")
        print(f"  ✓ Structure: {' → '.join(result.data['structure'])}")
    else:
        print(f"  ✗ PPT FAILED: {result.errors}")

    # ── 2. Word Document ─────────────────────────────────────────
    print("\n[2/4] Generating Word document...")
    result = await word_agent.execute(TaskContext(intent="word.create", parameters=WORD_PARAMS))
    if result.outcome.value == "success":
        path = result.data["file_path"]
        generated["docx"] = path
        print(f"  ✓ Word doc created: {path}")
        print(f"  ✓ Sections: {result.data['section_count']}  |  Size: {result.data['size_kb']} KB")
        print(f"  ✓ Structure: {' → '.join(result.data['structure'])}")
    else:
        print(f"  ✗ Word FAILED: {result.errors}")

    # ── 3. PDF ───────────────────────────────────────────────────
    print("\n[3/4] Generating PDF report...")
    result = await pdf_agent.execute(TaskContext(intent="pdf.create", parameters=PDF_PARAMS))
    if result.outcome.value == "success":
        path = result.data["file_path"]
        generated["pdf"] = path
        print(f"  ✓ PDF created: {path}")
        print(f"  ✓ Pages: {result.data['page_count']}  |  Size: {result.data['size_kb']} KB")
        print(f"  ✓ Image source: {result.data['image_source']}")
        print(f"  ✓ People type: {result.data['people_type']}")
    else:
        print(f"  ✗ PDF FAILED: {result.errors}")

    # ── 4. Quality Assessment ─────────────────────────────────────
    print("\n[4/4] Running VP-Level Quality Assessment on all documents...")
    print("=" * 70)

    for file_type, path in generated.items():
        report_ctx = TaskContext(
            intent="quality.report",
            parameters={"file_path": path, "output_dir": "output/reports"},
        )
        report_result = await assessor.execute(report_ctx)
        if report_result.outcome.value == "success":
            d = report_result.data
            print(f"\n  [{file_type.upper()}] {Path(path).name}")
            print(f"  Overall Score : {d['overall_score']:.1f}/10  Grade: {d['grade']}")
            print(f"  VP Verdict    : {d['vp_verdict']}")
            print(f"  Full report   → {d['report_path']}")
            print()
            print(d["report_text"])
        else:
            print(f"  ✗ Assessment FAILED for {path}: {report_result.errors}")

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  GENERATION COMPLETE")
    print("=" * 70)
    print("\nGenerated files:")
    for ft, path in generated.items():
        size_kb = Path(path).stat().st_size // 1024
        print(f"  [{ft.upper():5}] {path}  ({size_kb} KB)")
    print("\nAssessment reports:")
    for p in Path("output/reports").glob("assessment_*.txt"):
        print(f"  {p}")
    print()


if __name__ == "__main__":
    asyncio.run(run_demo())
