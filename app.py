import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="CAGE Distance Explorer", page_icon="🌍", layout="wide")

DIMENSIONS = ["Cultural", "Administrative", "Geographic", "Economic"]
DIM_DETAILS = {
    "Cultural": "Language, religious traditions, social norms, values, and consumption patterns",
    "Administrative": "Trade agreements, sanctions, political relationships, regulations, institutional differences",
    "Geographic": "Actual distance, borders, time zones, transport corridors, and logistics",
    "Economic": "Income levels, purchasing power, wages, cost structures, and market affordability",
}

INDUSTRY_WEIGHTS = {
    "General / unspecified": [25, 25, 25, 25],
    "Video game retail": [30, 20, 15, 35],
    "Film, TV & media": [40, 20, 15, 25],
    "Cement & construction materials": [10, 20, 45, 25],
    "Software / SaaS": [25, 30, 10, 35],
    "Food & beverages": [35, 25, 20, 20],
    "Consumer electronics": [20, 25, 25, 30],
    "Financial services": [20, 40, 10, 30],
}


def get_key():
    try:
        return st.secrets.get("GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    except Exception:
        return os.getenv("GEMINI_API_KEY", "")


def clean_json(raw):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def gather_research(client, model, home, target, industry):
    prompt = f"""You are a country risk research analyst applying Pankaj Ghemawat's CAGE framework.
Research HOME={home!r} and TARGET={target!r} for INDUSTRY={industry!r}.
Use Google Search. State specific, sourced country-pair FACTS for each of the FOUR dimensions.
Cultural: comparable cultural indices (e.g., Hofstede / Culture Factor if available), languages, and norms.
Administrative: trade agreements, tariffs/status, sanctions status, policy and regulatory differences. Do not claim absence of sanctions without checking.
Geographic: actual approximate city-to-city or capital-to-capital distance in kilometers (name the endpoints), borders, logistics rankings/infrastructure where supported.
Economic: latest available World Bank GDP per capita (specify indicator, values, and years where verified), income classification, or alternative comparable indicators.
For each dimension find at least one SOURCE specifically supporting a COUNTRY-LEVEL claim. Favor primary sources: World Bank, WTO, US Trade Representative, government trade offices, UN Comtrade, World Bank LPI, CEPII distance, Hofstede/Culture Factor, and official statistics.
Separate facts from interpretation; mark unsupported figures as UNVERIFIED, never guess. Write research notes with four explicit headings and cite your sources inline when possible. Also give a list of source titles and URLs at end if available. This is research, not a recommendation yet."""
    result = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            
        ),
    )
    notes = result.text or ""
    sources = []
    for cand in (result.candidates or []):
        md = getattr(cand, "grounding_metadata", None)
        if not md:
            continue
        for chunk in (getattr(md, "grounding_chunks", None) or []):
            web = getattr(chunk, "web", None)
            if web and getattr(web, "uri", None):
                sources.append({"title": getattr(web, "title", "Source") or "Source", "url": web.uri})
    dedup = {s["url"]: s for s in sources}
    return notes, list(dedup.values())


def organize(client, model, home, target, industry, notes, sources):
    source_lines = "\n".join(f"[{i}] {s['title']} | {s['url']}" for i, s in enumerate(sources))
    prompt = f"""Convert the search-grounded country research below into a conservative, transparent CAGE risk assessment.
HOME: {home}; TARGET: {target}; INDUSTRY: {industry}.
DISTANCE SCORE: 1=very similar / low expansion friction, 2=low, 3=moderate, 4=high, 5=very high.
Each score is an analytical judgment, NOT a validated universal index. Give a precise score justification drawing on the researched facts and industry. If evidence is too thin, flag uncertainty. Do NOT introduce new unsupported numerical facts.
ONLY cite source IDs from this ACTUAL search-grounding source list. For each dimension use source_ids with 1+ relevant IDs if possible; never fabricate URLs or IDs. If none of these sources supports a dimension set source_ids to [] and say evidence is insufficient.
Sources:
{source_lines or '(No grounding sources returned)'}

Research notes:
{notes[:24000]}

Return ONLY JSON matching this shape, with all four dimension keys:
{{"dimensions":{{"Cultural":{{"score":3,"reasoning":"...","key_facts":["..."],"source_ids":[0],"caution":"..."}},"Administrative":{{"score":3,"reasoning":"...","key_facts":["..."],"source_ids":[0],"caution":"..."}},"Geographic":{{"score":3,"reasoning":"...","key_facts":["..."],"source_ids":[0],"caution":"..."}},"Economic":{{"score":3,"reasoning":"...","key_facts":["..."],"source_ids":[0],"caution":"..."}}}},"weight_justification":{{"Cultural":"...","Administrative":"...","Geographic":"...","Economic":"..."}},"largest_risk_dimension":"Cultural","largest_risk":"specific single biggest expansion risk for leadership, and why","recommendation":"balanced management recommendation including due diligence, not a yes/no investment approval","limitations":"specific facts and decisions this tool cannot establish"}}
"""
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    data = clean_json(response.text)
    for dim in DIMENSIONS:
        item = data["dimensions"][dim]
        item["score"] = max(1, min(5, int(round(float(item["score"])))))
        item["source_ids"] = [int(i) for i in item.get("source_ids", []) if str(i).isdigit() and 0 <= int(i) < len(sources)]
    return data


def score(weights, dims):
    return sum(weights[d] * dims[d]["score"] for d in DIMENSIONS) / 100


def level(s):
    if s < 2:
        return "Low"
    if s < 3:
        return "Moderate-low"
    if s < 4:
        return "Moderate-high"
    return "High"


def shift_weights(weights, risky):
    # Deliberately stress the dimension that received the highest distance score.
    # Increase it to 50% and redistribute the other 50% proportionally.
    other = [d for d in DIMENSIONS if d != risky]
    rest = sum(weights[d] for d in other)
    if rest == 0:
        return {d: (50 if d == risky else (17 if d != other[-1] else 16)) for d in DIMENSIONS}
    vals = {d: (50 if d == risky else 50 * weights[d] / rest) for d in DIMENSIONS}
    return vals


st.title("🌍 CAGE Distance Explorer")
st.caption("AI-assisted, source-grounded international expansion screening • Based on Pankaj Ghemawat's CAGE framework")
st.info("Scores are decision aids, not objectively measured distances. Always open and verify cited sources before making consequential decisions.")

with st.form("inputs"):
    a, b = st.columns(2)
    with a:
        home = st.text_input("Home country", value="United States").strip()
    with b:
        target = st.text_input("Target country", value="Japan").strip()
    industry_choice = st.selectbox("Industry (optional)", list(INDUSTRY_WEIGHTS.keys()) + ["Other (describe)"] , index=1)
    industry = st.text_input("Describe your industry", value="", placeholder="e.g., medical devices") if industry_choice == "Other (describe)" else industry_choice
    model = st.selectbox("Gemini model", ["gemini-3.8-flash"], index=0)
    analyze = st.form_submit_button("🔎 Research & analyze", type="primary")

if analyze:
    if not home or not target or not industry:
        st.error("Enter two countries and an industry (or select General / unspecified).")
    elif home.lower() == target.lower():
        st.error("Choose two different countries.")
    elif not get_key():
        st.error("Missing GEMINI_API_KEY. Add it in Streamlit Community Cloud → App settings → Secrets.")
    else:
        try:
            client = genai.Client(api_key=get_key())
            with st.spinner("Researching the country pair and compiling source links…"):
                notes, sources = gather_research(client, model, home, target, industry)
            with st.spinner("Scoring the four dimensions and writing the strategic recommendation…"):
                data = organize(client, model, home, target, industry, notes, sources)
            st.session_state["report"] = {"home": home, "target": target, "industry": industry, "industry_choice": industry_choice, "data": data, "sources": sources, "notes": notes, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
        except Exception as exc:
            st.error(f"Analysis could not complete: {exc}")
            st.caption("If this is a model/quota error, check your AI Studio free-tier rate limits or try the other model.")

if "report" in st.session_state:
    report = st.session_state["report"]
    data, dims, sources = report["data"], report["data"]["dimensions"], report["sources"]
    st.divider()
    st.subheader(f"{report['home']} → {report['target']} | {report['industry']}")
    st.caption(f"Generated {report['generated']}; fact freshness varies by source")

    initial = INDUSTRY_WEIGHTS.get(report["industry_choice"], INDUSTRY_WEIGHTS["General / unspecified"])
    base_weights = dict(zip(DIMENSIONS, initial))
    st.markdown("### 1. Distance by dimension")
    metrics = st.columns(4)
    for i, d in enumerate(DIMENSIONS):
        with metrics[i]:
            st.metric(d, f"{dims[d]['score']} / 5")

    for d in DIMENSIONS:
        item = dims[d]
        with st.expander(f"{d} — {item['score']}/5", expanded=True):
            st.write(item.get("reasoning", ""))
            facts = item.get("key_facts", [])
            if facts:
                st.markdown("**Evidence cited in the research:**")
                for fact in facts:
                    st.markdown(f"- {fact}")
            st.markdown(f"**Industry relevance:** {data.get('weight_justification', {}).get(d, 'Not specified')}")
            ids = item.get("source_ids", [])
            if ids:
                st.markdown("**Search-grounding sources (open to verify the claims):**")
                for i in ids:
                    s = sources[i]
                    st.markdown(f"- [{s['title']}]({s['url']})")
            else:
                st.warning("No linked research source was assigned to this dimension. Verify independently before submission.")
            st.caption(f"Important caution: {item.get('caution', 'Scores are subjective')}")

    st.markdown("### 2. Industry weighting and sensitivity")
    st.write("Default weights reflect how the selected industry could amplify or reduce each kind of distance. Change them below; weights automatically normalize to 100%.")
    weight_cols = st.columns(4)
    raw = {}
    for i, d in enumerate(DIMENSIONS):
        with weight_cols[i]:
            raw[d] = st.slider(d, min_value=0, max_value=100, value=base_weights[d], key=f"w_{report['generated']}_{d}")
    if sum(raw.values()) == 0:
        st.error("At least one weight must be positive.")
        st.stop()
    adjusted = {d: 100 * raw[d] / sum(raw.values()) for d in DIMENSIONS}
    table = pd.DataFrame([{"Dimension": d, "Distance (1–5)": dims[d]["score"], "Default weight": f"{base_weights[d]}%", "Adjusted weight": f"{adjusted[d]:.1f}%", "Weighted contribution": f"{dims[d]['score']*adjusted[d]/100:.2f}"} for d in DIMENSIONS])
    st.dataframe(table, hide_index=True, use_container_width=True)
    base_result = score(base_weights, dims)
    adj_result = score(adjusted, dims)
    stressed_dim = max(DIMENSIONS, key=lambda d: dims[d]["score"])
    stress = shift_weights(base_weights, stressed_dim)
    stress_result = score(stress, dims)
    col1, col2, col3 = st.columns(3)
    col1.metric("Default weighted score", f"{base_result:.2f}/5", level(base_result))
    col2.metric("Your adjusted score", f"{adj_result:.2f}/5", level(adj_result))
    col3.metric("50% on highest-risk dimension", f"{stress_result:.2f}/5", level(stress_result))
    st.write(f"**Sensitivity scenario:** Increase {stressed_dim} to 50% of decision weight, redistributing the remaining 50% proportionally. "
             f"Score changes from **{base_result:.2f} ({level(base_result)})** to **{stress_result:.2f} ({level(stress_result)})**. "
             + ("The overall rating changes, so the strategic recommendation is weight-sensitive." if level(base_result) != level(stress_result) else "The overall rating remains in the same band, but the top risks and mitigation priority still deserve scrutiny."))
    st.caption("Weighted score is a transparent heuristic, NOT a validated probability of success. Thresholds: <2 low, 2–<3 moderate-low, 3–<4 moderate-high, ≥4 high.")

    st.markdown("### 3. Recommendation to leadership")
    st.write(data.get("recommendation", ""))
    st.error(f"**Single largest flagged risk — {data.get('largest_risk_dimension', '')}:** {data.get('largest_risk', '')}")
    st.markdown("**What this tool cannot decide:**")
    st.write(data.get("limitations", ""))

    st.markdown("### 4. Research transparency")
    missing = [d for d in DIMENSIONS if not dims[d].get("source_ids")]
    if missing:
        st.warning("Missing attributed links for: " + ", ".join(missing) + ". This analysis is not ready for submission until verified evidence is found.")
    st.caption("The list below comes from Gemini's Google Search grounding metadata. A returned link is not proof that every generated claim is accurate. Verify URLs, numbers, dates, and relevance. Search grounding may supply redirect links.")
    with st.expander("All retrieved research links"):
        for s in sources:
            st.markdown(f"- [{s['title']}]({s['url']})")
    with st.expander("Original grounded research notes"):
        st.text(report["notes"])

    markdown = [f"# CAGE Distance Report: {report['home']} → {report['target']}", f"Industry: {report['industry']}", f"Generated: {report['generated']}", ""]
    for d in DIMENSIONS:
        item = dims[d]
        markdown += [f"## {d}: {item['score']}/5", item.get('reasoning', ''), "Industry relevance: " + data.get('weight_justification', {}).get(d, ''), "Sources:"]
        markdown += [f"- {sources[i]['title']}: {sources[i]['url']}" for i in item.get('source_ids', [])]
        markdown.append("")
    markdown += ["## Weighting and sensitivity", "Default weights: " + ", ".join(f"{d} {base_weights[d]}%" for d in DIMENSIONS), f"Default composite: {base_result:.2f}/5 ({level(base_result)})", f"Stress test (50% weight on {stressed_dim}): {stress_result:.2f}/5 ({level(stress_result)})", "", "## Recommendation", data.get('recommendation', ''), "", "## Single largest risk", data.get('largest_risk', ''), "", "## Limitations", data.get('limitations', '')]
    st.download_button("⬇️ Download report text", data="\n".join(markdown), file_name="cage_report.md", mime="text/markdown")

st.divider()
st.caption("For coursework: use the publicly accessible app URL in your PDF. Test it in a private/incognito browser window. Gemini requests are subject to the API project's quotas and availability. Do not upload API keys to GitHub.")
