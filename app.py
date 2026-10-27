from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import math
import re
import time
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import streamlit as st

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage,
        PageBreak
    )
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

try:
    import xlsxwriter  # noqa: F401
    XLSX_AVAILABLE = True
except Exception:
    XLSX_AVAILABLE = False

st.set_page_config(page_title="Hispanic Heritage Historical Data Explorer", page_icon="📈", layout="wide")

COUNTRIES = {
    "Mexico": "MEX", "Brazil": "BRA", "Argentina": "ARG", "Colombia": "COL",
    "Chile": "CHL", "Peru": "PER", "Venezuela": "VEN", "Ecuador": "ECU", "Uruguay": "URY"
}
INDICATORS = {
    "Life expectancy at birth": {
        "code": "SP.DYN.LE00.IN", "units": "years", "definition": "Life expectancy at birth, total population."
    },
    "Unemployment rate": {
        "code": "SL.UEM.TOTL.NE.ZS", "units": "% of total labor force",
        "definition": "Unemployment, total (% of total labor force), national estimate."
    },
    "GDP per capita": {
        "code": "NY.GDP.PCAP.CD", "units": "current US$ per person",
        "definition": "Gross domestic product divided by midyear population, in current US dollars."
    },
    "Crude birth rate": {
        "code": "SP.DYN.CBRT.IN", "units": "births per 1,000 people",
        "definition": "Annual number of births per 1,000 people."
    },
    "Net migration": {
        "code": "SM.POP.NETM", "units": "people",
        "definition": "Net migration: immigration minus emigration for the source period."
    },
    "Intentional homicide rate": {
        "code": "VC.IHR.PSRC.P5", "units": "intentional homicides per 100,000 people",
        "definition": "Intentional homicides per 100,000 people."
    },
    "Consumer price inflation": {
        "code": "FP.CPI.TOTL.ZG", "units": "% annual change",
        "definition": "Annual percentage change in the consumer price index."
    },
    "Central government debt": {
        "code": "GC.DOD.TOTL.GD.ZS", "units": "% of GDP",
        "definition": "Central government debt as a percentage of GDP; not all public-sector debt."
    },
    "Total reserves, including gold": {
        "code": "FI.RES.TOTL.CD", "units": "current US$",
        "definition": "Total reserves including gold, in current US dollars."
    },
    "External balance: goods/services": {
        "code": "NE.RSB.GNFS.ZS", "units": "% of GDP",
        "definition": "External balance on goods and services as a percentage of GDP; not the current account."
    }
}
WB_API = "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
WB_INDICATOR_URL = "https://data.worldbank.org/indicator/{code}"
COUNTRY_CODES = set(COUNTRIES.values())

st.title("📈 Hispanic Heritage Historical Data Explorer")
st.caption("Historical indicators, polynomial models, and cultural context — use estimates thoughtfully.")
st.info("Brazil is included as a Latin American comparison; it is not a Spanish-speaking Hispanic country.")

def api_fetch(country_code: str, indicator_code: str, start_year: int, end_year: int) -> tuple[pd.DataFrame, str]:
    """Fetch genuine World Bank API observations. Never fabricate replacement data."""
    url = WB_API.format(country=country_code.lower(), indicator=indicator_code)
    params = {"format": "json", "date": f"{start_year}:{end_year}", "per_page": 2000}
    try:
        response = requests.get(url, params=params, timeout=(5, 20), headers={"User-Agent": "Hispanic-Heritage-Data-Explorer/1.0"})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
            return pd.DataFrame(columns=["year", "value"]), "World Bank returned no usable observation series."
        rows = []
        for item in payload[1]:
            if not isinstance(item, dict):
                continue
            year = item.get("date")
            value = item.get("value")
            if year is None or value is None:
                continue
            try:
                rows.append({"year": int(year), "value": float(value)})
            except (TypeError, ValueError):
                continue
        df = pd.DataFrame(rows, columns=["year", "value"]).dropna()
        if df.empty:
            return df, "No non-null observations were returned for this series and period."
        return df.sort_values("year").drop_duplicates("year"), ""
    except requests.Timeout:
        return pd.DataFrame(columns=["year", "value"]), "The World Bank request timed out. Retry later or check the API."
    except requests.RequestException as exc:
        return pd.DataFrame(columns=["year", "value"]), f"World Bank request failed: {exc}"
    except (ValueError, json.JSONDecodeError):
        return pd.DataFrame(columns=["year", "value"]), "The World Bank response was not valid JSON."

@st.cache_data(ttl=3600, show_spinner=False)
def cached_fetch(country_code: str, indicator_code: str, start_year: int, end_year: int):
    df, message = api_fetch(country_code, indicator_code, start_year, end_year)
    return df, message

def plausible_value(indicator_name: str, value: float) -> bool:
    if not math.isfinite(value):
        return False
    if indicator_name in ("Life expectancy at birth",):
        return 0 <= value <= 125
    if indicator_name == "Unemployment rate":
        return 0 <= value <= 100
    if indicator_name == "Crude birth rate":
        return 0 <= value <= 100
    if indicator_name == "Intentional homicide rate":
        return value >= 0
    if indicator_name == "Consumer price inflation":
        return value >= -100
    return True

def clean_working_data(df: pd.DataFrame, indicator_name: str) -> tuple[pd.DataFrame, list[str]]:
    issues = []
    if df is None or df.empty:
        return pd.DataFrame(columns=["year", "value"]), ["There are no observations to fit."]
    working = df.copy()
    if "year" not in working or "value" not in working:
        return pd.DataFrame(columns=["year", "value"]), ["Data table must have year and value columns."]
    working["year_num"] = pd.to_numeric(working["year"], errors="coerce")
    working["value_num"] = pd.to_numeric(working["value"], errors="coerce")
    bad_year = working["year_num"].isna() | (working["year_num"] % 1 != 0)
    bad_value = working["value_num"].isna() | ~np.isfinite(working["value_num"])
    if bad_year.any():
        issues.append(f"Rejected {int(bad_year.sum())} row(s) with missing/non-integer years.")
    if bad_value.any():
        issues.append(f"Rejected {int(bad_value.sum())} row(s) with missing/non-numeric values.")
    working = working.loc[~bad_year & ~bad_value].copy()
    working["year"] = working["year_num"].astype(int)
    working["value"] = working["value_num"].astype(float)
    dup = working["year"].duplicated(keep=False)
    if dup.any():
        issues.append(f"Rejected all rows for duplicate year(s): {sorted(working.loc[dup, 'year'].unique().tolist())}.")
        working = working.loc[~dup]
    bad_range = ~working["value"].apply(lambda v: plausible_value(indicator_name, float(v)))
    if bad_range.any():
        issues.append(f"Rejected {int(bad_range.sum())} value(s) outside basic plausibility checks for {indicator_name}.")
        working = working.loc[~bad_range]
    year_bad = ~working["year"].between(1900, 2100)
    if year_bad.any():
        issues.append(f"Rejected {int(year_bad.sum())} year(s) outside 1900–2100.")
        working = working.loc[~year_bad]
    return working[["year", "value"]].sort_values("year").reset_index(drop=True), issues

def fit_polynomial(df: pd.DataFrame, degree: int):
    if len(df) < degree + 1 or df["year"].nunique() < degree + 1:
        raise ValueError(f"Degree {degree} needs at least {degree + 1} distinct valid years; current count is {df['year'].nunique()}.")
    base_year = int(df["year"].min())
    t = df["year"].to_numpy(dtype=float) - base_year
    y = df["value"].to_numpy(dtype=float)
    coeffs = np.polyfit(t, y, degree)
    poly = np.poly1d(coeffs)
    predicted = poly(t)
    residuals = y - predicted
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    ss_res = float(np.sum(residuals ** 2))
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
    mae = float(np.mean(np.abs(residuals)))
    return {"base_year": base_year, "coeffs": coeffs, "poly": poly, "predicted": predicted,
            "residuals": residuals, "r2": r2, "mae": mae, "mean": float(np.mean(y)),
            "min_year": int(df["year"].min()), "max_year": int(df["year"].max()),
            "n": len(df), "degree": degree}

def estimate(model: dict, year: int) -> float:
    return float(model["poly"](int(year) - model["base_year"]))

def equation_text(model: dict) -> str:
    terms = []
    degree = model["degree"]
    for i, c in enumerate(model["coeffs"]):
        power = degree - i
        terms.append(f"({c:.6g})·t^{power}" if power > 1 else (f"({c:.6g})·t" if power == 1 else f"({c:.6g})"))
    return "y = " + " + ".join(terms) + f", where t = year − {model['base_year']}"

def calculate_holdout(df: pd.DataFrame, degree: int):
    """Chronological holdout: reserve the latest 20% (at least 3 rows) where feasible."""
    n = len(df)
    holdout_n = max(3, int(math.ceil(n * 0.2)))
    if n - holdout_n < degree + 1 or holdout_n < 3:
        return None
    train = df.iloc[:-holdout_n].copy()
    test = df.iloc[-holdout_n:].copy()
    try:
        model = fit_polynomial(train, degree)
    except Exception:
        return None
    preds = np.array([estimate(model, int(y)) for y in test["year"]])
    return {"n": len(test), "mae": float(np.mean(np.abs(test["value"].to_numpy() - preds))),
            "years": test["year"].astype(int).tolist(), "actual": test["value"].tolist(), "predicted": preds.tolist()}

def make_chart(df: pd.DataFrame, model: dict, country: str, indicator: str, sample_step: int, horizon: int,
               comparison: dict[str, pd.DataFrame] | None = None, point_years: list[int] | None = None):
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.scatter(df["year"], df["value"], label=f"{country}: observed", s=25)
    historical_x = np.linspace(model["min_year"], model["max_year"], max(200, model["n"] * 4))
    historical_y = [estimate(model, int(round(x))) for x in historical_x]
    ax.plot(historical_x, historical_y, label=f"{country}: degree {model['degree']} fit")
    if horizon > 0:
        future_x = np.linspace(model["max_year"], model["max_year"] + horizon, max(30, horizon * 8))
        ax.plot(future_x, [estimate(model, int(round(x))) for x in future_x], linestyle="--", label="Extrapolated segment")
    sampled_years = list(range(model["min_year"], model["max_year"] + 1, sample_step))
    ax.scatter(sampled_years, [estimate(model, y) for y in sampled_years], marker="x", s=28, label=f"Model markers every {sample_step} year(s)")
    if comparison:
        for cname, cdf in comparison.items():
            if not cdf.empty:
                ax.plot(cdf["year"], cdf["value"], marker=".", linewidth=1.4, label=f"{cname}: observed")
    if point_years:
        inside, outside = [], []
        for y in point_years:
            (inside if model["min_year"] <= y <= model["max_year"] else outside).append(y)
        if inside:
            ax.scatter(inside, [estimate(model, y) for y in inside], marker="D", s=55, label="Requested fitted-range estimate")
        if outside:
            ax.scatter(outside, [estimate(model, y) for y in outside], marker="^", s=65, label="Requested extrapolation")
    ax.axvline(model["max_year"], linestyle=":", linewidth=1, label="Historical-range boundary")
    ax.set_title(f"{country} — {indicator}")
    ax.set_xlabel("Year")
    ax.set_ylabel(INDICATORS[indicator]["units"])
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    return fig

def make_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

def make_xlsx(summary: dict, df: pd.DataFrame, results: pd.DataFrame | None) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame([summary]).to_excel(writer, sheet_name="Summary", index=False)
        df.to_excel(writer, sheet_name="Working Data", index=False)
        if results is not None and not results.empty:
            results.to_excel(writer, sheet_name="Calculated Years", index=False)
        workbook = writer.book
        header = workbook.add_format({"bold": True, "text_wrap": True, "valign": "top", "border": 1})
        for sheet_name, frame in [("Summary", pd.DataFrame([summary])), ("Working Data", df)]:
            ws = writer.sheets[sheet_name]
            ws.freeze_panes(1, 0)
            ws.set_row(0, 32, header)
            for i, col in enumerate(frame.columns):
                ws.set_column(i, i, min(max(len(str(col)) + 3, 14), 42))
        if results is not None and not results.empty:
            ws = writer.sheets["Calculated Years"]
            ws.freeze_panes(1, 0)
            ws.set_row(0, 32, header)
            ws.set_column(0, max(0, len(results.columns)-1), 20)
    return output.getvalue()

def make_pdf(summary: dict, df: pd.DataFrame, results: pd.DataFrame | None, fig) -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab is not installed.")
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(letter), rightMargin=0.45*inch, leftMargin=0.45*inch,
                            topMargin=0.45*inch, bottomMargin=0.45*inch)
    styles = getSampleStyleSheet()
    story = [Paragraph("Hispanic Heritage Historical Data Explorer", styles["Title"]),
             Paragraph("Data and model report — estimates are not guaranteed forecasts.", styles["Normal"]), Spacer(1, 10)]
    for key, value in summary.items():
        story.append(Paragraph(f"<b>{key}:</b> {str(value).replace('&', '&amp;')}", styles["BodyText"]))
    story.append(Spacer(1, 10))
    image_buf = BytesIO()
    fig.savefig(image_buf, format="png", dpi=130, bbox_inches="tight")
    image_buf.seek(0)
    story.append(RLImage(image_buf, width=9.4*inch, height=4.8*inch))
    story.append(Paragraph("Working data preview (first 20 rows)", styles["Heading2"]))
    data_rows = [["Year", "Value"]] + [[str(int(r.year)), f"{r.value:.6g}"] for r in df.head(20).itertuples()]
    table = Table(data_rows, repeatRows=1, colWidths=[1.2*inch, 1.8*inch])
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")),
                               ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                               ("GRID", (0,0), (-1,-1), 0.4, colors.grey),
                               ("FONTSIZE", (0,0), (-1,-1), 8), ("ALIGN", (0,0), (-1,-1), "LEFT")]))
    story.extend([table, Spacer(1, 8), Paragraph("Findings and limitations", styles["Heading2"]),
                  Paragraph("This polynomial summarizes the selected observations. In-sample R² and MAE describe fit to the data used for fitting; they do not establish forecasting accuracy. National unemployment estimates may use methods that differ by country. Historical context and source definitions must be considered before interpreting comparisons. Statistically validated prediction intervals are not provided.", styles["BodyText"])])
    if results is not None and not results.empty:
        story.append(Paragraph("Calculated-year results", styles["Heading2"]))
        rr = [["Year", "Estimate", "Classification"]] + [[str(int(r.year)), f"{r.estimate:.6g}", str(r.classification)] for r in results.itertuples()]
        rt = Table(rr, repeatRows=1)
        rt.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")),
                                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                                ("GRID", (0,0), (-1,-1), 0.4, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 8)]))
        story.append(rt)
    doc.build(story)
    return output.getvalue()

# Sidebar: all controls affect a corresponding output.
with st.sidebar:
    st.header("Explore the data")
    country = st.selectbox("Main country", list(COUNTRIES.keys()), index=list(COUNTRIES.keys()).index("Colombia"))
    indicator = st.selectbox("Indicator", list(INDICATORS.keys()), index=list(INDICATORS.keys()).index("Unemployment rate"))
    degree = st.slider("Polynomial degree", 3, 8, 3)
    sample_step = st.slider("Model marker sampling increment (years)", 1, 10, 1)
    horizon = st.slider("Forward display horizon (years)", 0, 50, 5)
    comparison_countries = st.multiselect("Compare same indicator", [c for c in COUNTRIES if c != country], default=["Chile"] if country != "Chile" else ["Colombia"])
    printer_mode = st.toggle("Printer-friendly report view", value=False)

current_year = datetime.now().year
start_year, end_year = current_year - 70, current_year - 1
meta = INDICATORS[indicator]
st.caption(f"Indicator code: `{meta['code']}` · Units: {meta['units']} · Target search window: {start_year}–{end_year} (actual coverage may be shorter).")
st.markdown(f"**Definition:** {meta['definition']}  \n**Source:** [World Bank indicator metadata]({WB_INDICATOR_URL.format(code=meta['code'])}) · **Retrieved:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

with st.spinner(f"Retrieving official World Bank data for {country}…"):
    source_df, source_message = cached_fetch(COUNTRIES[country], meta["code"], start_year, end_year)

if source_message:
    st.warning(source_message)
if source_df.empty:
    st.error("No authentic observations are available to fit this selection. Choose another country/indicator or retry later. No substitute values are generated.")
    st.stop()

source_df = source_df[["year", "value"]].sort_values("year").reset_index(drop=True)
if "selected_country" not in st.session_state or st.session_state.selected_country != country or st.session_state.get("selected_indicator") != indicator:
    st.session_state.selected_country = country
    st.session_state.selected_indicator = indicator
    st.session_state.working_data = source_df.copy()
    st.session_state.calculated_results = pd.DataFrame()
    st.session_state.last_model_signature = None

st.subheader("Historical observations")
c1, c2, c3 = st.columns(3)
c1.metric("Observations", len(source_df))
c2.metric("First observed year", int(source_df.year.min()))
c3.metric("Last observed year", int(source_df.year.max()))
st.caption("Original source observations are kept separately from the editable working copy. Editing creates a user-modified scenario.")
edited = st.data_editor(st.session_state.working_data, num_rows="dynamic", use_container_width=True, key="data_editor",
                        column_config={"year": st.column_config.NumberColumn("Year", step=1, format="%d"),
                                       "value": st.column_config.NumberColumn(f"Value ({meta['units']})", format="%.6g")})
b1, b2 = st.columns([1, 4])
with b1:
    if st.button("Reset to source"):
        st.session_state.working_data = source_df.copy()
        st.session_state.calculated_results = pd.DataFrame()
        st.rerun()
with b2:
    st.caption("Reset restores the retrieved source series; rejected rows are reported below.")

working_df, validation_issues = clean_working_data(edited, indicator)
edited_flag = not (working_df.equals(source_df.reset_index(drop=True)))
if validation_issues:
    for issue in validation_issues:
        st.warning(issue)
if edited_flag:
    st.warning("USER-MODIFIED SCENARIO: calculations and exports use the validated working copy, not the untouched source observations.")

if len(working_df) < degree + 1:
    st.error(f"Not enough valid distinct years for degree {degree}. Need at least {degree+1}; current count is {len(working_df)}.")
    st.stop()

try:
    model = fit_polynomial(working_df, degree)
except (ValueError, np.linalg.LinAlgError) as exc:
    st.error(f"Could not fit the selected polynomial: {exc}")
    st.stop()

signature = (country, indicator, degree, tuple(working_df["year"]), tuple(np.round(working_df["value"], 10)))
if st.session_state.get("last_model_signature") != signature:
    st.session_state.calculated_results = pd.DataFrame()
    st.session_state.last_model_signature = signature

st.subheader("Polynomial model")
if printer_mode:
    st.markdown("---")
    st.markdown(f"## Printable summary — {country}: {indicator}")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Degree", model["degree"])
m2.metric("In-sample R²", f"{model['r2']:.5f}" if np.isfinite(model["r2"]) else "undefined")
m3.metric("In-sample MAE", f"{model['mae']:.5g} {meta['units']}")
m4.metric("Mean", f"{model['mean']:.5g} {meta['units']}")
st.write(f"**Equation:** `{equation_text(model)}`")
st.write(f"**Base year:** {model['base_year']} · **Fitted domain:** {model['min_year']}–{model['max_year']} · **n:** {model['n']}")
st.caption("R² and MAE are in-sample fit measures. They are not proof of future forecasting accuracy. No validated 95% prediction interval is provided.")

with st.expander("Calculus pathway: first and second derivatives"):
    deriv1 = np.polyder(model["poly"], 1)
    deriv2 = np.polyder(model["poly"], 2)
    st.write(f"**First derivative:** `dy/dt = {np.array2string(deriv1.coefficients, precision=5)}` (indicator units per year)")
    st.write(f"**Second derivative:** `d²y/dt² = {np.array2string(deriv2.coefficients, precision=5)}` (indicator units per year²)")
    critical_t = np.roots(deriv1) if len(deriv1.coefficients) > 1 else np.array([])
    real_critical = sorted([float(x.real) for x in critical_t if abs(x.imag) < 1e-7 and model["min_year"] <= x.real + model["base_year"] <= model["max_year"]])
    if real_critical:
        st.write("Critical points inside the historical interval:")
        for tval in real_critical:
            year = model["base_year"] + tval
            second = float(deriv2(tval)) if len(deriv2.coefficients) else 0.0
            kind = "local minimum" if second > 0 else ("local maximum" if second < 0 else "classification inconclusive from second derivative")
            st.write(f"- Year ≈ {year:.3f}, fitted value ≈ {model['poly'](tval):.5g}; {kind}.")
    else:
        st.write("No real derivative roots were found inside the historical interval.")
    inflection_t = np.roots(deriv2) if len(deriv2.coefficients) > 1 else np.array([])
    inflections = sorted([float(x.real) for x in inflection_t if abs(x.imag) < 1e-7 and model["min_year"] <= x.real + model["base_year"] <= model["max_year"]])
    verified = []
    for tval in inflections:
        eps = 1e-3
        left, right = float(deriv2(tval-eps)), float(deriv2(tval+eps))
        if left * right < 0:
            verified.append(tval)
    st.write("Verified inflection candidates (second derivative changes sign): " + (", ".join(f"{model['base_year']+x:.3f}" for x in verified) if verified else "none inside the observed interval"))
    st.caption("These are properties of the fitted polynomial, not direct measurements of the economy. Endpoint extrema must also be checked when reporting interval extrema.")

holdout = calculate_holdout(working_df, degree)
if holdout:
    st.write(f"**Chronological holdout MAE:** {holdout['mae']:.5g} {meta['units']} across {holdout['n']} latest held-out observations (years {min(holdout['years'])}–{max(holdout['years'])}).")
else:
    st.write("**Chronological holdout:** not reported because the available observations are insufficient for the selected degree and a holdout of at least three later observations.")

comparison_data = {}
comparison_coverage = []
for cname in comparison_countries:
    cdf, cmessage = cached_fetch(COUNTRIES[cname], meta["code"], start_year, end_year)
    if cmessage:
        st.warning(f"{cname}: {cmessage}")
    if not cdf.empty:
        comparison_data[cname] = cdf
        comparison_coverage.append(f"{cname}: {int(cdf.year.min())}–{int(cdf.year.max())} ({len(cdf)} observations)")
if comparison_coverage:
    st.caption("Comparison coverage: " + " · ".join(comparison_coverage))
elif comparison_countries:
    st.warning("No comparison-country series could be retrieved; no substitute series was used.")

# Single estimate
st.subheader("Single-year estimate")
with st.form("single_estimate"):
    single_year = st.number_input("Year (1950–2100)", min_value=1950, max_value=2100, value=min(max(model["max_year"] + 1, 1950), 2100), step=1)
    single_submit = st.form_submit_button("Calculate Value")
if single_submit:
    y = int(single_year)
    val = estimate(model, y)
    classification = "within fitted range" if model["min_year"] <= y <= model["max_year"] else "extrapolation outside fitted range"
    observed = working_df.loc[working_df.year == y, "value"]
    st.session_state.single_result = {"year": y, "estimate": val, "classification": classification,
                                      "observed": float(observed.iloc[0]) if not observed.empty else None}
if st.session_state.get("single_result"):
    sr = st.session_state.single_result
    if sr["classification"].startswith("extrapolation"):
        st.warning("This estimate is outside the fitted historical range. Polynomial extrapolations can become implausible.")
    st.metric(f"Model estimate for {sr['year']}", f"{sr['estimate']:.6g} {meta['units']}")
    st.write(f"**Classification:** {sr['classification']}.")
    if sr["observed"] is not None:
        st.write(f"**Observed value for this year:** {sr['observed']:.6g} {meta['units']} (shown separately from the fitted value).")

# Batch estimate
st.subheader("Batch estimates")
mode = st.radio("Batch input type", ["Year range", "Custom years"], horizontal=True)
years = []
invalid_entries = []
if mode == "Year range":
    c1, c2, c3 = st.columns(3)
    with c1: range_start = st.number_input("Start year", 1950, 2100, max(1950, model["min_year"]), key="range_start")
    with c2: range_end = st.number_input("End year", 1950, 2100, min(2100, model["max_year"] + 5), key="range_end")
    with c3: range_step = st.number_input("Step (1–10)", 1, 10, 1, key="range_step")
    if range_end <= range_start:
        st.warning("End year must be greater than start year.")
    else:
        years = list(range(int(range_start), int(range_end) + 1, int(range_step)))
else:
    custom_text = st.text_input("Comma-separated years", value=f"{model['min_year']},{model['max_year']},{min(2100, model['max_year']+5)}")
    seen = set()
    for token in custom_text.split(","):
        token = token.strip()
        if not token:
            continue
        if not re.fullmatch(r"[+-]?\d+", token):
            invalid_entries.append(f"{token!r} is not an integer")
            continue
        y = int(token)
        if not 1950 <= y <= 2100:
            invalid_entries.append(f"{y} is outside 1950–2100")
            continue
        if y in seen:
            invalid_entries.append(f"{y} is a duplicate (kept once)")
            continue
        seen.add(y)
        years.append(y)
if invalid_entries:
    st.warning("Input feedback: " + "; ".join(invalid_entries))
st.write("**Final valid year list:** " + (", ".join(map(str, years)) if years else "No valid years"))
if st.button("Calculate Batch", disabled=not years):
    rows = []
    for y in years:
        val = estimate(model, y)
        classification = "fitted value at observed year" if y in set(working_df.year) else ("within fitted range" if model["min_year"] <= y <= model["max_year"] else "extrapolation")
        rows.append({"year": y, "estimate": val, "units": meta["units"], "classification": classification})
    st.session_state.calculated_results = pd.DataFrame(rows)
if isinstance(st.session_state.get("calculated_results"), pd.DataFrame) and not st.session_state.calculated_results.empty:
    result_df = st.session_state.calculated_results
    st.dataframe(result_df, use_container_width=True)
    st.caption("Batch values use the same model transformation as single-year estimates. Estimates at observed years are fitted values, not the raw observation.")
else:
    result_df = pd.DataFrame()

# Average rates of change and residuals
st.subheader("Rates of change and residuals")
if len(working_df) >= 2:
    first = working_df.iloc[0]
    mid = working_df.iloc[len(working_df)//2]
    last = working_df.iloc[-1]
    rate1 = (float(mid.value) - float(first.value)) / (int(mid.year) - int(first.year))
    rate2 = (float(last.value) - float(mid.value)) / (int(last.year) - int(mid.year))
    st.write(f"- Observed average rate, {int(first.year)}–{int(mid.year)}: **{rate1:.5g} {meta['units']} per year**.")
    st.write(f"- Observed average rate, {int(mid.year)}–{int(last.year)}: **{rate2:.5g} {meta['units']} per year**.")
    if indicator == "Unemployment rate":
        st.caption("For unemployment, these are percentage points per year, not relative percent change.")
residual_df = pd.DataFrame({"year": working_df["year"], "observed": working_df["value"],
                            "fitted": model["predicted"], "residual": model["residuals"]})
with st.expander("Inspect residuals"):
    st.dataframe(residual_df, use_container_width=True)

st.subheader("Visualization")
point_years = []
if st.session_state.get("single_result"):
    point_years.append(st.session_state.single_result["year"])
if not result_df.empty:
    point_years.extend(result_df["year"].astype(int).tolist())
fig = make_chart(working_df, model, country, indicator, sample_step, horizon, comparison_data, point_years)
st.pyplot(fig, use_container_width=True)
if printer_mode:
    st.markdown("### Printer view")
    st.write(f"{country} · {indicator} · {meta['units']} · data coverage {model['min_year']}–{model['max_year']} · degree {degree}")
    st.write(f"Equation: {equation_text(model)}")
    st.write(f"R² = {model['r2']:.5g}; MAE = {model['mae']:.5g}. Interpret as in-sample fit metrics.")
    st.caption("Print from your browser using Ctrl+P / Cmd+P. The simplified summary above is intended for a readable printout.")

# Exports
st.subheader("Download reports")
summary = {
    "Country": country,
    "Indicator": indicator,
    "Indicator code": meta["code"],
    "Units": meta["units"],
    "Definition": meta["definition"],
    "Source": WB_INDICATOR_URL.format(code=meta["code"]),
    "Retrieval timestamp UTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "Source coverage": f"{int(source_df.year.min())}–{int(source_df.year.max())}",
    "Working coverage": f"{model['min_year']}–{model['max_year']}",
    "Observation count": model["n"],
    "Data status": "USER-MODIFIED SCENARIO" if edited_flag else "Source data (not edited)",
    "Polynomial degree": degree,
    "Base year": model["base_year"],
    "Equation": equation_text(model),
    "In-sample R-squared": model["r2"],
    "In-sample MAE": model["mae"],
    "Mean": model["mean"],
    "Holdout MAE": holdout["mae"] if holdout else "Not available: insufficient data",
    "Uncertainty": "No statistically validated prediction intervals provided."
}
csv_bytes = make_csv(working_df.assign(data_status="USER-MODIFIED SCENARIO" if edited_flag else "Source data (not edited)"))
d1, d2, d3 = st.columns(3)
with d1:
    st.download_button("Download CSV data", data=csv_bytes, file_name=f"{country.lower()}_{meta['code'].lower()}_working_data.csv", mime="text/csv")
with d2:
    if XLSX_AVAILABLE:
        try:
            xlsx_bytes = make_xlsx(summary, working_df, result_df)
            st.download_button("Download Excel workbook", data=xlsx_bytes, file_name=f"{country.lower()}_historical_data_report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as exc:
            st.error(f"Excel export unavailable: {exc}")
    else:
        st.warning("Excel export unavailable: install xlsxwriter.")
with d3:
    if REPORTLAB_AVAILABLE:
        try:
            pdf_bytes = make_pdf(summary, working_df, result_df, fig)
            st.download_button("Download PDF report", data=pdf_bytes, file_name=f"{country.lower()}_historical_data_report.pdf", mime="application/pdf")
        except Exception as exc:
            st.error(f"PDF export unavailable: {exc}")
    else:
        st.warning("PDF export unavailable: install reportlab.")

st.subheader("Research context and interpretation")
st.markdown("""
- This project compares the national-estimate unemployment series for Colombia and Chile when selected. These data are indicators, not complete descriptions of either country or its people.
- Compare the series only after checking source definitions, coverage, and methodological differences. A gap between two plotted lines does not by itself identify a cause.
- Connect the data to a specific, cited historical, policy, labor-market, or community experience in your research brief. Avoid treating an indicator as a measure of a country's cultural worth.
- A polynomial is a descriptive mathematical model. Distant extrapolations can become unrealistic, and the model should not be presented as a dependable forecast without separate validation.
""")
st.markdown(f"**Source links:** [World Bank API documentation](https://datahelpdesk.worldbank.org/knowledgebase/articles/898581-api-basic-call-structures) · [Indicator page]({WB_INDICATOR_URL.format(code=meta['code'])}) · [Streamlit deployment guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)")
st.caption("Research/source information last assembled for this project on 2026-10-27. Check official metadata and live API output before presenting.")
