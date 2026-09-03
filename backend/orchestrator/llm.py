"""
Vertex AI Gemini wrapper.

Replaces NeuralKG's provider-agnostic llm.py (OpenAI / Gemini API key /
Azure OpenAI) with a single, direct Vertex AI integration authenticated by the
Cloud Run service account — no API keys anywhere in this codebase.

Two model tiers, matching the plan:
  - PLAN_MODEL:    fast classification / question-shape / SQL drafting
  - SYNTHESIS_MODEL: narrative answer + citations + presentation spec

Model names are read from env so they can be bumped (e.g. Gemini 3.x) without
a code change once a new tier is GA on Vertex AI.

Both `classify_and_plan` and `synthesize` return `(result, usage)` — `usage`
is the real prompt/output/total token counts from the Gemini response's
`usage_metadata`, threaded through pipeline.py into the per-query walkthrough
and guardrails.record_usage's cost calculation, instead of a flat per-call
cost guess.
"""
import os
import json
from google import genai
from google.genai import types

from ..accessor import okf_loader
from . import packs

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "atlas-ard-okf")
LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
PLAN_MODEL = os.environ.get("ATLAS_PLAN_MODEL", "gemini-2.5-flash")
SYNTHESIS_MODEL = os.environ.get("ATLAS_SYNTHESIS_MODEL", "gemini-2.5-pro")

_client = None


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    return _client


def _usage(resp) -> dict:
    """Real token counts off `resp.usage_metadata` (confirmed field name on
    the pinned google-genai==0.7.0 SDK — GenerateContentResponseUsageMetadata
    has prompt_token_count / candidates_token_count / total_token_count).
    Falls back to zeros rather than raising if a future SDK bump renames or
    drops the field, since a missing cost number shouldn't break an answer."""
    u = getattr(resp, "usage_metadata", None)
    if u is None:
        return {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": u.prompt_token_count or 0,
        "output_tokens": u.candidates_token_count or 0,
        "total_tokens": u.total_token_count or 0,
    }


PRESENTATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "narrative": {"type": "STRING"},
        "citations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "source_id": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "trust": {"type": "STRING", "enum": ["unverified", "machine-confirmed", "human-reviewed"]},
                },
                "required": ["source_id", "title", "trust"],
            },
        },
        "visualization": {
            "type": "OBJECT",
            "properties": {
                "kind": {"type": "STRING", "enum": ["table", "bar", "line", "kpi_cards", "map", "infographic"]},
                "data": {"type": "STRING", "description": "JSON-encoded data payload for the chosen kind"},
            },
            "required": ["kind", "data"],
        },
    },
    "required": ["narrative", "citations", "visualization"],
}


def _describe_candidate_for_planning(c: dict) -> dict:
    """Candidates arrive from discovery.py as embedding-search results
    (title/trust/score) with no parameter info attached. For an
    AttestedComputation candidate specifically, load its full OKF doc so the
    prompt can list its *declared* parameters (name/type/description) by
    name.

    Without this, the planner has no way to know what to extract from the
    question, and every AttestedComputation call fails with
    bigquery_accessor.run_attested_computation's "Missing required
    parameter" ValueError — this was a real bug found by actually running a
    query end to end, not just reading the code: the original prompt asked
    for {shape, source_id, needs_sql} only and never mentioned parameters at
    all, so `plan.get("params", {})` was always empty.

    For a plain BigQuery table candidate (needs_sql path, no
    required_params), the same problem exists one level down: the planner
    drafts raw SQL against the real table, but discovery.py's candidate dict
    already dropped everything except title/trust/type before this function
    even saw it. `c["description"]` — built deterministically from
    INFORMATION_SCHEMA.COLUMNS by the crawler (backend/crawler/main.py's
    `_describe_table`), never model-generated — is the one place the real
    column names survive. Without forwarding it here, the planner has to
    guess column names from the table's title alone, and it guesses
    plausible-sounding ones that don't exist: confirmed live via two
    different BigQuery 400s in the same session — "Unrecognized name:
    mean_aqi" against epa_historical_air_quality.co_daily_summary, and
    "Unrecognized name: place_name" against census_bureau_acs.cbsa_2010_5yr.

    Also forwards discovery's own relevance `score` (0-1, higher = better
    semantic match) — computed by discovery.py and already shown in the
    frontend walkthrough, but previously dropped before ever reaching this
    prompt. That gap was a real bug found live: asked to compare life
    expectancy in Japan vs. the US, discovery correctly ranked
    world_bank_health_population.country_summary highest, but with no score
    visible in the prompt the planner picked covid19_open_data instead —
    present in the candidate list, superficially plausible from its title
    alone, but wrong — and fetched Japan's Human Development Index: a real
    number, just not the one asked about."""
    out = {
        "source_id": c["source_id"],
        "title": c["title"],
        "type": c.get("type"),
        "trust": c["trust"],
        "score": round(c["score"], 3),
    }
    if c.get("type") == "AttestedComputation":
        doc = okf_loader.load_by_id(c["source_id"])
        if doc and doc.computation:
            out["required_params"] = [
                {
                    "name": p["name"],
                    "type": p.get("type", "STRING"),
                    "description": p.get("description", ""),
                    # Defaults to True so every existing template (which never
                    # declared this field) keeps its original strictly-required
                    # behavior. The SEC EDGAR template is the first to declare
                    # an optional one (fiscal_year) — see classify_and_plan's
                    # prompt for how optional params are handled differently.
                    "required": p.get("required", True),
                }
                for p in doc.computation.get("runtime", {}).get("parameters", [])
            ]
    elif c.get("kind") == "bigquery":
        out["schema"] = c.get("description", "")
    return out


def classify_and_plan(question: str, candidates: list[dict], pack: str = packs.DEFAULT_PACK) -> tuple[dict, dict]:
    """PLAN_MODEL call: question shape + source routing + optional SQL draft
    or template parameter extraction. Returns (plan, usage). `pack` only
    appends that pack's glossary (empty for the public pack, so the public
    prompt is byte-for-byte what it was)."""
    described = [_describe_candidate_for_planning(c) for c in candidates]
    single_candidate = len(candidates) == 1
    prompt = (
        "You are Atlas's query planner. Given a user question and a list of "
        "candidate data sources (each already ARD-matched by embedding "
        "similarity), decide the question shape (point, ranking, aggregate, "
        "trend, status) and which single candidate best answers it.\n\n"
        + (
            "There is only one candidate here — you are drafting fresh SQL or "
            "params for it specifically (this is a backtrack retry against a "
            "different table than was originally tried), so `source_id` in "
            "your response must be this candidate's.\n\n"
            if single_candidate else
            "Candidates are listed in DESCENDING order of `score` (0-1, "
            "discovery's own embedding-similarity ranking) — the first "
            "candidate is the best semantic match already. Prefer it unless "
            "you have a specific, concrete reason it can't answer the "
            "question (e.g. its `schema` is missing a column the question "
            "needs, or it has `required_params` the question doesn't supply "
            "values for) — a lower-scored candidate merely *sounding* more "
            "on-topic from its title is not a good enough reason to override "
            "the ranking. Confirmed live: asked to compare life expectancy "
            "in Japan vs. the US, the top-ranked candidate was the correct "
            "health/population table, but it got passed over for a "
            "COVID-data table that had no score attached to weigh against it.\n\n"
        )
        + "If the chosen candidate has a `required_params` list, it is a "
        "human-reviewed template (an AttestedComputation — not necessarily "
        "SQL; some run against a REST API instead) — you MUST extract a "
        "value for every parameter whose own `required` field is true, "
        "directly from the question's own wording (use each parameter's "
        "`description` as a guide for the expected format, e.g. a full "
        "county name, a two-letter state code, or one of a fixed set of "
        "curated metric keys) and return them under \"params\", keyed by "
        "parameter name. If the question doesn't actually supply enough "
        "information for one of that template's REQUIRED parameters, do "
        "NOT choose it — pick a different candidate instead, or set "
        "needs_sql to true and draft ad-hoc SQL against a plain table "
        "candidate. A parameter with `required: false` is different: only "
        "extract and include it under \"params\" when the question actually "
        "specifies a value for it (e.g. names a specific year) — its "
        "absence from the question should NOT block you from choosing that "
        "candidate, and you must never guess or invent a value to fill it "
        "in. Omit it from \"params\" entirely rather than guessing.\n\n"
        "If you draft ad-hoc SQL for a plain BigQuery table candidate "
        "(needs_sql: true, no required_params), inline all literal values "
        "directly in the SQL text — do not use query parameters there — "
        "and put the SQL under \"sql\". That candidate's `schema` field (if "
        "present) is the table's REAL column list, taken directly from "
        "BigQuery's own INFORMATION_SCHEMA — use ONLY column names that "
        "appear there. Never invent or guess a column name from the table's "
        "title/description, even one that sounds plausible: BigQuery will "
        "reject the query outright, and a name that merely sounds right for "
        "the domain (e.g. assuming an air-quality table exposes `mean_aqi`, "
        "or a place table exposes `place_name`) is exactly the mistake this "
        "warns against — both have failed against real tables before. If a "
        "candidate has no `schema` field, do not choose it for ad-hoc SQL.\n\n"
        "The question might name more than one entity to compare (e.g. "
        "\"Japan vs. the United States\", \"California and Texas\") — if so, "
        "your SQL must fetch a row for EVERY named entity (e.g. "
        "`WHERE country_name IN ('Japan', 'United States')`), never just the "
        "first one, or the comparison the question actually asked for is "
        "impossible to answer from what you fetched.\n\n"
        "When your WHERE clause filters a free-text column that holds "
        "names, places, or search terms (not a numeric ID or a short coded "
        "enum), do NOT use exact equality — real-world text data routinely "
        "doesn't match a user's exact phrasing (e.g. a place-name column may "
        "store \"Austin city, Texas\" when the question just says \"Austin, "
        "Texas\"). Use a case-insensitive partial match instead, e.g. "
        "`LOWER(place_name) LIKE LOWER('%Austin%')`, unless the schema shows "
        "a shorter coded column for the same thing (a 2-letter state code, "
        "a FIPS code) — prefer that coded column with its correct code "
        "value over free-text matching whenever one is available, since an "
        "exact-match query against a coded column is reliable in a way "
        "free-text matching on a spelled-out name usually isn't. Confirmed "
        "live: exact-match SQL against free-text columns returned 0 rows "
        "for a median-income-by-city question and a state-unemployment "
        "question, both with real matching data sitting in the table.\n\n"
        + packs.glossary(pack)
        + f"Question: {question!r}\nCandidates: {json.dumps(described)}\n"
        "Respond as JSON: {\"shape\": str, \"source_id\": str, "
        "\"needs_sql\": bool, \"sql\": str or null, \"params\": object, "
        "\"reasoning\": str}. Always include \"params\" — an empty object {} "
        "if the chosen candidate has no required_params. \"reasoning\" is "
        "one plain-language sentence, written for the person who asked the "
        "question, explaining why you picked this source and this shape for "
        "it specifically — not a restatement of these instructions."
    )
    resp = client().models.generate_content(
        model=PLAN_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    plan = json.loads(resp.text)
    plan.setdefault("params", {})
    plan.setdefault("reasoning", "")
    return plan, _usage(resp)


def synthesize(question: str, evidence: dict, pack: str = packs.DEFAULT_PACK) -> tuple[dict, dict]:
    """SYNTHESIS_MODEL call: grounded answer + citations + presentation spec.
    Returns (presentation, usage)."""
    prompt = (
        "You are Atlas. Compose a grounded, cited answer to the user's "
        "question using ONLY the evidence provided — never invent figures. "
        f"Question: {question!r}\nEvidence: {json.dumps(evidence, default=str)}\n"
        "Choose the visualization kind that best fits the shape of the "
        "evidence (a single figure -> kpi_cards, a ranking/comparison -> "
        "bar, a time series -> line, a list of records -> table, a "
        "geographic breakdown -> map; reserve infographic for a finding a "
        "plain chart would undersell).\n\n"
        "The \"data\" field must be a JSON-encoded string using EXACTLY "
        "this shape for the chosen kind — the frontend renderer keys off "
        "these exact field names and will show nothing if they don't "
        "match:\n"
        "  table       -> [{\"<col>\": <value>, ...}, ...]\n"
        "  bar         -> {\"labels\": [string, ...], \"values\": [number, ...], \"label\": string (optional)}\n"
        "  line        -> {\"labels\": [string, ...], \"series\": [{\"name\": string, \"values\": [number, ...]}, ...]}\n"
        "  kpi_cards   -> [{\"label\": string, \"value\": string}, ...]\n"
        "  infographic -> {\"headline\": string, \"stats\": [{\"label\": string, \"value\": string}, ...], \"note\": string (optional)}\n"
        "  map         -> {\"points\": [{\"lat\": number, \"lon\": number, \"label\": string}, ...]}\n"
        "Every array named above (labels, values, series, stats, points) "
        "must be present, even if empty — never omit it."
        + packs.synthesis_rules(pack)
    )
    resp = client().models.generate_content(
        model=SYNTHESIS_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PRESENTATION_SCHEMA,
        ),
    )
    return json.loads(resp.text), _usage(resp)


def embed(text: str) -> list[float]:
    """Embedding for ARD discovery — written into ard_catalog.embeddings and
    compared at query time via BigQuery VECTOR_SEARCH."""
    resp = client().models.embed_content(
        model=os.environ.get("ATLAS_EMBED_MODEL", "text-embedding-005"),
        contents=text,
    )
    return resp.embeddings[0].values


# --- finance pack: narrative theming and claim extraction (plan-tier model) ---

THEMES_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "themes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "share_pct": {"type": "NUMBER", "description": "share of the sampled narratives this theme covers, 0-100"},
                    "summary": {"type": "STRING"},
                    "quotes": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "complaint_id": {"type": "STRING"},
                                "excerpt": {"type": "STRING", "description": "verbatim excerpt, 10-40 words, copied exactly from that complaint's narrative"},
                            },
                            "required": ["complaint_id", "excerpt"],
                        },
                    },
                },
                "required": ["name", "share_pct", "summary", "quotes"],
            },
        }
    },
    "required": ["themes"],
}


def theme_narratives(question: str, narratives: list[dict], instructions: str, max_themes: int = 6) -> tuple[dict, dict]:
    """Second step of a `bigquery_sample_llm` Attested Computation: the
    sampled narratives (already byte-capped and row-limited by the template's
    own SQL) are themed by the plan-tier model. `instructions` is the
    template's own reviewed prompt text (computation.runtime.prompt) — the
    model is told what to do by the OKF document, not by request-time text.

    Every quote must be a verbatim excerpt with the complaint_id it came
    from; pipeline.py's check stage re-verifies each one against the sample
    and drops anything that doesn't match, so a fabricated quote can never
    reach the answer. Returns ({themes: [...]}, usage)."""
    compact = [
        {"complaint_id": str(n.get("complaint_id")), "narrative": (n.get("consumer_complaint_narrative") or "")[:1200]}
        for n in narratives
    ]
    prompt = (
        "You are Atlas's narrative analyst for a finance compliance team.\n"
        f"{instructions}\n\n"
        f"Identify at most {max_themes} themes across the sampled complaint narratives below. "
        "For each theme give a short name, the approximate share of narratives it covers, a "
        "two-sentence summary, and 2-3 representative quotes. A quote MUST be copied verbatim "
        "from one narrative (10-40 words, no paraphrase, no ellipsis edits) and carry that "
        "narrative's complaint_id. Never invent a complaint_id or a quote.\n\n"
        f"Question being answered: {question!r}\n"
        f"Sampled narratives ({len(compact)}): {json.dumps(compact)}"
    )
    resp = client().models.generate_content(
        model=PLAN_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=THEMES_SCHEMA),
    )
    return json.loads(resp.text), _usage(resp)


CLAIMS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "claims": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "text": {"type": "STRING", "description": "the claim exactly as written"},
                    "entity": {"type": "STRING", "description": "company name or ticker as written, or empty"},
                    "metric": {"type": "STRING", "description": "one of the curated metric or ratio keys, or empty if none fits"},
                    "fiscal_year": {"type": "INTEGER"},
                    "claimed_value": {"type": "STRING", "description": "the number or direction claimed, as written"},
                    "claim_kind": {"type": "STRING", "enum": ["level", "growth", "ratio", "direction", "other"]},
                },
                "required": ["id", "text", "entity", "metric", "claimed_value", "claim_kind"],
            },
        }
    },
    "required": ["claims"],
}


def extract_claims(text: str, metric_keys: list[str], ratio_keys: list[str]) -> tuple[dict, dict]:
    """Fact-check step 1: split a paragraph into checkable numeric claims and
    map each to a curated metric/ratio key (or leave it empty, which becomes a
    'not verifiable' verdict — never a guess). Returns ({claims: [...]}, usage)."""
    prompt = (
        "You are Atlas's claim extractor. Split the paragraph into individual factual claims "
        "about a company's reported financials. For each claim, name the company as written, "
        "the fiscal year if stated (otherwise omit fiscal_year), the value or direction claimed, "
        "and map it to exactly one of these curated keys when one fits — otherwise leave metric "
        "empty. Do not merge two claims into one; do not invent a year.\n"
        f"Metric keys (levels): {metric_keys}\nRatio keys: {ratio_keys}\n\n"
        f"Paragraph: {text!r}"
    )
    resp = client().models.generate_content(
        model=PLAN_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=CLAIMS_SCHEMA),
    )
    return json.loads(resp.text), _usage(resp)
