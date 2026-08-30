"""
Vertex AI Gemini wrapper.

Replaces Resource Raiser's provider-agnostic llm.py (OpenAI / Gemini API key /
Azure OpenAI) with a single, direct Vertex AI integration authenticated by the
Cloud Run service account — no API keys anywhere in this codebase.

Two model tiers, matching the plan:
  - PLAN_MODEL:    fast classification / question-shape / SQL drafting
  - SYNTHESIS_MODEL: narrative answer + citations + presentation spec

Model names are read from env so they can be bumped (e.g. Gemini 3.x) without
a code change once a new tier is GA on Vertex AI.
"""
import os
import json
from google import genai
from google.genai import types

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


def classify_and_plan(question: str, candidates: list[dict]) -> dict:
    """PLAN_MODEL call: question shape + source routing + optional SQL draft."""
    prompt = (
        "You are Atlas's query planner. Given a user question and a list of "
        "candidate data sources (each already ARD-matched by embedding "
        "similarity), decide the question shape (point, ranking, aggregate, "
        "trend, status) and which single candidate best answers it. "
        f"Question: {question!r}\nCandidates: {json.dumps(candidates)}\n"
        "Respond as JSON: {\"shape\": str, \"source_id\": str, \"needs_sql\": bool}."
    )
    resp = client().models.generate_content(
        model=PLAN_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return json.loads(resp.text)


def synthesize(question: str, evidence: dict) -> dict:
    """SYNTHESIS_MODEL call: grounded answer + citations + presentation spec."""
    prompt = (
        "You are Atlas. Compose a grounded, cited answer to the user's "
        "question using ONLY the evidence provided — never invent figures. "
        f"Question: {question!r}\nEvidence: {json.dumps(evidence)}\n"
        "Choose the visualization kind that best fits the shape of the "
        "evidence (a single figure -> kpi_cards, a ranking/comparison -> "
        "bar, a time series -> line, a list of records -> table, a "
        "geographic breakdown -> map; reserve infographic for a finding a "
        "plain chart would undersell)."
    )
    resp = client().models.generate_content(
        model=SYNTHESIS_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PRESENTATION_SCHEMA,
        ),
    )
    return json.loads(resp.text)


def embed(text: str) -> list[float]:
    """Embedding for ARD discovery — written into ard_catalog.embeddings and
    compared at query time via BigQuery VECTOR_SEARCH."""
    resp = client().models.embed_content(
        model=os.environ.get("ATLAS_EMBED_MODEL", "text-embedding-005"),
        contents=text,
    )
    return resp.embeddings[0].values
