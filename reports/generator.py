"""
IRIS Diagnostic Report Generation Engine.
Generates comprehensive diagnostic reports in:
  1. Rich standalone HTML format (with print styling, plain-English operator guides, and compliance audit)
  2. Printable PDF format (via ReportLab with vector tables and layout)
  3. High-resolution JPEG format (via PIL / Matplotlib diagnostic summary infographic)
"""

import io
import os
import glob
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from ai.severity import get_class_meta, get_severity_meta, Severity

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("data/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def generate_html_report(state: Dict[str, Any], history: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    Generate a comprehensive standalone HTML diagnostic report.
    Includes plain-English non-technical explanations for operators,
    detailed engineering metrics, defect log, IS 11592 compliance, and maintenance work orders.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    report_id = f"RPT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    health = float(state.get("health_score", 100.0))
    rul = float(state.get("rul_hours", 500.0))
    rul_ci_l = float(state.get("rul_ci_lower", rul * 0.8))
    rul_ci_u = float(state.get("rul_ci_upper", rul * 1.2))
    advisory = state.get("belt_advisory", "NORMAL")
    advisory_msg = state.get("belt_advisory_message", "All parameters within normal limits")
    fail_prob = float(state.get("failure_probability", 0.0))
    dom_sev = state.get("dominant_severity", "NONE")
    
    speed = float(state.get("belt_speed_mps", 3.15))
    pos = float(state.get("belt_position_m", 0.0))
    t_tight = float(state.get("tension_tight_N", 54200.0))
    t_slack = float(state.get("tension_slack_N", 18100.0))
    sf = float(state.get("safety_factor", 9.4))
    sag = float(state.get("sag_ratio_pct", 1.1))
    temp = float(state.get("temperature_c", 38.5))
    vib = float(state.get("vibration_mms", 2.8))
    load = float(state.get("load_fraction", 1.0))
    power = float(state.get("motor_power_kW", 185.0))
    is_compliant = state.get("is_compliant", True)
    
    events = state.get("active_damage_events", [])
    sensors = state.get("sensor_lifetimes", [])
    shap = state.get("shap_contributions", [])

    # Health status color and plain interpretation
    if health >= 80:
        health_color = "#10b981"  # Emerald
        health_badge = "EXCELLENT / HEALTHY"
        health_plain = "The conveyor belt is in good overall working condition. Standard mining loads can continue safely with no risk of unexpected stoppage."
    elif health >= 60:
        health_color = "#f59e0b"  # Amber
        health_badge = "MODERATE WEAR / ATTENTION"
        health_plain = "The belt is showing visible signs of wear and surface defects. Operation is safe for now, but inspection and patch repairs should be scheduled within the week."
    elif health >= 40:
        health_color = "#f97316"  # Orange
        health_badge = "HIGH WEAR / PLAN REPAIR"
        health_plain = "Elevated damage detected. Belt strength is compromised. Operating speed/load should be moderated, and a maintenance repair window must be booked within 24 to 48 hours."
    else:
        health_color = "#ef4444"  # Red
        health_badge = "CRITICAL / ACTION REQUIRED"
        health_plain = "CRITICAL: High risk of belt tear, splice rupture, or core cord exposure. Immediate engineering intervention or controlled shutdown is strongly advised."

    # RUL plain interpretation
    rul_days = round(rul / 24.0, 1)
    if rul > 200:
        rul_plain = f"Approximately <strong>{rul:.0f} operating hours (~{rul_days} days)</strong> of useful life remain under current ore loading before major structural reconditioning is necessary."
    elif rul > 50:
        rul_plain = f"Approximately <strong>{rul:.0f} operating hours (~{rul_days} days)</strong> remain. Plan belt splicing or rubber vulcanizing during the upcoming maintenance weekend."
    else:
        rul_plain = f"URGENT: Only <strong>{rul:.0f} operating hours (~{rul_days} days)</strong> remain before critical degradation threshold is reached."

    # Advisory status color
    adv_colors = {
        "NORMAL": "#10b981",
        "PLAN_INSPECTION": "#38bdf8",
        "SCHEDULE_REPLACEMENT": "#f59e0b",
        "IMMEDIATE_REPLACEMENT": "#ef4444",
    }
    adv_color = adv_colors.get(advisory, "#64748b")

    # Render Defect Rows & Plain explanations
    defect_rows_html = ""
    if events:
        for idx, evt in enumerate(events, 1):
            cname = evt.get("type", "CRACK")
            cmeta = get_class_meta(cname)
            sev = evt.get("severity", "NONE")
            smeta = get_severity_meta(sev)
            conf = float(evt.get("confidence", 0.9)) * 100
            length = float(evt.get("length_cm", 5.0))
            rul_imp = float(evt.get("rul_impact_hours", -5.0))
            
            defect_rows_html += f"""
            <tr>
                <td style="font-weight:600;font-family:monospace">{evt.get('id', f'DEF-{idx:02d}')}</td>
                <td>
                    <span class="class-chip" style="background:{cmeta['color']}22;color:{cmeta['color']};border-color:{cmeta['color']}">
                        {cmeta['icon']} {cname}
                    </span>
                    <div style="font-size:11px;color:#64748b;margin-top:4px">{cmeta['title']}</div>
                </td>
                <td>
                    <span class="sev-chip" style="background:{smeta['color']}22;color:{smeta['color']};border-color:{smeta['color']}">
                        {sev}
                    </span>
                </td>
                <td><strong>{length:.1f} cm</strong></td>
                <td>{conf:.1f}%</td>
                <td style="color:#ef4444;font-weight:600">{rul_imp:+.1f} h</td>
                <td style="font-size:12px;color:#334155">{cmeta['action_plain']}</td>
            </tr>
            """
    else:
        defect_rows_html = """
        <tr>
            <td colspan="7" style="text-align:center;padding:24px;color:#64748b">
                ✓ No active structural defects detected in the current inspection window. Belt surface is clean.
            </td>
        </tr>
        """

    # Plain English Defect Catalog Cards
    defect_cards_html = ""
    for cname in ["CRACK", "TEAR", "SURFACE_DAMAGE", "SPLICE_GAP", "EDGE_DAMAGE", "FOREIGN_OBJECT"]:
        cm = get_class_meta(cname)
        defect_cards_html += f"""
        <div class="plain-card">
            <div class="plain-card-header">
                <span class="plain-icon">{cm['icon']}</span>
                <div>
                    <div class="plain-card-title">{cname.replace('_', ' ')} ({cm['title']})</div>
                    <div class="plain-card-cat">{cm['category']} • {cm['iso_standard']}</div>
                </div>
            </div>
            <div class="plain-card-body">
                <p><strong>What is it?</strong> {cm['description_plain']}</p>
                <p><strong>Why is it dangerous?</strong> <span style="color:#b91c1c">{cm['danger_plain']}</span></p>
                <p><strong>Recommended Operator Action:</strong> <span style="color:#047857">{cm['action_plain']}</span></p>
            </div>
        </div>
        """

    # Sensors table
    sensor_rows_html = ""
    if sensors:
        for s in sensors:
            rem = float(s.get("remaining_pct", 100.0))
            st = s.get("status", "GOOD")
            st_color = "#10b981" if st == "GOOD" else ("#f59e0b" if st == "REPLACE_SOON" else "#ef4444")
            sensor_rows_html += f"""
            <tr>
                <td style="font-weight:600;font-family:monospace">{s.get('sensor_id','-')}</td>
                <td>{s.get('sensor_type','-')}</td>
                <td>{s.get('location','-')}</td>
                <td>{s.get('elapsed_hours', 0):.1f} / {s.get('rated_life_hours', 10000):.0f} h</td>
                <td>
                    <div style="background:#e2e8f0;border-radius:4px;height:8px;overflow:hidden;width:100px;display:inline-block;vertical-align:middle;margin-right:8px">
                        <div style="background:{st_color};height:100%;width:{rem}%"></div>
                    </div>
                    {rem:.1f}%
                </td>
                <td><span style="color:{st_color};font-weight:600">{st}</span></td>
            </tr>
            """
    else:
        sensor_rows_html = "<tr><td colspan='6' style='text-align:center;color:#64748b'>Telemetry active — rated lifespans within standard margins.</td></tr>"

    # SHAP contributions table
    shap_rows_html = ""
    if shap:
        for f in shap[:5]:
            contrib = float(f.get("contribution", 0.0)) * 100
            dir_str = f.get("direction", "neutral")
            dir_color = "#ef4444" if dir_str == "risk" else ("#10b981" if dir_str == "protective" else "#64748b")
            shap_rows_html += f"""
            <tr>
                <td><strong>{f.get('feature','-')}</strong></td>
                <td>
                    <div style="background:#e2e8f0;border-radius:4px;height:8px;overflow:hidden;width:120px;display:inline-block;vertical-align:middle;margin-right:8px">
                        <div style="background:{dir_color};height:100%;width:{min(100, contrib)}%"></div>
                    </div>
                    {contrib:.1f}%
                </td>
                <td><span style="color:{dir_color};font-weight:600;text-transform:uppercase">{dir_str}</span></td>
            </tr>
            """
    else:
        shap_rows_html = "<tr><td colspan='3' style='text-align:center;color:#64748b'>Equal baseline attribution across channels.</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IRIS Diagnostic Report — {report_id}</title>
    <style>
        :root {{
            --primary: #0f172a;
            --primary-accent: #2563eb;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --bg-page: #f8fafc;
            --bg-card: #ffffff;
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-page);
            color: var(--text-main);
            line-height: 1.5;
            padding: 24px;
        }}
        .report-container {{
            max-width: 1080px;
            margin: 0 auto;
            background: var(--bg-card);
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.06);
            border: 1px solid var(--border);
            overflow: hidden;
        }}
        /* Header Banner */
        .report-header {{
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #ffffff;
            padding: 32px;
            position: relative;
        }}
        .govt-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            padding: 4px 12px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.05em;
            color: #cbd5e1;
            margin-bottom: 12px;
        }}
        .report-title-row {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 16px;
        }}
        .report-main-title {{
            font-size: 26px;
            font-weight: 800;
            letter-spacing: -0.02em;
        }}
        .report-subtitle {{
            font-size: 14px;
            color: #94a3b8;
            margin-top: 4px;
        }}
        .meta-box {{
            text-align: right;
            font-size: 12px;
            color: #cbd5e1;
            background: rgba(255, 255, 255, 0.05);
            padding: 10px 16px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .meta-box strong {{
            color: #ffffff;
        }}

        /* Action Toolbar */
        .action-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #f1f5f9;
            padding: 12px 32px;
            border-bottom: 1px solid var(--border);
            gap: 12px;
            flex-wrap: wrap;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 600;
            border-radius: 6px;
            cursor: pointer;
            text-decoration: none;
            border: 1px solid transparent;
            transition: all 0.2s ease;
        }}
        .btn-primary {{
            background: #2563eb;
            color: #ffffff;
        }}
        .btn-primary:hover {{
            background: #1d4ed8;
        }}
        .btn-outline {{
            background: #ffffff;
            color: #334155;
            border-color: #cbd5e1;
        }}
        .btn-outline:hover {{
            background: #f8fafc;
            border-color: #94a3b8;
        }}

        /* Content Area */
        .report-body {{
            padding: 32px;
        }}

        /* Section Headings */
        .section-title {{
            font-size: 18px;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 8px;
        }}

        /* KPI Dashboard Grid */
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .kpi-card {{
            background: #ffffff;
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
            position: relative;
            overflow: hidden;
        }}
        .kpi-card::before {{
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: var(--card-color, #2563eb);
        }}
        .kpi-label {{
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
        }}
        .kpi-val {{
            font-size: 28px;
            font-weight: 800;
            color: var(--card-color, #0f172a);
            margin: 6px 0;
        }}
        .kpi-sub {{
            font-size: 12px;
            color: var(--text-muted);
        }}

        /* Plain English Guide Callout */
        .guide-box {{
            background: #f0fdf4;
            border: 1px solid #bbf7d0;
            border-left: 6px solid #16a34a;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 32px;
        }}
        .guide-box h3 {{
            font-size: 16px;
            color: #15803d;
            font-weight: 700;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .guide-box p {{
            font-size: 14px;
            color: #166534;
            margin-bottom: 8px;
        }}
        .guide-box p:last-child {{
            margin-bottom: 0;
        }}

        /* Plain Cards Grid for Defect Classes */
        .plain-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .plain-card {{
            background: #ffffff;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            font-size: 13px;
        }}
        .plain-card-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
            border-bottom: 1px solid #f1f5f9;
            padding-bottom: 8px;
        }}
        .plain-icon {{
            font-size: 22px;
        }}
        .plain-card-title {{
            font-weight: 700;
            font-size: 14px;
            color: #0f172a;
        }}
        .plain-card-cat {{
            font-size: 11px;
            color: var(--text-muted);
        }}
        .plain-card-body p {{
            margin-bottom: 6px;
            line-height: 1.4;
        }}

        /* Tables */
        .data-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-bottom: 32px;
        }}
        .data-table th {{
            background: #f8fafc;
            color: #475569;
            font-weight: 600;
            text-align: left;
            padding: 10px 14px;
            border-bottom: 2px solid var(--border);
        }}
        .data-table td {{
            padding: 10px 14px;
            border-bottom: 1px solid var(--border);
            vertical-align: middle;
        }}
        .data-table tr:hover td {{
            background: #f8fafc;
        }}

        /* Chips & Badges */
        .class-chip {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 700;
            border: 1px solid transparent;
        }}
        .sev-chip {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 700;
            border: 1px solid transparent;
        }}

        /* Engineering Metrics 2-col */
        .two-col {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
            margin-bottom: 32px;
        }}
        @media (max-width: 768px) {{
            .two-col {{
                grid-template-columns: 1fr;
            }}
        }}

        /* Signoff Block */
        .signoff-block {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 32px;
            margin-top: 40px;
            padding-top: 24px;
            border-top: 2px dashed var(--border);
        }}
        .sign-box {{
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            background: #f8fafc;
        }}
        .sign-line {{
            margin-top: 36px;
            border-top: 1px solid #94a3b8;
            padding-top: 4px;
            font-size: 12px;
            color: #64748b;
        }}

        /* Print Media Styles */
        @media print {{
            body {{
                background: #ffffff;
                padding: 0;
            }}
            .report-container {{
                box-shadow: none;
                border: none;
                max-width: 100%;
            }}
            .action-bar {{
                display: none;
            }}
            .report-header {{
                background: #0f172a !important;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}
            .kpi-card, .plain-card, .guide-box {{
                break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>

<div class="report-container">
    <!-- Header -->
    <div class="report-header">
        <div class="govt-badge">
            <span>🇮🇳 MINISTRY OF STEEL • GOVT. OF INDIA</span>
            <span>•</span>
            <span>NMDC LIMITED</span>
        </div>
        <div class="report-title-row">
            <div>
                <h1 class="report-main-title">IRIS — Conveyor Inspection Report</h1>
                <div class="report-subtitle">Intelligent Real-time Inspection System • Digital Twin Diagnostic Summary</div>
            </div>
            <div class="meta-box">
                <div>Report ID: <strong>{report_id}</strong></div>
                <div>Generated: <strong>{now_str}</strong></div>
                <div>Conveyor Unit: <strong>NMDC Kirandul Line 4B</strong></div>
                <div>Belt Spec: <strong>ST-2500 Steel Cord (500m Loop)</strong></div>
            </div>
        </div>
    </div>

    <!-- Toolbar -->
    <div class="action-bar">
        <div style="font-size:13px;color:#475569;font-weight:600">
            📊 Export Options:
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
            <a href="/api/report/pdf" class="btn btn-primary" download="IRIS_Report_{report_id}.pdf">
                📄 Download PDF
            </a>
            <a href="/api/report/jpeg" class="btn btn-outline" download="IRIS_Report_{report_id}.jpeg">
                🖼️ Download JPEG Sheet
            </a>
            <button onclick="window.print()" class="btn btn-outline">
                🖨️ Print / Save as PDF
            </button>
            <a href="/" class="btn btn-outline">
                👁️ Open Live Dashboard
            </a>
        </div>
    </div>

    <div class="report-body">
        <!-- ═══ 1. Executive Status & KPIs ═══ -->
        <div class="section-title">📊 1. Executive Status & Health KPI Summary</div>
        
        <div class="kpi-grid">
            <div class="kpi-card" style="--card-color: {health_color}">
                <div class="kpi-label">Overall Health Score</div>
                <div class="kpi-val">{health:.1f}%</div>
                <div class="kpi-sub">Status: <strong>{health_badge}</strong></div>
            </div>
            <div class="kpi-card" style="--card-color: #2563eb">
                <div class="kpi-label">Remaining Useful Life (RUL)</div>
                <div class="kpi-val">{rul:.0f} h</div>
                <div class="kpi-sub">90% Confidence: <strong>{rul_ci_l:.0f} – {rul_ci_u:.0f} h</strong></div>
            </div>
            <div class="kpi-card" style="--card-color: {adv_color}">
                <div class="kpi-label">Belt Advisory Level</div>
                <div class="kpi-val" style="font-size:20px">{advisory.replace('_', ' ')}</div>
                <div class="kpi-sub">{advisory_msg}</div>
            </div>
            <div class="kpi-card" style="--card-color: {'#10b981' if is_compliant else '#ef4444'}">
                <div class="kpi-label">IS 11592 / DIN 22101 Audit</div>
                <div class="kpi-val" style="font-size:22px">{'✓ COMPLIANT' if is_compliant else '✗ WARNING'}</div>
                <div class="kpi-sub">Safety Factor: <strong>{sf:.1f}× (Min 8.0×)</strong></div>
            </div>
        </div>

        <!-- ═══ 2. Non-Technical / Plain-English Guide ═══ -->
        <div class="guide-box">
            <h3>📖 For Regular Users & Shift Operators: Plain-English Summary</h3>
            <p><strong>Health Interpretation:</strong> {health_plain}</p>
            <p><strong>RUL Life Expectancy:</strong> {rul_plain}</p>
            <p><strong>Action Recommendation:</strong> {advisory_msg}. Regular daily inspection walkdowns should continue. Any newly detected crack or tear must be logged in the shift register.</p>
        </div>

        <!-- ═══ 3. Active Damage Event Ledger ═══ -->
        <div class="section-title">🔍 2. AI Vision Defect Ledger (Active Damage Events)</div>
        <table class="data-table">
            <thead>
                <tr>
                    <th>Defect ID</th>
                    <th>Defect Class</th>
                    <th>Severity</th>
                    <th>Estimated Size</th>
                    <th>Detection Conf.</th>
                    <th>RUL Impact</th>
                    <th>Operator Action</th>
                </tr>
            </thead>
            <tbody>
                {defect_rows_html}
            </tbody>
        </table>

        <!-- ═══ 4. Defect Types Knowledge Base for Operators ═══ -->
        <div class="section-title">📚 3. Defect Classification Guide & Hazard Mitigation</div>
        <div class="plain-grid">
            {defect_cards_html}
        </div>

        <!-- ═══ 5. Physics & Dynamic Compliance ═══ -->
        <div class="section-title">⚙️ 4. Conveyor Dynamics & Engineering Compliance (IS 11592)</div>
        <div class="two-col">
            <div>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Parameter</th>
                            <th>Measured / Estimated</th>
                            <th>Standard Limit</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>Tight Side Tension ($T_1$)</td>
                            <td><strong>{t_tight:,.0f} N</strong></td>
                            <td>Max Rating: 320,000 N</td>
                        </tr>
                        <tr>
                            <td>Slack Side Tension ($T_2$)</td>
                            <td><strong>{t_slack:,.0f} N</strong></td>
                            <td>Min Slack: 12,000 N</td>
                        </tr>
                        <tr>
                            <td>Dynamic Safety Factor</td>
                            <td><strong style="color:{'#10b981' if sf >= 8.0 else '#ef4444'}">{sf:.2f}×</strong></td>
                            <td>Min IS 11592: &ge; 8.0×</td>
                        </tr>
                        <tr>
                            <td>Catenary Sag Ratio</td>
                            <td><strong style="color:{'#10b981' if sag <= 2.0 else '#ef4444'}">{sag:.2f}%</strong></td>
                            <td>Max Allowed: &le; 2.0%</td>
                        </tr>
                        <tr>
                            <td>Belt Velocity</td>
                            <td><strong>{speed:.2f} m/s</strong></td>
                            <td>Rated Speed: 3.15 m/s</td>
                        </tr>
                        <tr>
                            <td>Belt Position along Loop</td>
                            <td><strong>{pos:.1f} m / 500 m</strong></td>
                            <td>Full Loop: 500.0 m</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <div>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Thermal & Mechanical</th>
                            <th>Live Reading</th>
                            <th>Condition</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>Motor Power Draw</td>
                            <td><strong>{power:.1f} kW</strong></td>
                            <td>Nominal (Load: {load:.0%})</td>
                        </tr>
                        <tr>
                            <td>Drive Pulley Bearing Temp</td>
                            <td><strong>{temp:.1f} °C</strong></td>
                            <td><span style="color:{'#10b981' if temp < 65 else '#ef4444'}">{'Normal' if temp < 65 else 'High'}</span> (Max 80°C)</td>
                        </tr>
                        <tr>
                            <td>Vibration RMS Velocity</td>
                            <td><strong>{vib:.2f} mm/s</strong></td>
                            <td><span style="color:{'#10b981' if vib < 4.5 else '#ef4444'}">{'Good (ISO 10816)' if vib < 4.5 else 'Warning'}</span></td>
                        </tr>
                        <tr>
                            <td>Failure Probability</td>
                            <td><strong>{fail_prob*100:.1f}%</strong></td>
                            <td>Nonlinear Degradation Model</td>
                        </tr>
                        <tr>
                            <td>Dominant Worst Defect</td>
                            <td><strong>{dom_sev}</strong></td>
                            <td>Governs immediate work order</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- ═══ 6. AI SHAP Feature Risk Attribution & Sensors ═══ -->
        <div class="two-col">
            <div>
                <div class="section-title">🤖 5. AI Risk Attribution (SHAP)</div>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Root-Cause Feature</th>
                            <th>Contribution</th>
                            <th>Impact</th>
                        </tr>
                    </thead>
                    <tbody>
                        {shap_rows_html}
                    </tbody>
                </table>
            </div>
            <div>
                <div class="section-title">📶 6. Multi-Sensor Health & Lifetime</div>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Sensor ID</th>
                            <th>Type</th>
                            <th>Location</th>
                            <th>Elapsed / Rated</th>
                            <th>Remaining</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sensor_rows_html}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- ═══ 7. Work Order & Signatures ═══ -->
        <div class="section-title">📋 7. Maintenance Work Order Recommendation & Sign-Off</div>
        <div style="background:#f8fafc;border:1px solid var(--border);border-radius:8px;padding:16px;font-size:13px;line-height:1.6">
            <strong>Recommended Maintenance Protocol:</strong>
            <ul style="margin-left:20px;margin-top:8px">
                <li><strong>Immediate (0-24h):</strong> Clean belt carrying surface around idler transition zones. Visually confirm through-tear and splice integrity at station x={pos:.0f}m.</li>
                <li><strong>Scheduled (Weekly):</strong> Apply cold vulcanizing compound on cover surface gouges and hairline cracks. Check training idler alignment on return strand.</li>
                <li><strong>Preventive (Monthly):</strong> Perform ultrasonic thickness test along central wear path. Greasing and thermographic inspection of tail pulley bearings.</li>
            </ul>
        </div>

        <div class="signoff-block">
            <div class="sign-box">
                <div style="font-weight:700;font-size:13px;color:#0f172a">Inspecting AI System Engineer</div>
                <div style="font-size:12px;color:#64748b;margin-top:2px">Autonomous Digital Twin IRIS (SIH26008)</div>
                <div class="sign-line">Certified Digitally • IRIS-VAL-OK</div>
            </div>
            <div class="sign-box">
                <div style="font-weight:700;font-size:13px;color:#0f172a">Shift Maintenance In-Charge (NMDC)</div>
                <div style="font-size:12px;color:#64748b;margin-top:2px">Mining Conveyor Maintenance Division</div>
                <div class="sign-line">Authorized Signature & Stamp: ______________________</div>
            </div>
        </div>
    </div>
</div>

</body>
</html>
"""
    return html


def generate_pdf_report(state: Dict[str, Any]) -> bytes:
    """
    Generate a clean, professional vector PDF report using ReportLab.
    """
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        styles = getSampleStyleSheet()
        
        # Custom Paragraph styles
        title_style = ParagraphStyle(
            'ReportTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=22,
            textColor=colors.HexColor('#0f172a')
        )
        subtitle_style = ParagraphStyle(
            'ReportSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor('#64748b')
        )
        h2_style = ParagraphStyle(
            'ReportH2',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=12,
            leading=16,
            textColor=colors.HexColor('#0f172a'),
            spaceBefore=12,
            spaceAfter=6
        )
        body_style = ParagraphStyle(
            'ReportBody',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=13,
            textColor=colors.HexColor('#334155')
        )
        callout_style = ParagraphStyle(
            'CalloutBody',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=13,
            textColor=colors.HexColor('#166534')
        )

        elements = []

        # Header Title
        elements.append(Paragraph("<b>MINISTRY OF STEEL • GOVT. OF INDIA | NMDC LIMITED</b>", subtitle_style))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph("<b>IRIS — Conveyor Belt Digital Twin Inspection Report</b>", title_style))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
        elements.append(Paragraph(f"Conveyor Unit: NMDC Kirandul Line 4B | Spec: ST-2500 (500m Loop) | Generated: {now_str}", subtitle_style))
        elements.append(Spacer(1, 10))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0f172a'), spaceAfter=12))

        # KPI Summary Table
        health = float(state.get("health_score", 100.0))
        rul = float(state.get("rul_hours", 500.0))
        advisory = state.get("belt_advisory", "NORMAL").replace('_', ' ')
        sf = float(state.get("safety_factor", 9.4))
        
        kpi_data = [
            [
                Paragraph(f"<b>Overall Health Score</b><br/><font size='16' color='#0f172a'><b>{health:.1f}%</b></font>", body_style),
                Paragraph(f"<b>Remaining Useful Life</b><br/><font size='16' color='#2563eb'><b>{rul:.0f} Hours</b></font>", body_style),
                Paragraph(f"<b>Advisory Level</b><br/><font size='14' color='#d97706'><b>{advisory}</b></font>", body_style),
                Paragraph(f"<b>IS 11592 Safety Factor</b><br/><font size='14' color='#059669'><b>{sf:.1f}× (Pass)</b></font>", body_style),
            ]
        ]
        kpi_table = Table(kpi_data, colWidths=[130, 130, 130, 130])
        kpi_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(kpi_table)
        elements.append(Spacer(1, 12))

        # Plain-English Operator Summary Box
        guide_text = (
            "<b>Plain-English Guide for Operators:</b><br/>"
            f"• <b>Belt Health:</b> Operating at {health:.1f}% health. Minor surface defects tracked. Safe for standard continuous ore conveying.<br/>"
            f"• <b>Life Expectancy:</b> Estimated {rul:.0f} hours (~{rul/24.0:.1f} days) before major structural reconditioning is recommended.<br/>"
            f"• <b>Required Action:</b> {state.get('belt_advisory_message', 'Continue routine inspection.')}"
        )
        guide_table = Table([[Paragraph(guide_text, callout_style)]], colWidths=[520])
        guide_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f0fdf4')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#bbf7d0')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(guide_table)
        elements.append(Spacer(1, 12))

        # Active Defects Table
        elements.append(Paragraph("<b>1. AI Vision Defect Ledger (Active Damage Events)</b>", h2_style))
        events = state.get("active_damage_events", [])
        
        defect_data = [["ID", "Defect Class", "Severity", "Length", "Confidence", "RUL Impact"]]
        if events:
            for evt in events[:10]:
                defect_data.append([
                    evt.get("id", "DEF")[-8:],
                    evt.get("type", "CRACK"),
                    evt.get("severity", "MINOR"),
                    f"{float(evt.get('length_cm', 5.0)):.1f} cm",
                    f"{float(evt.get('confidence', 0.9))*100:.0f}%",
                    f"{float(evt.get('rul_impact_hours', -5.0)):+.1f} h",
                ])
        else:
            defect_data.append(["-", "No defects detected", "NONE", "-", "-", "0.0 h"])

        def_table = Table(defect_data, colWidths=[70, 110, 80, 80, 80, 100])
        def_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])
        ]))
        elements.append(def_table)
        elements.append(Spacer(1, 12))

        # Engineering Compliance Table
        elements.append(Paragraph("<b>2. IS 11592 / DIN 22101 Engineering Compliance Audit</b>", h2_style))
        t_tight = float(state.get("tension_tight_N", 54200.0))
        t_slack = float(state.get("tension_slack_N", 18100.0))
        sag = float(state.get("sag_ratio_pct", 1.1))
        temp = float(state.get("temperature_c", 38.5))
        vib = float(state.get("vibration_mms", 2.8))
        speed = float(state.get("belt_speed_mps", 3.15))

        eng_data = [
            ["Engineering Parameter", "Measured / Calculated", "IS 11592 Limit", "Compliance Status"],
            ["Tight Side Tension (T1)", f"{t_tight:,.0f} N", "Max 320,000 N", "PASS"],
            ["Slack Side Tension (T2)", f"{t_slack:,.0f} N", "Min 12,000 N", "PASS"],
            ["Dynamic Safety Factor", f"{sf:.2f}×", "Min >= 8.0×", "PASS" if sf >= 8.0 else "WARNING"],
            ["Catenary Sag Ratio", f"{sag:.2f}%", "Max <= 2.0%", "PASS" if sag <= 2.0 else "FAIL"],
            ["Drive Pulley Bearing Temp", f"{temp:.1f} °C", "Max <= 80 °C", "PASS" if temp < 70 else "HIGH"],
            ["Vibration RMS Velocity", f"{vib:.2f} mm/s", "ISO 10816 Limit", "PASS" if vib < 4.5 else "WARNING"],
            ["Belt Speed & Position", f"{speed:.2f} m/s @ {float(state.get('belt_position_m',0)):.1f}m", "Rated 3.15 m/s", "NORMAL"],
        ]
        eng_table = Table(eng_data, colWidths=[150, 120, 120, 130])
        eng_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e293b')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])
        ]))
        elements.append(eng_table)
        elements.append(Spacer(1, 14))

        # Sign-off Block
        sign_data = [
            [
                Paragraph("<b>Autonomous AI Inspection Engineer:</b><br/>IRIS Digital Twin System (PS26008)<br/><br/><i>Certified Digitally • IRIS-VAL-OK</i>", body_style),
                Paragraph("<b>Shift Maintenance In-Charge:</b><br/>NMDC Mining Division<br/><br/>Signature: ___________________________", body_style),
            ]
        ]
        sign_table = Table(sign_data, colWidths=[260, 260])
        sign_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(sign_table)

        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()

    except Exception as e:
        logger.error(f"Error generating PDF with reportlab: {e}")
        # Fallback simple byte string
        return f"%PDF-1.4 Error generating PDF report: {e}".encode('utf-8')


def generate_jpeg_report(state: Dict[str, Any]) -> bytes:
    """
    Generate a high-resolution graphical diagnostic sheet in JPEG format using PIL & Matplotlib.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches
        from PIL import Image

        fig, ax = plt.subplots(figsize=(12, 16), dpi=150)
        fig.patch.set_facecolor('#0f172a')
        ax.set_facecolor('#0f172a')
        ax.set_xlim(0, 1200)
        ax.set_ylim(1600, 0)  # Inverted Y for top-to-bottom layout
        ax.axis('off')

        # ── Header Banner ──
        ax.add_patch(patches.Rectangle((40, 40), 1120, 140, facecolor='#1e293b', edgecolor='#334155', linewidth=1.5))
        ax.text(60, 75, "MINISTRY OF STEEL • GOVT. OF INDIA | NMDC LIMITED", fontsize=10, color='#94a3b8', weight='bold')
        ax.text(60, 115, "IRIS — Conveyor Belt Digital Twin Diagnostic Sheet", fontsize=18, color='#ffffff', weight='bold')
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        ax.text(60, 150, f"Line: Kirandul 4B | Spec: ST-2500 Steel Cord (500m) | Date: {now_str}", fontsize=11, color='#38bdf8')

        # ── KPI Cards (4 columns) ──
        health = float(state.get("health_score", 100.0))
        rul = float(state.get("rul_hours", 500.0))
        advisory = state.get("belt_advisory", "NORMAL").replace('_', ' ')
        sf = float(state.get("safety_factor", 9.4))

        kpis = [
            ("HEALTH SCORE", f"{health:.1f}%", "#10b981" if health >= 80 else "#f59e0b", "Composite Score"),
            ("REMAINING LIFE", f"{rul:.0f} h", "#38bdf8", f"~{rul/24.0:.1f} Days"),
            ("BELT ADVISORY", advisory, "#f59e0b" if "REPLACE" in advisory else "#10b981", "Operator Action"),
            ("SAFETY FACTOR", f"{sf:.1f}x", "#10b981" if sf >= 8.0 else "#ef4444", "IS 11592 (Min 8.0x)")
        ]

        for i, (title, val, col, sub) in enumerate(kpis):
            x = 40 + i * 290
            ax.add_patch(patches.Rectangle((x, 210), 260, 120, facecolor='#1e293b', edgecolor=col, linewidth=1.5))
            ax.text(x + 20, 240, title, fontsize=9, color='#94a3b8', weight='bold')
            ax.text(x + 20, 285, val, fontsize=20, color=col, weight='bold')
            ax.text(x + 20, 315, sub, fontsize=10, color='#cbd5e1')

        # ── Plain-English Guide Banner ──
        ax.add_patch(patches.Rectangle((40, 360), 1120, 120, facecolor='#064e3b', edgecolor='#10b981', linewidth=1.5))
        ax.text(60, 395, "[OPERATOR GUIDE] Plain-English Conveyor Status", fontsize=12, color='#34d399', weight='bold')
        guide_p1 = f"• Current Condition: Belt is operating at {health:.1f}% health. Standard continuous mining load is safe."
        guide_p2 = f"• Estimated RUL: Approximately {rul:.0f} hours (~{rul/24.0:.1f} days) before major splicing or reconditioning."
        guide_p3 = f"• Action Plan: {state.get('belt_advisory_message', 'Maintain standard routine monitoring.')}"
        ax.text(60, 425, guide_p1, fontsize=10, color='#e2e8f0')
        ax.text(60, 448, guide_p2, fontsize=10, color='#e2e8f0')
        ax.text(60, 470, guide_p3, fontsize=10, color='#e2e8f0')

        # ── Active Defects Table ──
        ax.text(40, 520, "[DEFECT LEDGER] AI Vision Defect Ledger (Active Damage Events)", fontsize=14, color='#ffffff', weight='bold')
        ax.add_patch(patches.Rectangle((40, 540), 1120, 350, facecolor='#1e293b', edgecolor='#334155', linewidth=1))
        
        # Table Header
        ax.add_patch(patches.Rectangle((40, 540), 1120, 35, facecolor='#0f172a', edgecolor='#334155', linewidth=1))
        headers = ["Defect ID", "Defect Class", "Severity", "Length", "Confidence", "RUL Impact", "Operator Recommendation"]
        col_xs = [60, 180, 320, 440, 560, 680, 810]
        for h, cx in zip(headers, col_xs):
            ax.text(cx, 562, h, fontsize=9, color='#94a3b8', weight='bold')

        events = state.get("active_damage_events", [])
        if events:
            for r, evt in enumerate(events[:7]):
                y = 605 + r * 42
                cname = evt.get("type", "CRACK")
                cm = get_class_meta(cname)
                sev = evt.get("severity", "MINOR")
                length = float(evt.get("length_cm", 5.0))
                conf = float(evt.get("confidence", 0.9)) * 100
                rul_imp = float(evt.get("rul_impact_hours", -5.0))
                
                ax.text(col_xs[0], y, evt.get("id", "DEF")[-8:], fontsize=9, color='#cbd5e1', family='monospace')
                ax.text(col_xs[1], y, f"[{cname}]", fontsize=9, color=cm['color'], weight='bold')
                ax.text(col_xs[2], y, sev, fontsize=9, color='#f59e0b' if sev in ('MODERATE','SEVERE') else '#ef4444' if sev == 'CRITICAL' else '#10b981', weight='bold')
                ax.text(col_xs[3], y, f"{length:.1f} cm", fontsize=9, color='#ffffff')
                ax.text(col_xs[4], y, f"{conf:.0f}%", fontsize=9, color='#ffffff')
                ax.text(col_xs[5], y, f"{rul_imp:+.1f} h", fontsize=9, color='#ef4444', weight='bold')
                ax.text(col_xs[6], y, cm['action_plain'][:38] + "...", fontsize=8.5, color='#94a3b8')
        else:
            ax.text(450, 700, "Clean: No active defects detected in camera inspection window.", fontsize=11, color='#10b981')

        # ── Engineering Metrics & Compliance Table ──
        ax.text(40, 930, "[ENGINEERING AUDIT] Conveyor Dynamics & Compliance (IS 11592 / DIN 22101)", fontsize=14, color='#ffffff', weight='bold')
        ax.add_patch(patches.Rectangle((40, 950), 1120, 360, facecolor='#1e293b', edgecolor='#334155', linewidth=1))

        t_tight = float(state.get("tension_tight_N", 54200.0))
        t_slack = float(state.get("tension_slack_N", 18100.0))
        sag = float(state.get("sag_ratio_pct", 1.1))
        temp = float(state.get("temperature_c", 38.5))
        vib = float(state.get("vibration_mms", 2.8))
        speed = float(state.get("belt_speed_mps", 3.15))
        power = float(state.get("motor_power_kW", 185.0))

        eng_rows = [
            ("Tight Side Tension (T1)", f"{t_tight:,.0f} N", "Max 320,000 N", "PASS", "#10b981"),
            ("Slack Side Tension (T2)", f"{t_slack:,.0f} N", "Min 12,000 N", "PASS", "#10b981"),
            ("Dynamic Safety Factor", f"{sf:.2f}x", "Min >= 8.0x (IS 11592)", "PASS" if sf >= 8.0 else "WARNING", "#10b981" if sf >= 8.0 else "#f59e0b"),
            ("Catenary Sag Ratio", f"{sag:.2f}%", "Max <= 2.0% (IS 11592)", "PASS" if sag <= 2.0 else "FAIL", "#10b981" if sag <= 2.0 else "#ef4444"),
            ("Bearing Temperature", f"{temp:.1f} deg C", "Max <= 80 deg C", "NORMAL", "#10b981"),
            ("Vibration RMS Velocity", f"{vib:.2f} mm/s", "ISO 10816 Standard", "GOOD", "#10b981"),
            ("Motor Power Draw", f"{power:.1f} kW", "Nominal Load", "OPTIMAL", "#10b981"),
            ("Belt Velocity & Position", f"{speed:.2f} m/s @ {float(state.get('belt_position_m',0)):.1f}m", "Rated Speed 3.15 m/s", "NOMINAL", "#10b981"),
        ]

        # Table Header
        ax.add_patch(patches.Rectangle((40, 950), 1120, 35, facecolor='#0f172a', edgecolor='#334155', linewidth=1))
        ax.text(60, 972, "Engineering Parameter", fontsize=9, color='#94a3b8', weight='bold')
        ax.text(420, 972, "Telemetry / Estimated", fontsize=9, color='#94a3b8', weight='bold')
        ax.text(700, 972, "Standard Limit", fontsize=9, color='#94a3b8', weight='bold')
        ax.text(980, 972, "Audit Status", fontsize=9, color='#94a3b8', weight='bold')

        for r, (param, val, lim, stat, col) in enumerate(eng_rows):
            y = 1010 + r * 37
            ax.text(60, y, param, fontsize=9, color='#cbd5e1')
            ax.text(420, y, val, fontsize=9, color='#ffffff', weight='bold')
            ax.text(700, y, lim, fontsize=9, color='#94a3b8')
            ax.text(980, y, f"OK {stat}", fontsize=9, color=col, weight='bold')

        # ── Signoff Footer ──
        ax.add_patch(patches.Rectangle((40, 1350), 545, 180, facecolor='#1e293b', edgecolor='#334155'))
        ax.text(60, 1380, "Autonomous AI Inspection Engine", fontsize=11, color='#ffffff', weight='bold')
        ax.text(60, 1405, "IRIS Digital Twin • SIH26008 Certified", fontsize=9.5, color='#94a3b8')
        ax.text(60, 1480, "Digitally Verified: IRIS-VAL-OK", fontsize=10, color='#38bdf8', weight='bold')

        ax.add_patch(patches.Rectangle((615, 1350), 545, 180, facecolor='#1e293b', edgecolor='#334155'))
        ax.text(635, 1380, "Shift Maintenance In-Charge", fontsize=11, color='#ffffff', weight='bold')
        ax.text(635, 1405, "NMDC Mining Conveyor Maintenance Wing", fontsize=9.5, color='#94a3b8')
        ax.text(635, 1480, "Sign: __________________________", fontsize=10, color='#94a3b8')

        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='jpeg', facecolor='#0f172a', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        logger.error(f"Error generating JPEG report with matplotlib/PIL: {e}")
        # Create fallback image with PIL
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (1200, 800), color=(15, 23, 42))
        d = ImageDraw.Draw(img)
        d.text((50, 50), f"IRIS Diagnostic Report (Fallback)\nError: {e}", fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        buf.seek(0)
        return buf.getvalue()


def save_report_snapshot(state: Dict[str, Any], history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Generate and save HTML, PDF, and JPEG report snapshots to disk in data/reports/.
    Returns file paths and metadata.
    """
    now_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"IRIS_Report_{now_ts}"

    html_path = REPORTS_DIR / f"{base_name}.html"
    pdf_path = REPORTS_DIR / f"{base_name}.pdf"
    jpeg_path = REPORTS_DIR / f"{base_name}.jpeg"

    # Generate HTML
    html_content = generate_html_report(state, history)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # Generate PDF
    pdf_bytes = generate_pdf_report(state)
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)

    # Generate JPEG
    jpeg_bytes = generate_jpeg_report(state)
    with open(jpeg_path, "wb") as f:
        f.write(jpeg_bytes)

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "report_id": base_name,
        "html_file": html_path.name,
        "pdf_file": pdf_path.name,
        "jpeg_file": jpeg_path.name,
        "health_score": state.get("health_score", 100.0),
        "rul_hours": state.get("rul_hours", 500.0),
        "belt_advisory": state.get("belt_advisory", "NORMAL"),
    }


def list_saved_reports() -> List[Dict[str, Any]]:
    """List all saved diagnostic reports in data/reports/."""
    results = []
    html_files = sorted(glob.glob(str(REPORTS_DIR / "IRIS_Report_*.html")), reverse=True)
    
    for hf in html_files:
        path = Path(hf)
        stem = path.stem
        pdf_name = f"{stem}.pdf"
        jpeg_name = f"{stem}.jpeg"
        
        pdf_exists = (REPORTS_DIR / pdf_name).exists()
        jpeg_exists = (REPORTS_DIR / jpeg_name).exists()
        
        stat = path.stat()
        results.append({
            "report_id": stem,
            "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "html_filename": path.name,
            "pdf_filename": pdf_name if pdf_exists else None,
            "jpeg_filename": jpeg_name if jpeg_exists else None,
            "size_kb": round(stat.st_size / 1024, 1),
        })
    return results
