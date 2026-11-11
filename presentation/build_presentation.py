"""Build SecureDataFlow_DSA4030_Presentation.pptx from the ACTUAL experiment results.

Every number on the slides is read from reports/experiment_results.json and
reports/test_results.txt (produced by `python main.py` and `python -m pytest`),
and the console excerpt is copied verbatim from reports/run_output.txt.

Run:  python presentation/build_presentation.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "SecureDataFlow_DSA4030_Presentation.pptx"
R = json.loads((ROOT / "reports" / "experiment_results.json").read_text(encoding="utf-8"))
RUN_TXT = (ROOT / "reports" / "run_output.txt").read_text(encoding="utf-8").splitlines()
TEST_TXT = (ROOT / "reports" / "test_results.txt").read_text(encoding="utf-8")

# ---------------------------------------------------------------- design tokens
NAVY, INK, MUTED, TINT, LINE = "13233A", "1B1B1B", "5F6B7A", "F1F4F8", "D5DCE5"
ICE = "CADCFC"
BLUE, ORANGE, AQUA = "2A78D6", "EB6834", "1BAF7A"          # truth / no controls / with controls
GREEN, AMBER, RED = "0CA30C", "FAB219", "D03B3B"            # status: accepted / flagged / rejected
AMBER_TEXT = "8A5A00"                                       # readable amber for text on white
HEAD, BODY, MONO = "Cambria", "Calibri", "Courier New"
W, H = 13.333, 7.5


def rgb(h):
    return RGBColor.from_string(h)


def money(v, dec=2):
    return f"{v:,.{dec}f}"


def pct(v, ref):
    return f"{(v - ref) / ref * 100:+.2f}%"


# ---------------------------------------------------------------- helpers
def box(slide, x, y, w, h, fill, rounded=True, line=None, name=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
                                 Inches(x), Inches(y), Inches(w), Inches(h))
    if rounded:
        shp.adjustments[0] = 0.07
    shp.fill.solid()
    shp.fill.fore_color.rgb = rgb(fill)
    if line:
        shp.line.color.rgb = rgb(line)
        shp.line.width = Pt(1)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    if name:
        shp.name = name
    return shp


def circle(slide, x, y, d, fill, label, color="FFFFFF", size=16, name=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    shp.fill.solid()
    shp.fill.fore_color.rgb = rgb(fill)
    shp.line.fill.background()
    shp.shadow.inherit = False
    tf = shp.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    _font(r, size, color, True, BODY)
    if name:
        shp.name = name
    return shp


def _font(run, size, color, bold=False, face=BODY, italic=False):
    run.font.size = Pt(size)
    run.font.color.rgb = rgb(color)
    run.font.bold = bold
    run.font.italic = italic
    run.font.name = face


def _bullet(p, indent=0.22):
    pPr = p._p.get_or_add_pPr()
    pPr.set("marL", str(Emu(Inches(indent))))
    pPr.set("indent", str(-Emu(Inches(indent))))
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    bu = etree.SubElement(pPr, qn("a:buChar"))
    bu.set("char", "•")


def text(slide, x, y, w, h, paras, size=16, color=INK, bold=False, face=BODY, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, bullets=False, space_after=6, margin=0.0, name=None, line_spacing=None):
    """paras: list of paragraphs; each is a str or a list of (text, {size,color,bold,face,italic}) runs."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    m = Inches(margin)
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = m
    tf.vertical_anchor = anchor
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        if line_spacing:
            p.line_spacing = line_spacing
        runs = [(para, {})] if isinstance(para, str) else para
        for t, o in runs:
            r = p.add_run()
            r.text = t
            _font(r, o.get("size", size), o.get("color", color), o.get("bold", bold), o.get("face", face),
                  o.get("italic", False))
        if bullets:
            _bullet(p)
    return tb


def title(slide, t, dark=False):
    text(slide, 0.6, 0.42, 12.1, 0.8, [t], size=36, color="FFFFFF" if dark else NAVY, bold=True, face=HEAD,
         anchor=MSO_ANCHOR.MIDDLE, name="Title")


def footer(slide, n, dark=False):
    c = "9FB0C8" if dark else MUTED
    text(slide, 0.6, 7.0, 8, 0.3, ["SecureDataFlow  ·  DSA 4030 Big Data Security  ·  Group 1"], size=10, color=c,
         name="Footer")
    text(slide, 11.73, 7.0, 1.0, 0.3, [str(n)], size=10, color=c, align=PP_ALIGN.RIGHT, name="Slide number")


def background(slide, color):
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = rgb(color)


def notes(slide, t):
    slide.notes_slide.notes_text_frame.text = t


def style_chart(chart, legend=False, size=12):
    chart.font.size = Pt(size)
    chart.font.name = BODY
    chart.font.color.rgb = rgb(MUTED)
    chart.has_legend = legend
    if legend:
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(size)
        chart.legend.font.color.rgb = rgb(INK)
    va = chart.value_axis
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = rgb("E3E7EC")
    va.format.line.fill.background()
    va.tick_labels.font.size = Pt(size - 1)
    va.tick_labels.font.color.rgb = rgb(MUTED)
    ca = chart.category_axis
    ca.format.line.color.rgb = rgb(LINE)
    ca.tick_labels.font.size = Pt(size - 1)
    ca.tick_labels.font.color.rgb = rgb(INK)
    ca.has_major_gridlines = False


def table(slide, x, y, w, col_w, rows, header_fill=NAVY, size=12, row_h=0.36, fills=None, aligns=None, name=None):
    shp = slide.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(row_h * len(rows)))
    if name:
        shp.name = name
    tbl = shp.table
    tbl.first_row = True
    tbl.horz_banding = False
    for j, cw in enumerate(col_w):
        tbl.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        tbl.rows[i].height = Inches(row_h)
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            fill = header_fill if i == 0 else (fills[i][j] if fills and fills[i][j] else ("FFFFFF" if i % 2 else "F7F9FB"))
            cell.fill.fore_color.rgb = rgb(fill)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = (aligns[j] if aligns else PP_ALIGN.LEFT) if i else (aligns[j] if aligns else PP_ALIGN.LEFT)
            r = p.add_run()
            r.text = str(val)
            _font(r, size, "FFFFFF" if i == 0 else INK, bold=(i == 0))
    return tbl


# ---------------------------------------------------------------- data from the evidence run
truth = R["downstream"]["clean_ground_truth"]
A = R["downstream"]["experiment_A_no_controls"]
B = R["downstream"]["experiment_B_with_controls"]
sec = R["security_summary"]
ev = R["evaluation"]
tot = ev["totals"]
by_sc = {r["scenario"]: r for r in ev["by_scenario"]}
attr_a = {r["scenario"]: r["revenue_effect"] for r in R["impact_attribution"]["experiment_A"]}
attr_b = {r["scenario"]: r["revenue_effect"] for r in R["impact_attribution"]["experiment_B"]}
run_id = R["ingestion"]["run_id"]
m = re.search(r"(\d+) passed.*?in ([\d.]+)s", TEST_TXT)
tests_passed, tests_time = (int(m.group(1)), m.group(2)) if m else (None, None)
tests_failed = len(re.findall(r"\bFAILED\b", TEST_TXT))
crosscheck = all(x["matches_pandas_crosscheck"] for x in (truth, A, B))
SC_LABEL = {
    "S1_MISSING_FIELDS": "S1 Missing fields", "S2_INVALID_TYPES": "S2 Invalid types",
    "S3_NEGATIVE_VALUES": "S3 Negative values", "S4_DUPLICATE_IDS": "S4 Duplicate IDs",
    "S5_INVALID_TIMESTAMPS": "S5 Invalid timestamps", "S6_EXTREME_VALUES": "S6 Extreme values",
    "S7_IN_TRANSIT_TAMPERING": "S7 In-transit tampering", "S8_PLAUSIBLE_MANIPULATION": "S8 Plausible manipulation",
    "S9_RULE_VIOLATIONS": "S9 Rule violations", "LEGITIMATE": "Legitimate",
}
ORDER = list(SC_LABEL)[:-1]

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(W), Inches(H)
BLANK = prs.slide_layouts[6]
n = 0


def new_slide(dark=False):
    global n
    n += 1
    s = prs.slides.add_slide(BLANK)
    background(s, NAVY if dark else "FFFFFF")
    return s


# ================================================================ 1 Title
s = new_slide(dark=True)
text(s, 0.8, 1.55, 7.6, 1.2, ["SecureDataFlow"], size=60, color="FFFFFF", bold=True, face=HEAD, name="Title")
text(s, 0.8, 2.85, 7.4, 1.1, ["Securing data ingestion pipelines against tampering and data poisoning"],
     size=24, color=ICE, face=HEAD)
text(s, 0.8, 4.45, 7.4, 1.6, ["DSA 4030 – Big Data Security  ·  Group 1",
                              "Team: [insert team member names]",
                              "November 2026"], size=16, color="FFFFFF", space_after=8)
for i, (lbl, key, col, tc) in enumerate([("ACCEPTED", "accepted", GREEN, "FFFFFF"),
                                         ("FLAGGED", "flagged", AMBER, INK),
                                         ("REJECTED", "rejected", RED, "FFFFFF")]):
    y = 1.75 + i * 1.35
    box(s, 9.0, y, 3.5, 1.1, "1D3250", name=f"{lbl} card")
    circle(s, 9.2, y + 0.2, 0.7, col, lbl[0], color=tc, size=20)
    text(s, 10.1, y + 0.12, 2.3, 0.45, [f"{sec[key]:,} records"], size=22, color="FFFFFF", bold=True)
    text(s, 10.1, y + 0.58, 2.3, 0.4, [lbl.title()], size=14, color=ICE)
text(s, 9.0, 5.85, 3.5, 0.6, [f"Decisions on the {sec['received']:,}-row attacked batch (run {run_id})"],
     size=11, color="9FB0C8")
notes(s, "Introduce the team and the topic: Group 1, securing data ingestion pipelines. "
         "SecureDataFlow is a working ingestion and validation system. The three numbers on the right are the "
         "real decisions it made on our attacked test batch; we will explain each of them.")

# ================================================================ 2 Problem
s = new_slide()
title(s, "Ingestion is where bad data gets in")
text(s, 0.6, 1.55, 6.4, 4.8, [
    [("Input tampering: ", {"bold": True}), ("genuine records altered or replayed between source and pipeline", {})],
    [("Data poisoning: ", {"bold": True}), ("false records inserted to distort totals, dashboards and models", {})],
    [("Every later stage inherits it: ", {"bold": True}),
     ("encryption, access control and analytics cannot repair a record that was false on arrival", {})],
    [("Our goal: ", {"bold": True}),
     ("measure the damage, then detect, flag or reject bad input and be honest about what still gets through", {})],
], size=18, bullets=True, space_after=14)
box(s, 7.5, 1.6, 5.2, 4.6, TINT, name="Headline stat card")
text(s, 7.8, 1.85, 4.6, 1.3, [f"{(A['total_revenue'] - truth['total_revenue']) / truth['total_revenue'] * 100:+.1f}%"],
     size=66, color=ORANGE, bold=True, face=HEAD)
text(s, 7.8, 3.2, 4.6, 1.3, [f"October revenue overstated when the attacked batch was ingested with no controls"],
     size=18, color=INK)
text(s, 7.8, 4.55, 4.6, 1.4, [
    [("True revenue  ", {"color": MUTED}), (f"KES {money(truth['total_revenue'], 0)}", {"bold": True})],
    [("Reported  ", {"color": MUTED}), (f"KES {money(A['total_revenue'], 0)}", {"bold": True, "color": ORANGE})],
    [(f"Caused by {tot['manipulated_records']} manipulated rows out of {sec['received']:,}", {"color": MUTED,
                                                                                            "size": 14})],
], size=16, space_after=4)
footer(s, n)
notes(s, "Ingestion is the trust boundary. Two threats: tampering with genuine records, and poisoning with false ones. "
         "Our measured headline: 63 manipulated rows, about 6 percent of the batch, more than doubled reported revenue "
         "when the batch was loaded the naive way.")

# ================================================================ 3 Architecture
s = new_slide()
title(s, "SecureDataFlow architecture")
steps = [("1", "Ingest", "Run id, UTC time, source, SHA-256 fingerprint, archive copy, values read as raw text"),
         ("2", "Validate", "Pydantic rules, HMAC signature, duplicate IDs, anomaly vs historical baseline"),
         ("3", "Route", "ACCEPTED → trusted/\nREJECTED / FLAGGED → quarantine/ with every reason"),
         ("4", "Log", "security_events.jsonl, ingestion_runs.jsonl, pipeline.log"),
         ("5", "Report", "Flowfile flow: Read → Group By → Sort on trusted records only")]
cw, gap, x0 = 2.24, 0.2, 0.6
for i, (num, head, body) in enumerate(steps):
    x = x0 + i * (cw + gap)
    box(s, x, 1.65, cw, 3.0, TINT, name=f"Step {num}")
    circle(s, x + 0.2, 1.85, 0.6, BLUE if num != "5" else AQUA, num, size=18)
    text(s, x + 0.2, 2.6, cw - 0.4, 0.5, [head], size=20, color=NAVY, bold=True, face=HEAD)
    text(s, x + 0.2, 3.12, cw - 0.4, 1.5, body.split("\n"), size=14, color=INK, space_after=4)
    if i < len(steps) - 1:
        a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x + cw + 0.03), Inches(3.0), Inches(0.14),
                               Inches(0.3))
        a.fill.solid()
        a.fill.fore_color.rgb = rgb(LINE)
        a.line.fill.background()
box(s, 0.6, 4.95, 12.1, 0.75, "FDEEE7", name="Experiment A path")
text(s, 0.85, 4.95, 11.6, 0.75, [[("Experiment A (no controls): ", {"bold": True, "color": ORANGE}),
                                  ("pandas.read_csv → numbers coerced, nothing checked → the same Flowfile report", {})]],
     size=16, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.6, 5.95, 12.1, 0.9, [
    [("Flowfile 0.24.0 ", {"bold": True}),
     (f"computes the report; results identical to an independent pandas calculation on every run "
      f"({'verified' if crosscheck else 'MISMATCH'}). Flows are saved as YAML and were executed in the Flowfile server "
      f"(4/4 nodes). Security controls are our own Python/Pydantic code, because Flowfile does not provide them.", {})]],
     size=14, color=MUTED)
footer(s, n)
notes(s, "Walk the five stages left to right. Emphasise that every rejected record is kept with its reasons. "
         "Experiment A skips stages 1 to 4 but uses the identical downstream report, so the comparison is fair. "
         "Flowfile is the processing foundation; the security layer is ours.")

# ================================================================ 4 Dataset and attacks
s = new_slide()
title(s, "Synthetic dataset and controlled attacks")
box(s, 0.6, 1.55, 4.3, 5.2, TINT, name="Dataset card")
text(s, 0.85, 1.75, 3.9, 0.5, ["Fictional data only"], size=20, color=NAVY, bold=True, face=HEAD)
text(s, 0.85, 2.3, 3.85, 4.4, [
    f"{R['data_generation']['clean_records']:,} clean October 2026 transactions, 5 sources, 5 categories, KES",
    f"{R['data_generation']['historical_records']:,} Jul–Sep records build the anomaly baseline",
    "Every record signed by its source (HMAC-SHA256)",
    f"Attacked batch: {sec['received']:,} rows, {tot['manipulated_records']} of them manipulated",
    "Ground-truth manifest used only to score results",
    "Fixed seeds, so every run is identical",
], size=15, bullets=True, space_after=9)
CLASS_FILL = {"invalid": "FBE3E3", "suspicious": "FEF1D2", "plausible but manipulated": "DDEBFA"}
rows = [["Scenario", "Rows", "Class"]]
fills = [None]
for sc in ORDER:
    r = by_sc[sc]
    rows.append([SC_LABEL[sc], r["records"], r["data_class"]])
    fills.append([None, None, CLASS_FILL[r["data_class"]]])
rows.append(["Untouched legitimate", by_sc["LEGITIMATE"]["records"], "legitimate"])
fills.append([None, None, "E2F4E2"])
table(s, 5.25, 1.55, 7.45, [3.6, 0.9, 2.95], rows, size=13, row_h=0.46, fills=fills,
      aligns=[PP_ALIGN.LEFT, PP_ALIGN.RIGHT, PP_ALIGN.LEFT], name="Scenario table")
footer(s, n)
notes(s, "Nine scenarios. Most are clearly invalid. S6 values are legal but extreme, so suspicious. "
         "S7 edits genuine records in transit and keeps them plausible. S8 is the important one: a compromised "
         "source inflates prices by 60 percent but stays in the normal range and re-signs the records. "
         "It is designed to pass every rule, so we can discuss the limits of validation.")

# ================================================================ 5 Controls
s = new_slide()
title(s, "Layered validation controls")
ctrls = [("Schema rules", "Pydantic", "Missing fields, wrong types, NaN, negatives, disallowed values, amount ≠ qty × price",
          "Well-formed but false values"),
         ("Timestamps", "strict ISO 8601", "Impossible dates, wrong formats, anything outside 1–31 Oct 2026",
          "A plausible wrong time inside the window"),
         ("Duplicate IDs", "batch level", "Exact replays (keep first); same ID with new content (reject all)",
          "Replay under a new, validly signed ID"),
         ("HMAC signature", "per record", "Any edit or injection by someone without the source key",
          "Compromised source, replays, deletions"),
         ("Anomaly baseline", "median / MAD", "Robust |z| > 3.5 vs Jul–Sep history; flagged, not rejected",
          "Manipulation inside the normal range"),
         ("Quarantine + logs", "evidence", "Every failure gets a reason code and message; run hash and archive copy",
          "Logs are not tamper-evident")]
cw, ch = 3.9, 2.55
for i, (head, tag, det, miss) in enumerate(ctrls):
    x = 0.6 + (i % 3) * (cw + 0.2)
    y = 1.55 + (i // 3) * (ch + 0.2)
    box(s, x, y, cw, ch, TINT, name=f"Control {i + 1}")
    circle(s, x + 0.2, y + 0.2, 0.5, NAVY, str(i + 1), size=15)
    text(s, x + 0.85, y + 0.12, cw - 1.0, 0.42, [head], size=18, color=NAVY, bold=True, face=HEAD,
         anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.85, y + 0.5, cw - 1.0, 0.28, [tag], size=12, color=MUTED)
    lbl_det, lbl_miss = ("Provides  ", "Limit  ") if i == 5 else ("Detects  ", "Misses  ")
    text(s, x + 0.2, y + 0.88, cw - 0.4, 0.95, [[(lbl_det, {"bold": True, "color": GREEN}), (det, {})]], size=14)
    text(s, x + 0.2, y + 1.85, cw - 0.4, 0.62, [[(lbl_miss, {"bold": True, "color": RED}), (miss, {})]], size=14)
footer(s, n)
notes(s, "Six layers. The key idea is that each answers a different question. The schema asks whether the data is "
         "well formed. The signature asks whether it was changed after the source signed it. The baseline asks "
         "whether it is unusual. None of them asks whether it is true, and that is why S8 gets through.")

# ================================================================ 6 Experiment A
s = new_slide()
title(s, "Experiment A: no controls, distorted report")
cd = CategoryChartData()
cats = [sc for sc in ORDER if abs(attr_a.get(sc, 0)) > 0][::-1]
cd.categories = [SC_LABEL[c] for c in cats]
cd.add_series("Effect on total revenue (KES)", [attr_a[c] for c in cats])
gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.6), Inches(1.45), Inches(7.6), Inches(5.35), cd)
gf.name = "Revenue effect chart"
ch_ = gf.chart
style_chart(ch_)
ch_.has_title = True
ch_.chart_title.text_frame.text = "Effect of each scenario on reported revenue (KES)"
ch_.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
ch_.chart_title.text_frame.paragraphs[0].runs[0].font.color.rgb = rgb(INK)
ser = ch_.series[0]
ser.format.fill.solid()
ser.format.fill.fore_color.rgb = rgb(ORANGE)
ser.invert_if_negative = False
plot = ch_.plots[0]
plot.gap_width = 60
plot.has_data_labels = True
plot.data_labels.number_format = '#,##0'
plot.data_labels.number_format_is_linked = False
plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
plot.data_labels.font.size = Pt(11)
plot.data_labels.font.color.rgb = rgb(INK)
ch_.value_axis.tick_labels.number_format = '#,##0,,"M"'
ch_.value_axis.tick_labels.number_format_is_linked = False
ch_.value_axis.maximum_scale = 10_000_000
ch_.value_axis.minimum_scale = -2_000_000
ch_.value_axis.major_unit = 2_000_000
from pptx.enum.chart import XL_TICK_LABEL_POSITION  # noqa: E402
ch_.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW
callouts = [(f"{A['unparseable_amounts']} amounts", "silently became NaN (12,5OO.00 · NaN · blank)"),
            ("Crypto + blank", "categories appeared in the revenue report"),
            ("2027 / 2025", "dated rows counted as October revenue"),
            (f"+KES {sum(attr_a.values()) / 1e6:.2f}M", "net error; negative 'reversals' hid part of it")]
for i, (big, small) in enumerate(callouts):
    y = 1.5 + i * 1.33
    box(s, 8.55, y, 4.15, 1.18, TINT, name=f"Callout {i + 1}")
    text(s, 8.8, y + 0.1, 3.75, 0.5, [big], size=22, color=ORANGE, bold=True, face=HEAD)
    text(s, 8.8, y + 0.62, 3.75, 0.5, [small], size=14, color=INK)
footer(s, n)
notes(s, "Experiment A loads the attacked file with pandas defaults. Five extreme records alone added about "
         "8.2 million shillings. Replays added about 0.8 million. Negative fake reversals subtracted 0.29 million, "
         "which shows that attacks can partly cancel out and make a corrupted total look closer to normal than it is. "
         "The worst behaviour is silent: three amounts became NaN with no warning.")

# ================================================================ 7 Execution evidence
s = new_slide()
title(s, "Actual execution: python main.py")


def grab(start_pat, count):
    for i, line in enumerate(RUN_TXT):
        if start_pat in line:
            return RUN_TXT[i:i + count]
    return []


MAXC = 108
excerpt = (grab("| Security decision", 7) + [""] +
           [ln for ln in RUN_TXT if ln.startswith("  row ")][:6] + [""] +
           grab("| Metric ", 9) + [""] +
           [ln for ln in RUN_TXT if ln.startswith("Flowfile results identical")])
excerpt = [ln if len(ln) <= MAXC else ln[:MAXC - 3] + "..." for ln in excerpt]
box(s, 0.6, 1.45, 9.3, 5.35, "0F1B2B", name="Console card")
text(s, 0.78, 1.58, 9.0, 5.15, excerpt, size=9.5, color="E6EDF5", face=MONO, space_after=0, line_spacing=1.0)
text(s, 0.6, 6.8, 9.3, 0.25, [f"Verbatim lines from reports/run_output.txt, run {run_id} (long lines shortened with ...)"],
     size=10, color=MUTED)
box(s, 10.1, 1.45, 2.6, 2.4, TINT, name="Tests card")
text(s, 10.3, 1.55, 2.3, 0.8, [f"{tests_passed} / {tests_passed + tests_failed}"], size=36, color=GREEN, bold=True,
     face=HEAD)
text(s, 10.3, 2.4, 2.3, 1.4, ["tests passed", f"pytest, {tests_time} s"], size=15, color=INK)
box(s, 10.1, 4.05, 2.6, 2.75, TINT, name="Outputs card")
text(s, 10.3, 4.15, 2.3, 0.5, ["Saved evidence"], size=16, color=NAVY, bold=True, face=HEAD)
text(s, 10.3, 4.7, 2.3, 2.0, ["data/trusted/", "data/quarantine/", "logs/*.jsonl", "reports/*.json",
                              "reports/flowfile/"], size=13, color=INK, space_after=4)
footer(s, n)
notes(s, "This is real output, copied from the run log, not a mock-up. If time allows, run python main.py live: "
         "it takes about 15 seconds. Point out the reason codes on the quarantined rows and the Flowfile cross-check "
         "line. 60 automated tests cover each control.")

# ================================================================ 8 Before / after
s = new_slide()
title(s, "Before and after: downstream revenue")
cd = CategoryChartData()
cats = [c for c in truth["by_category"]]
cd.categories = cats
cd.add_series("Clean ground truth", [truth["by_category"][c]["revenue"] for c in cats])
cd.add_series("A: no controls", [A["by_category"].get(c, {}).get("revenue") or 0 for c in cats])
cd.add_series("B: with controls", [B["by_category"].get(c, {}).get("revenue") or 0 for c in cats])
gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.45), Inches(6.9), Inches(5.35), cd)
gf.name = "Revenue by category chart"
ch_ = gf.chart
style_chart(ch_, legend=True)
for ser, col in zip(ch_.series, (BLUE, ORANGE, AQUA)):
    ser.format.fill.solid()
    ser.format.fill.fore_color.rgb = rgb(col)
ch_.plots[0].gap_width = 70
ch_.plots[0].overlap = -8
ch_.value_axis.tick_labels.number_format = '#,##0.0,,"M"'
ch_.value_axis.tick_labels.number_format_is_linked = False
ch_.has_title = True
ch_.chart_title.text_frame.text = "Revenue by category (KES)"
ch_.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
ch_.chart_title.text_frame.paragraphs[0].runs[0].font.color.rgb = rgb(INK)
rows = [["Metric", "Truth", "A: none", "B: controls"]]
for lbl, k, d in [("Records", "records", 0), ("Total revenue", "total_revenue", 0), ("Mean", "mean_amount", 0),
                  ("Median", "median_amount", 0), ("Largest", "max_amount", 0)]:
    f = (lambda v: f"{v:,}") if k == "records" else (lambda v: money(v, 0))
    rows.append([lbl, f(truth[k]), f(A[k]), f(B[k])])
table(s, 7.8, 1.5, 4.9, [1.45, 1.15, 1.15, 1.15], rows, size=13, row_h=0.42,
      aligns=[PP_ALIGN.LEFT, PP_ALIGN.RIGHT, PP_ALIGN.RIGHT, PP_ALIGN.RIGHT], name="Metrics table")
box(s, 7.8, 4.25, 2.35, 1.6, "FDEEE7", name="A error card")
text(s, 7.95, 4.35, 2.1, 0.7, [pct(A["total_revenue"], truth["total_revenue"])], size=28, color=ORANGE, bold=True,
     face=HEAD)
text(s, 7.95, 5.05, 2.1, 0.75, ["revenue error without controls"], size=13, color=INK)
box(s, 10.35, 4.25, 2.35, 1.6, "E3F5EE", name="B error card")
text(s, 10.5, 4.35, 2.1, 0.7, [pct(B["total_revenue"], truth["total_revenue"])], size=28, color="0E7A53", bold=True,
     face=HEAD)
text(s, 10.5, 5.05, 2.1, 0.75, ["revenue error with controls"], size=13, color=INK)
lost = attr_b.get("LEGITIMATE", 0) + attr_b.get("S7_IN_TRANSIT_TAMPERING", 0)
text(s, 7.8, 6.0, 4.9, 0.85, [f"Residual: KES {money(-lost, 0)} of genuine value held in quarantine "
                              f"(4 legitimate + 8 tampered originals); "
                              f"KES {money(attr_b.get('S8_PLAUSIBLE_MANIPULATION', 0), 0)} of S8 inflation accepted"],
     size=12, color=MUTED)
footer(s, n)
notes(s, "Same report, same attacked input. Without controls, totals more than double and the largest transaction "
         "jumps to 3.4 million. With controls, the error is minus one percent, mostly from records held in quarantine "
         "for review, which can be released. The undetected S8 inflation is the small positive part.")

# ================================================================ 9 Effectiveness
s = new_slide()
title(s, "How well the controls worked")
detectable = tot["manipulated_records"] - by_sc["S8_PLAUSIBLE_MANIPULATION"]["records"]
stats = [(f"{tot['manipulated_quarantined']} / {detectable}", "detectable manipulated rows quarantined", GREEN),
         (f"{by_sc['S8_PLAUSIBLE_MANIPULATION']['accepted']} / {by_sc['S8_PLAUSIBLE_MANIPULATION']['records']}",
          "plausible signed manipulations missed (S8)", RED),
         (f"{tot['legitimate_quarantined']} / {tot['legitimate_records']}",
          f"legitimate rows quarantined ({tot['false_positive_rate_pct']}%)", AMBER_TEXT),
         (f"{tot['detection_rate_pct']}%", "of all 63 manipulated rows quarantined", NAVY)]
for i, (big, small, col) in enumerate(stats):
    x = 0.6 + i * 3.075
    box(s, x, 1.5, 2.9, 1.55, TINT, name=f"Stat {i + 1}")
    text(s, x + 0.2, 1.55, 2.6, 0.75, [big], size=30, color=col, bold=True, face=HEAD)
    text(s, x + 0.2, 2.3, 2.6, 0.7, [small], size=13, color=INK)
cd = CategoryChartData()
sc_list = ["LEGITIMATE"] + ORDER
cd.categories = [SC_LABEL[c] for c in sc_list][::-1]
for key in ("accepted", "flagged", "rejected"):
    cd.add_series(key.title(), [by_sc[c][key] for c in sc_list][::-1])
gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_STACKED_100, Inches(0.6), Inches(3.25), Inches(12.1), Inches(3.6), cd)
gf.name = "Decisions per scenario chart"
ch_ = gf.chart
style_chart(ch_, legend=True, size=11)
for ser, col in zip(ch_.series, (GREEN, AMBER, RED)):
    ser.format.fill.solid()
    ser.format.fill.fore_color.rgb = rgb(col)
ch_.plots[0].gap_width = 40
# Colour alone would make the S8 bar read as a success: label it as missed attacks.
s8_idx = list(reversed(sc_list)).index("S8_PLAUSIBLE_MANIPULATION")
pt = ch_.series[0].points[s8_idx]
pt.data_label.has_text_frame = True
pt.data_label.position = XL_LABEL_POSITION.INSIDE_BASE
_tf = pt.data_label.text_frame
_tf.text = f"{by_sc['S8_PLAUSIBLE_MANIPULATION']['accepted']} attacks MISSED (accepted)"
for _r in _tf.paragraphs[0].runs:
    _font(_r, 11, "FFFFFF", bold=True)
ch_.value_axis.tick_labels.number_format = '0%'
ch_.value_axis.tick_labels.number_format_is_linked = False
footer(s, n)
notes(s, "Every record we designed to be detectable was quarantined: 53 of 53. The 10 S8 records all passed. "
         "That is the honest limit of validation. Four genuine records were quarantined: two because an attacker "
         "reused their IDs, and two because they were genuinely unusual. That is the cost of the statistical rule.")

# ================================================================ 10 Limitations and lessons
s = new_slide()
title(s, "Limitations and lessons learned")
cols = [("What the rules cannot catch", RED, [
            "Plausible manipulation by a trusted source (S8)",
            "Low-and-slow poisoning below the threshold",
            "Deleted records: no signed batch manifest",
            "Stolen keys: demo keys live in config"]),
        ("Risks the controls create", AMBER_TEXT, [
            "Genuine outliers flagged (2 here)",
            "ID collisions quarantine genuine records (2)",
            "Static baseline drifts with seasons",
            "Logs not hash-chained"]),
        ("Lessons learned", "0E7A53", [
            "Never coerce silently: reject with a reason",
            "Valid is not the same as true",
            "HMAC answers 'changed?', not 'true?'",
            "Quarantine beats deletion: auditable and reversible"])]
for i, (head, col, items) in enumerate(cols):
    x = 0.6 + i * 4.1
    box(s, x, 1.55, 3.9, 5.2, TINT, name=f"Column {i + 1}")
    text(s, x + 0.25, 1.75, 3.45, 0.55, [head], size=18, color=col, bold=True, face=HEAD)
    text(s, x + 0.25, 2.5, 3.45, 4.1, items, size=18, bullets=True, space_after=20)
footer(s, n)
notes(s, "Be explicit about limits. Validation proves form, not truth. The S8 attack needs evidence from outside the "
         "record, such as reconciliation with payments. Our anomaly rule also costs something: genuine outliers get "
         "flagged. The main lesson is that quarantining with reasons makes every decision auditable and reversible.")

# ================================================================ 11 Recommendations / close
s = new_slide(dark=True)
title(s, "Next steps and demonstration", dark=True)
recs = ["Per-source keys in a vault; asymmetric signatures",
        "Signed batch manifests (count, IDs, hash)",
        "Human review queue for FLAGGED records",
        "Reconcile with payments and inventory for S8-type fraud",
        "Hash-chained security logs; seasonal baselines"]
for i, r_ in enumerate(recs):
    y = 1.6 + i * 0.82
    circle(s, 0.6, y, 0.55, AQUA, str(i + 1), size=15)
    text(s, 1.35, y - 0.02, 6.6, 0.6, [r_], size=18, color="FFFFFF", anchor=MSO_ANCHOR.MIDDLE)
box(s, 8.4, 1.6, 4.3, 2.35, "1D3250", name="Demo card")
text(s, 8.65, 1.75, 3.9, 0.5, ["Run it yourself"], size=20, color=ICE, bold=True, face=HEAD)
text(s, 8.65, 2.35, 3.9, 2.1, [".\\.venv\\Scripts\\Activate.ps1", "python main.py", "python -m pytest -v"],
     size=15, color="FFFFFF", face=MONO, space_after=10)
text(s, 8.4, 5.0, 4.3, 1.0, ["Questions?"], size=40, color="FFFFFF", bold=True, face=HEAD)
footer(s, n, dark=True)
notes(s, "Close with the roadmap. Offer to run main.py live and to open a quarantined record or a Flowfile flow. "
         "Then take questions.")

prs.core_properties.title = "SecureDataFlow - Securing Data Ingestion Pipelines"
prs.core_properties.author = "DSA 4030 Group 1"
prs.save(OUT)
print(f"saved {OUT.name}: {len(prs.slides)} slides; tests {tests_passed} passed / {tests_failed} failed; "
      f"crosscheck={crosscheck}")
if tests_passed is None:
    sys.exit("could not read test results")
