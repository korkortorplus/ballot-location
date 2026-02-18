"""Streamlit app to test OpenRouter models for Thai geocoding tool use.

Usage:
    fnox exec -- uv run streamlit run ect69-geo-decoding/scripts/test_openrouter_models.py
"""

import json
import os
import time

import pandas as pd
import streamlit as st
from openai import OpenAI

# --- Config ---

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

MODELS = [
    # Free models with tool use
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-120b:free",
    "qwen/qwen3-coder:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "z-ai/glm-4.5-air:free",
    # Cheap paid (< $0.10/M input)
    "openai/gpt-4.1-nano",
    "openai/gpt-oss-120b",
    "google/gemini-2.0-flash-001",
    "deepseek/deepseek-chat-v3-0324",
    "mistralai/mistral-small-3.2-24b-instruct",
    # Mid-range
    "google/gemini-2.5-flash",
    "openai/gpt-4.1-mini",
    "anthropic/claude-haiku-4.5",
]

SAMPLE_LOCATIONS = [
    {
        "raw": "เต็นท์บริเวณริมคลองคูเมืองเดิม ถนนอัษฎางค์ #ตรงข้าม บริษัท นัฐพงษ์เซลส์แอนด์เซอร์วิส จำกัด",
        "province": "กรุงเทพมหานคร",
        "amphoe": "พระนคร",
        "tambon": "พระบรมมหาราชวัง",
    },
    {
        "raw": "ศาลาประชาคม หมู่ที่ 3",
        "province": "จังหวัดปทุมธานี",
        "amphoe": "สามโคก",
        "tambon": "บ้านปทุม",
    },
    {
        "raw": "หอประชุมอำเภอกุมภวาปี",
        "province": "จังหวัดอุดรธานี",
        "amphoe": "กุมภวาปี",
        "tambon": "กุมภวาปี",
    },
    {
        "raw": "อาคารอเนกประสงค์ องค์การบริหารส่วนตำบลท่าช้าง",
        "province": "จังหวัดนครราชสีมา",
        "amphoe": "เฉลิมพระเกียรติ",
        "tambon": "ท่าช้าง",
    },
    {
        "raw": "ณ ศาลากลางบ้าน",
        "province": "จังหวัดอุบลราชธานี",
        "amphoe": "โพธิ์ไทร",
        "tambon": "ม่วงใหญ่",
    },
]

SYSTEM_PROMPT = """\
You are a Thai geocoding agent. Given a voting station location description and its administrative context (province, amphoe, tambon), produce a geocoding plan as a JSON object.

Your job is to:
1. Parse the raw Thai location text and identify the main place name, sub-location, road/landmark clues.
2. Produce an ordered list of geocoding attempts using the available tools.
3. Produce executable assertions to validate the result.

Query construction rules:
- For geocode tools (nominatim, google_geocode): keep the query SHORT — just the core place name. Geocoders work best with concise input + spatial constraints.
- For text search (google_textsearch): include EVERYTHING — sub-location, road, amphoe, province. Text search is fuzzy and benefits from more context.
- Both may return multiple results. The plan should note which result to pick (closest to anchor, inside tambon, etc.)

Output a JSON object with these fields:
- reasoning: string explaining your analysis of the location
- plan: array of {step, query, service, why} where service is one of: nominatim, google_geocode, google_textsearch, overpass
- assertions: array of executable checks {check, query, service, op, value_m} or {check, query, service, expect}

Respond with ONLY the JSON object, no markdown fences."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "geocode_nominatim",
            "description": "Free-form search on self-hosted Nominatim (OSM data for Thailand). Best with short, specific place names.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query, keep short and specific",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "geocode_google",
            "description": "Google Geocoding API with bounds bias. Use short place name, bounds constrains results spatially.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Short place name to geocode",
                    },
                    "bounds": {
                        "type": "object",
                        "description": "Soft rectangular bias (tambon/amphoe bounding box)",
                        "properties": {
                            "sw_lat": {"type": "number"},
                            "sw_lng": {"type": "number"},
                            "ne_lat": {"type": "number"},
                            "ne_lng": {"type": "number"},
                        },
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_google_places",
            "description": "Google Places Text Search (New). Include everything in query. Use locationRestriction (hard bbox) OR locationBias (soft circle), not both.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Rich query with all context (name, road, amphoe, province)",
                    },
                    "location_restriction": {
                        "type": "object",
                        "description": "Hard rectangular constraint (results must be inside)",
                        "properties": {
                            "sw_lat": {"type": "number"},
                            "sw_lng": {"type": "number"},
                            "ne_lat": {"type": "number"},
                            "ne_lng": {"type": "number"},
                        },
                    },
                    "location_bias": {
                        "type": "object",
                        "description": "Soft circular bias (results prefer this area)",
                        "properties": {
                            "center_lat": {"type": "number"},
                            "center_lng": {"type": "number"},
                            "radius_m": {"type": "number"},
                        },
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_overpass",
            "description": "Query OSM features via Overpass API. Use for road geometry, POIs, waterways.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Overpass QL query",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def get_client() -> OpenAI:
    api_key = os.environ.get("OPENROUTER_KEY")
    if not api_key:
        st.error(
            "OPENROUTER_KEY not set. Run with: `fnox exec -- uv run streamlit run ...`"
        )
        st.stop()
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)


def test_model(client: OpenAI, model: str, location: dict, use_tools: bool) -> dict:
    user_msg = json.dumps(location, ensure_ascii=False)

    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
    }
    if use_tools:
        kwargs["tools"] = TOOLS
        kwargs["tool_choice"] = "auto"

    t0 = time.time()
    try:
        response = client.chat.completions.create(**kwargs)
        elapsed = time.time() - t0
        choice = response.choices[0]

        result = {
            "model": model,
            "elapsed_s": round(elapsed, 2),
            "finish_reason": choice.finish_reason,
            "content": choice.message.content or "",
            "tool_calls": [],
            "usage": None,
            "error": None,
        }

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                result["tool_calls"].append(
                    {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                )

        if response.usage:
            result["usage"] = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return result
    except Exception as e:
        return {
            "model": model,
            "elapsed_s": round(time.time() - t0, 2),
            "finish_reason": "error",
            "content": "",
            "tool_calls": [],
            "usage": None,
            "error": str(e),
        }


# --- UI ---

st.set_page_config(page_title="OpenRouter Model Tester", layout="wide")
st.title("OpenRouter Model Tester — Thai Geocoding Tool Use")

st.markdown(
    "Test different models for Thai location parsing + geocoding plan generation. "
    "Evaluates: Thai understanding, tool calling, JSON output quality."
)

# Sidebar
with st.sidebar:
    st.header("Settings")

    selected_models = st.multiselect(
        "Models to test",
        options=MODELS,
        default=MODELS[:3],
    )

    custom_model = st.text_input(
        "Custom model ID (optional)", placeholder="meta-llama/llama-4-maverick:free"
    )
    if custom_model:
        selected_models.append(custom_model)

    use_tools = st.checkbox("Send tool definitions", value=True)

    st.divider()
    st.header("Test Location")

    location_choice = st.selectbox(
        "Pick a sample",
        options=range(len(SAMPLE_LOCATIONS)),
        format_func=lambda i: f"{SAMPLE_LOCATIONS[i]['tambon']} — {SAMPLE_LOCATIONS[i]['raw'][:40]}...",
    )

    location = SAMPLE_LOCATIONS[location_choice]
    custom_raw = st.text_area("Or edit raw text", value=location["raw"])
    location = {**location, "raw": custom_raw}

    st.json(location)

# Main area
if st.button("Run Test", type="primary", width="stretch"):
    if not selected_models:
        st.warning("Select at least one model.")
        st.stop()

    client = get_client()
    results = []

    cols = st.columns(len(selected_models))

    for i, model in enumerate(selected_models):
        with cols[i]:
            st.subheader(model.split("/")[-1], divider=True)
            with st.spinner(f"Testing {model}..."):
                result = test_model(client, model, location, use_tools)
                results.append(result)

            if result["error"]:
                st.error(result["error"])
                continue

            # Metrics
            m1, m2 = st.columns(2)
            m1.metric("Time", f"{result['elapsed_s']}s")
            if result["usage"]:
                m2.metric("Tokens", result["usage"]["total_tokens"])

            st.caption(f"finish_reason: `{result['finish_reason']}`")

            # Tool calls
            if result["tool_calls"]:
                st.markdown("**Tool calls:**")
                for tc in result["tool_calls"]:
                    with st.expander(f"`{tc['name']}`"):
                        try:
                            st.json(json.loads(tc["arguments"]))
                        except json.JSONDecodeError:
                            st.code(tc["arguments"])

            # Content
            if result["content"]:
                st.markdown("**Response:**")
                try:
                    parsed = json.loads(result["content"])
                    st.json(parsed)
                except json.JSONDecodeError:
                    st.text(result["content"][:2000])

    # Summary table
    if results:
        st.divider()
        st.subheader("Summary")
        summary_rows = []
        for r in results:
            has_thai = any(
                "\u0e00" <= c <= "\u0e7f"
                for c in (
                    r["content"] + "".join(tc["arguments"] for tc in r["tool_calls"])
                )
            )
            try:
                parsed = json.loads(r["content"]) if r["content"] else None
                valid_json = parsed is not None and "plan" in parsed
            except (json.JSONDecodeError, TypeError):
                valid_json = False

            summary_rows.append(
                {
                    "Model": r["model"].split("/")[-1],
                    "Time (s)": r["elapsed_s"],
                    "Tokens": r["usage"]["total_tokens"] if r["usage"] else 0,
                    "Tool Calls": len(r["tool_calls"]),
                    "Valid JSON Plan": valid_json,
                    "Has Thai": has_thai,
                    "Finish": r["finish_reason"],
                    "Error": r["error"] or "",
                }
            )
        st.dataframe(pd.DataFrame(summary_rows), width="stretch")
