import math
import os
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="CAGE Distance Explorer", page_icon="🌍", layout="wide")
DIMS = ["Cultural", "Administrative", "Geographic", "Economic"]
WEIGHTS = {
    "General / unspecified": [25, 25, 25, 25],
    "Video game retail": [30, 20, 15, 35],
    "Film, TV & media": [40, 20, 15, 25],
    "Cement & construction materials": [10, 20, 45, 25],
    "Software / SaaS": [25, 30, 10, 35],
    "Food & beverages": [35, 25, 20, 20],
    "Consumer electronics": [20, 25, 25, 30],
    "Financial services": [20, 40, 10, 30],
}
REASONS = {
    "Cultural": "Language, customer communication and localization change product-market fit.",
    "Administrative": "Institutional quality affects regulatory compliance and operating predictability; trade and sanctions need separate verification.",
    "Geographic": "Distance, shipping infrastructure and supply chains affect service and distribution.",
    "Economic": "Customer purchasing power and affordability influence price and market size.",
}


def req_json(url):
    r = requests.get(url, timeout=18, headers={"User-Agent": "CAGE-Country-Research/1.0"})
    r.raise_for_status()
    return r.json()


COUNTRY_DATA_URL = "https://raw.githubusercontent.com/mledoze/countries/master/countries.json"
COUNTRY_DATA_PAGE = "https://github.com/mledoze/countries"


@st.cache_data(ttl=86400, show_spinner=False)
def all_countries():
    # The legacy REST Countries v3 endpoint has been retired. This open data
    # repository provides the compatible country records without an API key.
    data = req_json(COUNTRY_DATA_URL)
    if not isinstance(data, list) or not data:
        raise ValueError("The country dataset returned no records")
    return data


@st.cache_data(ttl=86400, show_spinner=False)
def country(name):
    q = name.strip().casefold()
    aliases = {"usa": "united states", "us": "united states", "u.s.": "united states",
               "uk": "united kingdom", "u.k.": "united kingdom", "south korea": "south korea",
               "russia": "russia", "vietnam": "vietnam"}
    q = aliases.get(q, q)
    entries = all_countries()
    def names(c):
        return [c.get("name", {}).get("common", ""), c.get("name", {}).get("official", ""),
                c.get("cca2", ""), c.get("cca3", "")] + c.get("altSpellings", [])
    exact = [c for c in entries if q in {v.casefold() for v in names(c) if isinstance(v, str)}]
    if exact:
        return exact[0]
    partial = [c for c in entries if q in c.get("name", {}).get("common", "").casefold()]
    if len(partial) == 1:
        return partial[0]
    raise ValueError(f"Country not found or ambiguous: {name}. Try the full country name")


@st.cache_data(ttl=86400, show_spinner=False)
def indicator(code, metric):
    url = f"https://api.worldbank.org/v2/country/{code}/indicator/{metric}?format=json&per_page=80"
    try:
        payload = req_json(url)
    except requests.RequestException:
        return None, None, url
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        return None, None, url
    rows = [x for x in payload[1] if x.get("value") is not None]
    if not rows:
        return None, None, url
    rows.sort(key=lambda x: str(x.get("date", "")), reverse=True)
    row = rows[0]
    return float(row["value"]), str(row["date"]), url


def haversine(p1, p2):
    if len(p1) != 2 or len(p2) != 2:
        return None
    a, b, c, d = [math.radians(float(v)) for v in [p1[0], p1[1], p2[0], p2[1]]]
    x = math.sin((c-a)/2)**2 + math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 6371 * 2 * math.asin(min(1, math.sqrt(x)))


def band(v):
    return "Low" if v < 2 else "Moderate-low" if v < 3 else "Moderate-high" if v < 4 else "High"


def clamp(v):
    return max(1, min(5, int(round(v))))


def build(home, target, industry):
    h, t = country(home), country(target)
    if h["cca3"] == t["cca3"]:
        raise ValueError("Select two different countries.")
    hname, tname = h["name"]["common"], t["name"]["common"]
    csource = COUNTRY_DATA_PAGE
    langs_h = set(h.get("languages", {}).values())
    langs_t = set(t.get("languages", {}).values())
    shared = sorted(langs_h & langs_t)
    cultural = 2 if shared else 4
    if h.get("region") != t.get("region"):
        cultural = min(5, cultural + 1)
    cultural_reason = (f"Official languages: {hname}: {', '.join(sorted(langs_h)) or 'unavailable'}; "
                       f"{tname}: {', '.join(sorted(langs_t)) or 'unavailable'}. "
                       + (f"Shared language(s): {', '.join(shared)}. " if shared else "No shared listed official language. ")
                       + "This is a language/region proxy, not a validated measure of values, religion or cultural preferences.")
    source_country_h = COUNTRY_DATA_URL
    source_country_t = COUNTRY_DATA_URL

    # WGI rule-of-law point estimates: governance proxy, not actual treaty/sanctions checks.
    gov_h, gy_h, gu_h = indicator(h["cca2"], "RL.EST")
    gov_t, gy_t, gu_t = indicator(t["cca2"], "RL.EST")
    if gov_h is not None and gov_t is not None:
        gap = abs(gov_h-gov_t)
        admin = 1 if gap < 0.25 else 2 if gap < 0.5 else 3 if gap < 1 else 4 if gap < 1.5 else 5
        admin_reason = (f"World Bank Worldwide Governance Indicators, Rule of Law estimate: "
                        f"{hname} {gov_h:.2f} ({gy_h}), {tname} {gov_t:.2f} ({gy_t}); absolute gap {gap:.2f}. "
                        "Rule of law is only an institutional proxy. This does NOT establish the trade agreement, tariffs, sanctions, or sector licensing status between the countries.")
    else:
        admin, admin_reason = 3, "Rule-of-law data not available for both countries. Neutral placeholder score; verify treaties, sanctions, and regulatory requirements manually."

    pos_h = h.get("latlng") or []
    pos_t = t.get("latlng") or []
    km = haversine(pos_h, pos_t)
    if km is None:
        geo = 3
        geo_reason = "Coordinates unavailable for capital distance; neutral placeholder score."
    else:
        geo = 1 if km < 500 else 2 if km < 2000 else 3 if km < 5000 else 4 if km < 9000 else 5
        geo_reason = (f"Calculated great-circle country-coordinate to country-coordinate distance: {hname} to {tname}, approximately {km:,.0f} km "
                      "from the open country dataset coordinates (haversine formula). This is NOT actual freight distance or shipping time.")
    border = t["cca3"] in h.get("borders", []) or h["cca3"] in t.get("borders", [])
    if border:
        geo = max(1, geo-1)
        geo_reason += " Countries share a land border, reducing the score by one point."
    lpi_h, ly_h, lu_h = indicator(h["cca2"], "LP.LPI.OVRL.XQ")
    lpi_t, ly_t, lu_t = indicator(t["cca2"], "LP.LPI.OVRL.XQ")
    if lpi_h is not None and lpi_t is not None:
        geo_reason += f" World Bank LPI overall: {hname} {lpi_h:.2f} ({ly_h}); {tname} {lpi_t:.2f} ({ly_t}). LPI is context, not added to this distance score."

    gdp_h, yy_h, eu_h = indicator(h["cca2"], "NY.GDP.PCAP.CD")
    gdp_t, yy_t, eu_t = indicator(t["cca2"], "NY.GDP.PCAP.CD")
    if gdp_h is not None and gdp_t is not None and min(gdp_h, gdp_t) > 0:
        ratio = max(gdp_h, gdp_t)/min(gdp_h, gdp_t)
        econ = 1 if ratio < 1.2 else 2 if ratio < 1.6 else 3 if ratio < 2.5 else 4 if ratio < 5 else 5
        econ_reason = (f"World Bank GDP per capita, current US$: {hname} ${gdp_h:,.0f} ({yy_h}); "
                       f"{tname} ${gdp_t:,.0f} ({yy_t}); higher/lower ratio {ratio:.2f}×. "
                       "GDP per capita is a crude income proxy, not household purchasing power or product demand.")
    else:
        econ, econ_reason = 3, "Comparable World Bank GDP-per-capita data unavailable; neutral placeholder score."

    rows = {
        "Cultural": {"score": cultural, "reason": cultural_reason, "sources": [("Open country dataset: home languages and region", source_country_h), ("Open country dataset: target languages and region", source_country_t)], "limit": "Religion, values, and consumer behavior are not independently measured here."},
        "Administrative": {"score": admin, "reason": admin_reason, "sources": [("World Bank WGI: home country Rule of Law", gu_h), ("World Bank WGI: target country Rule of Law", gu_t)], "limit": "Must separately check actual bilateral agreements, tariffs, sanctions and industry regulations."},
        "Geographic": {"score": geo, "reason": geo_reason, "sources": [("Open country dataset: home coordinates", source_country_h), ("Open country dataset: target coordinates", source_country_t)] + ([("World Bank LPI: home", lu_h), ("World Bank LPI: destination", lu_t)] if lpi_h is not None and lpi_t is not None else []), "limit": "Straight-line distance is not a shipping route or logistics quotation."},
        "Economic": {"score": econ, "reason": econ_reason, "sources": [("World Bank GDP per capita: home", eu_h), ("World Bank GDP per capita: target", eu_t)], "limit": "GDP per capita does not establish willingness to pay, market size or margin."},
    }
    return {"home": hname, "target": tname, "industry": industry, "rows": rows, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}


def weighted(rows, weights):
    return sum(rows[d]["score"]*weights[d] for d in DIMS)/100


def explanation_for_industry(industry, dim):
    tailored = {
        "Video game retail": {"Cultural": "Game preferences, language, and store experience require localization.", "Administrative": "Consumer, import and digital-content rules affect retail operations.", "Geographic": "Physical game inventory adds shipping friction, but digital products reduce it.", "Economic": "Game and hardware prices depend on consumer purchasing power."},
        "Cement & construction materials": {"Cultural": "A relatively standardized product limits language-related demand differences.", "Administrative": "Materials standards and import rules matter.", "Geographic": "Bulky and heavy material makes freight distance especially consequential.", "Economic": "Construction activity and project economics drive demand."},
        "Film, TV & media": {"Cultural": "Language and audience taste strongly affect content appeal.", "Administrative": "Content rights and broadcast rules can restrict distribution.", "Geographic": "Digital distribution limits physical transport costs.", "Economic": "Subscriptions and advertising revenues depend on local incomes."},
    }
    return tailored.get(industry, {}).get(dim, REASONS[dim])


def report_text(r, weights, stress, chosen):
    rows = r["rows"]
    base = weighted(rows, weights)
    changed = weighted(rows, stress)
    highest = max(DIMS, key=lambda d: rows[d]["score"]*weights[d])
    parts = [f"# CAGE Distance Explorer: {r['home']} → {r['target']}", f"Industry: {r['industry']}", f"Generated: {r['generated']}", "", "Scores are transparent heuristics, not validated country distance indices.", ""]
    for dim in DIMS:
        x = rows[dim]
        parts += [f"## {dim}: {x['score']}/5", x["reason"], f"Why industry weight {weights[dim]}%: {explanation_for_industry(r['industry'], dim)}", "Sources:"]
        parts += [f"- {n}: {u}" for n, u in x["sources"] if u]
        parts += [f"Limit: {x['limit']}", ""]
    parts += ["## Default weights and sensitivity", ", ".join(f"{d}: {weights[d]}%" for d in DIMS), f"Default: {base:.2f}/5 ({band(base)})", f"Stress scenario (50% on {chosen}): {changed:.2f}/5 ({band(changed)})", "", "## Recommendation", f"Treat {r['target']} as a {band(base).lower()}-distance screening case for {r['industry']}. Use a phased validation or pilot before making an entry commitment. Check local customer demand, tariffs, legal compliance and unit economics before deciding.", "", "## Single largest risk", f"{highest}: {rows[highest]['reason']}", "", "## Decision this tool cannot support", "It cannot approve opening a specific store, choosing an acquisition target or setting an investment budget. It lacks firm-level costs, demand validation, current tariffs and legal advice.", "", "## Mandatory manual checks", "Confirm bilateral trade agreement status: https://rtais.wto.org/", "Confirm relevant sanctions: https://ofac.treasury.gov/sanctions-programs-and-country-information"]
    return "\n".join(parts)


st.title("🌍 CAGE Distance Explorer")
st.caption("Live public-data CAGE screening • No paid Search grounding required • Based on Pankaj Ghemawat's framework")
st.info("This is a transparent, repeatable screening heuristic. Country statistics are retrieved when you run the analysis. Treaty, sanctions and industry regulations still require separate verification.")
with st.form("selection"):
    a, b = st.columns(2)
    home = a.text_input("Home country", "United States")
    target = b.text_input("Target country", "Japan")
    industry = st.selectbox("Industry (optional)", list(WEIGHTS), index=1)
    go = st.form_submit_button("🔎 Research & analyze", type="primary")
if go:
    try:
        with st.spinner("Fetching country-level evidence from open country dataset and World Bank…"):
            st.session_state["cage"] = build(home.strip(), target.strip(), industry)
    except Exception as e:
        st.error(f"Could not retrieve the country data: {e}. Please retry; check spelling and that public APIs are reachable.")
if "cage" in st.session_state:
    r = st.session_state["cage"]
    rows = r["rows"]
    default = dict(zip(DIMS, WEIGHTS[r["industry"]]))
    st.divider()
    st.subheader(f"{r['home']} → {r['target']} | {r['industry']}")
    st.caption("Data fetched: " + r["generated"] + ". Indicator years are labeled individually.")
    metrics = st.columns(4)
    for i, d in enumerate(DIMS):
        metrics[i].metric(d, f"{rows[d]['score']}/5")
    st.markdown("### 1. Country-level evidence and scores")
    for d in DIMS:
        x = rows[d]
        with st.expander(f"{d}: {x['score']}/5", expanded=True):
            st.write(x["reason"])
            st.write(f"**Industry importance ({default[d]}%):** {explanation_for_industry(r['industry'], d)}")
            st.markdown("**Country-level sources:**")
            for name, url in x["sources"]:
                if url:
                    st.markdown(f"- [{name}]({url})")
            st.caption("Limitation: " + x["limit"])
    st.markdown("### 2. Weights and sensitivity analysis")
    st.write("The four industry defaults add to 100%. Adjust the sliders; weights normalize automatically.")
    sliders = st.columns(4)
    inputs = {d: sliders[i].slider(d, 0, 100, default[d], key=f"weight_{r['generated']}_{d}") for i, d in enumerate(DIMS)}
    total = sum(inputs.values())
    if total == 0:
        st.warning("Set at least one weight above zero.")
        st.stop()
    adjusted = {d: 100*inputs[d]/total for d in DIMS}
    st.dataframe(pd.DataFrame([{"Dimension": d, "Score (1–5)": rows[d]["score"], "Default weight": f"{default[d]}%", "Adjusted weight": f"{adjusted[d]:.1f}%", "Weighted contribution": round(rows[d]["score"]*adjusted[d]/100, 2)} for d in DIMS]), hide_index=True, use_container_width=True)
    base = weighted(rows, default)
    now = weighted(rows, adjusted)
    stressed = max(DIMS, key=lambda d: rows[d]["score"])
    other_total = 100-default[stressed]
    stress = {d: (50 if d == stressed else (50*default[d]/other_total if other_total else 50/3)) for d in DIMS}
    scenario = weighted(rows, stress)
    m1, m2, m3 = st.columns(3)
    m1.metric("Industry default", f"{base:.2f}/5", band(base))
    m2.metric("Your adjusted weights", f"{now:.2f}/5", band(now))
    m3.metric(f"50% on {stressed}", f"{scenario:.2f}/5", band(scenario))
    st.write(f"**Sensitivity:** Raising the weight on {stressed} to 50% changes the distance rating from {band(base)} ({base:.2f}) to {band(scenario)} ({scenario:.2f}). " + ("The risk category changes: stronger caution is warranted." if band(base) != band(scenario) else "The category does not change, but mitigation priorities may."))
    st.caption("Scoring: 1 lowest friction; 5 highest. Weighting is an analyst judgment. Bands: <2 low; 2–<3 moderate-low; 3–<4 moderate-high; ≥4 high.")
    st.markdown("### 3. Recommendation to leadership")
    st.write(f"**Distance assessment:** {band(base)} overall for {r['industry']}, with important differences across the four dimensions. Consider a small pilot or targeted diligence, rather than treating this number as an investment approval.")
    risk = max(DIMS, key=lambda d: rows[d]["score"]*default[d])
    st.error(f"**Single largest weighted risk: {risk}.** {rows[risk]['reason']}")
    st.write("**What this tool cannot decide:** Whether to open a particular location, commit a specific budget, or enter the market by acquisition. It does not model firm-level profit, verify customer demand or confirm current legal restrictions.")
    st.warning("**Administrative verification required:** World Bank rule-of-law differences are not evidence of bilateral treaty status, tariffs or sanctions. Before submission or real-world use, check the [WTO regional trade agreements database](https://rtais.wto.org/) and [official U.S. sanctions programs](https://ofac.treasury.gov/sanctions-programs-and-country-information) for the specific country pair. The tool intentionally does not invent a status.")
    st.download_button("⬇️ Download report (Markdown)", report_text(r, default, stress, stressed), file_name="cage_report.md", mime="text/markdown")
st.divider()
st.caption("Source data: mledoze/countries open dataset (languages, borders, country coordinates) and World Bank (rule of law, logistics index, GDP per capita). Scores are not Hofstede scores or guaranteed trade-policy findings. Verify source dates and country coverage before submitting the PDF.")
