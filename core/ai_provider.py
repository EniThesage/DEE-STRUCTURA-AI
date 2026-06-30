"""Single entry point for every AI provider call in the app.

extract_floor_plan() and ask_struxy() are the only two functions the rest of
the codebase should call — neither one's caller needs to know whether Groq or
Anthropic answered. Switching providers is a single settings.AI_PROVIDER flip
(driven by the AI_PROVIDER env var), not a code change.
"""

import base64
import json

import httpx
from anthropic import Anthropic
from django.conf import settings

GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'
ANTHROPIC_VERSION = '2023-06-01'

EXTRACTION_PROMPT = """You are analyzing an architectural floor plan image for a Nigerian construction quantity surveying app. \
Your only job is to identify actual ENCLOSED ROOMS with floor area — not every number printed on the drawing.

Return STRICT JSON only, no prose, no markdown fences, matching exactly this shape:
{
  "building_width_m": <number>,
  "building_length_m": <number>,
  "rooms": [
    {"name": "<room name>", "width_m": <number>, "length_m": <number>, "confidence": "high|medium|low"}
  ],
  "extraction_notes": "<short note, or empty string>"
}

A valid room is a space with a NAME LABEL written inside a CLOSED WALL BOUNDARY (e.g. "MASTER BEDROOM", \
"SECURITY CONTROL ROOM", "T/BATH", "KITCHEN", "CORRIDOR" only if it is actually a walled passage, not a \
distance figure). Only include spaces that satisfy both conditions: a name label AND enclosing walls.

A PORCH or covered entrance/veranda is a valid room even WITHOUT a text label — Nigerian drawings commonly \
show it only as a covered, partially-open area (e.g. hatching, a canopy/roof outline, or a recess) attached \
to the main entrance, with no name written inside it. If you see such a covered entry area with no label, \
include it as a room named "Porch" (or "Veranda" if that convention applies), using its outline to estimate \
width_m/length_m, and mark confidence "low" if its boundary is ambiguous.

A STAIRCASE / STAIRWAY is a valid room and MUST be extracted — do not treat its diagonal tread-line symbol \
(the parallel diagonal lines representing individual steps, often with an arrow showing the direction of \
travel) as structural clutter or a non-room. It is usually labeled "Stair way", "Staircase", or "Stairs"; if \
no label is present, identify it by the tread-line symbol itself and name it "Staircase". Use its full \
enclosed footprint (the wall boundary around the whole flight, including any landing) as width_m/length_m — \
the floor area it occupies in plan, not the number of steps.

Explicitly DO NOT extract these as rooms, even though they have numbers near them:
- Dimension lines / dimension annotations — the numbers (often with arrows or tick marks) that run alongside \
or between walls to indicate a measurement, distance, or setback. These describe a wall's length or a gap \
between elements, not a room's floor area.
- Structural columns, posts, piers, or gate posts — small isolated boxes (commonly square, e.g. "900x900" or \
"225x225") that are NOT enclosing any interior space, and do NOT contain a staircase's diagonal tread-line \
symbol. These are structural members, not rooms.
- Site/setback distance markers — figures showing how far a building, gate, or fence sits from a boundary \
or from another structure. These describe site layout, not a room.
- External works — gates, fences, driveways, posts, perimeter walls shown alongside or instead of a building \
interior. If the drawing is primarily external works rather than a building interior, say so in \
"extraction_notes" and only extract genuine enclosed rooms if any building interior is also shown.

Rules:
- Dimensions must be in metres.
- "confidence" reflects how legible/certain the dimension labels were in the drawing.
- If you cannot determine a dimension for a genuine room, make your best estimate and mark confidence "low".
- "extraction_notes" should briefly flag anything a human reviewer should double check — e.g. "drawing shows \
gate posts and setback distances alongside the building; these were excluded as not being rooms" — or be an \
empty string if there's nothing to flag.
- Output JSON only, no other text.
"""

STRUXY_SYSTEM_PROMPT = """You are Struxy, the Construction Advisor built into DEE STRUCTURA AI, a platform Nigerian \
civil engineers and quantity surveyors use to turn architectural floor plans into a Bill of Quantities (BOQ).

Your expertise:
- Nigerian construction practice: concrete mix ratios (e.g. 1:2:4, 1:3:6), reinforcement spacing and \
concrete cover requirements, sandcrete blockwork standards, and general Nigerian QS conventions.
- BESMM4 (Building Engineering Standard Method of Measurement) measurement conventions.
- The DEE STRUCTURA AI platform itself: how to create a project, upload a floor plan for automatic room \
extraction, run the specifications wizard, generate a BOQ, customize the letterhead, and export to \
PDF (print) or Excel.

Scope: answer general construction/QS knowledge questions and platform how-to questions. You do not \
have access to the user's current project data, so don't claim to reference specific BOQ line items, \
room data, or prices from their account — if asked about their specific project, explain that you can't \
see live project data yet and suggest where in the app to check.

Be concise and practical. Use Naira (₦) when discussing costs.
"""


class AIProviderError(Exception):
    pass


def extract_floor_plan(image_bytes, image_mime_type):
    """Returns parsed JSON: {"building_width_m", "building_length_m", "rooms": [...]}."""
    if settings.AI_PROVIDER == 'groq':
        return _extract_floor_plan_groq(image_bytes, image_mime_type)
    elif settings.AI_PROVIDER == 'anthropic':
        return _extract_floor_plan_anthropic(image_bytes, image_mime_type)
    raise AIProviderError(f'Unknown AI_PROVIDER: {settings.AI_PROVIDER}')


def ask_struxy(message, conversation_history):
    """conversation_history is a list of {'role', 'content'} dicts, oldest-first.
    Returns the assistant's reply as a plain string."""
    if settings.AI_PROVIDER == 'groq':
        return _ask_struxy_groq(message, conversation_history)
    elif settings.AI_PROVIDER == 'anthropic':
        return _ask_struxy_anthropic(message, conversation_history)
    raise AIProviderError(f'Unknown AI_PROVIDER: {settings.AI_PROVIDER}')


def _parse_extraction_json(raw_text):
    raw_text = raw_text.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AIProviderError(f'AI provider returned invalid JSON: {exc}') from exc


def _extract_floor_plan_groq(image_bytes, image_mime_type):
    if not settings.GROQ_API_KEY:
        raise AIProviderError('GROQ_API_KEY is not configured. Add it to .env to enable automatic extraction.')

    encoded = base64.standard_b64encode(image_bytes).decode('utf-8')
    payload = {
        'model': settings.GROQ_VISION_MODEL,
        'max_tokens': 2048,
        'messages': [
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': EXTRACTION_PROMPT},
                    {'type': 'image_url', 'image_url': {'url': f'data:{image_mime_type};base64,{encoded}'}},
                ],
            }
        ],
    }
    try:
        response = httpx.post(
            GROQ_API_URL,
            json=payload,
            headers={'Authorization': f'Bearer {settings.GROQ_API_KEY}'},
            timeout=60,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AIProviderError(f'Groq request failed: {exc}') from exc

    text = response.json()['choices'][0]['message']['content']
    return _parse_extraction_json(text)


def _extract_floor_plan_anthropic(image_bytes, image_mime_type):
    if not settings.ANTHROPIC_API_KEY:
        raise AIProviderError('ANTHROPIC_API_KEY is not configured. Add it to .env to enable automatic extraction.')

    encoded = base64.standard_b64encode(image_bytes).decode('utf-8')
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=settings.ANTHROPIC_VISION_MODEL,
        max_tokens=2048,
        messages=[
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {'type': 'base64', 'media_type': image_mime_type, 'data': encoded},
                    },
                    {'type': 'text', 'text': EXTRACTION_PROMPT},
                ],
            }
        ],
    )
    return _parse_extraction_json(response.content[0].text)


def _ask_struxy_groq(message, conversation_history):
    if not settings.GROQ_API_KEY:
        raise AIProviderError('GROQ_API_KEY is not configured. Add it to .env to enable Struxy.')

    messages = [{'role': 'system', 'content': STRUXY_SYSTEM_PROMPT}]
    messages.extend(conversation_history)
    messages.append({'role': 'user', 'content': message})

    payload = {'model': settings.GROQ_CHAT_MODEL, 'max_tokens': 1024, 'messages': messages}
    try:
        response = httpx.post(
            GROQ_API_URL,
            json=payload,
            headers={'Authorization': f'Bearer {settings.GROQ_API_KEY}'},
            timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AIProviderError(f'Groq request failed: {exc}') from exc

    return response.json()['choices'][0]['message']['content'].strip()


def _ask_struxy_anthropic(message, conversation_history):
    if not settings.ANTHROPIC_API_KEY:
        raise AIProviderError('ANTHROPIC_API_KEY is not configured. Add it to .env to enable Struxy.')

    messages = list(conversation_history)
    messages.append({'role': 'user', 'content': message})

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=settings.ANTHROPIC_CHAT_MODEL,
        max_tokens=1024,
        system=STRUXY_SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text.strip()
