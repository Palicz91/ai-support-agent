"""
Gemini AI service with function calling.
Connects the AI to your database via predefined tools + dynamic SQL fallback.

CUSTOMIZE THIS FILE:
1. Update TOOL_DECLARATIONS with your query tools
2. Update SYSTEM_PROMPT with your database schema and domain knowledge
3. Update func_map in _execute_function_call to match your database.py methods
"""

import json
import base64

import google.generativeai as genai

from database import DatabaseService

# =========================================================
# TOOL DECLARATIONS
#
# Each tool maps to a method in database.py.
# Gemini decides which tool to call based on the user's question.
# =========================================================

TOOL_DECLARATIONS = [
    {
        "name": "lookup_customer",
        "description": "Search for a customer by name, email, or country. Use this first when the user mentions a specific customer.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Customer name, email, or country"},
            },
            "required": ["search_term"],
        },
    },
    {
        "name": "get_customer_details",
        "description": "Get full customer profile by ID. Use after lookup_customer.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "UUID of the customer"},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_customer_projects",
        "description": "Get all projects for a customer.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "UUID of the customer"},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_recent_activity",
        "description": "Get recent activity/events for a customer in the last N days.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "UUID of the customer"},
                "days": {"type": "integer", "description": "Number of days to look back (default 30)"},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_subscription",
        "description": "Get subscription details for a customer.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "UUID of the customer"},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "count_active_customers",
        "description": "Count active customers, optionally filtered by country.",
        "parameters": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "Country filter (optional)"},
            },
            "required": [],
        },
    },
    {
        "name": "lookup_error_code",
        "description": "Look up an error code or search error descriptions. Use when the user mentions an error code or describes an error message.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Error code (e.g. ERR_AUTH_001) or error message text"},
            },
            "required": ["search_term"],
        },
    },
    {
        "name": "run_dynamic_query",
        "description": "Run a custom read-only SQL SELECT query. ONLY use this when none of the predefined tools can answer the question.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL SELECT query (read-only, no mutations)"},
            },
            "required": ["sql"],
        },
    },
]

# =========================================================
# SYSTEM PROMPT
#
# This is the most important part to customize.
# Tell the AI about your app, database schema, and how to investigate issues.
# =========================================================

SYSTEM_PROMPT = """You are an internal support agent that helps your team diagnose and troubleshoot customer issues by querying the database. You CANNOT modify any data - only read.

## Your app
[Describe what your app does in 2-3 sentences]

## Database schema

### customers
id (uuid), name, email, phone, country, plan, status, created_at

### projects
id (uuid), customer_id -> customers.id, name, status, config (JSONB), created_at

### events
id (uuid), customer_id -> customers.id, event_type, metadata (JSONB), created_at

### subscriptions
id (uuid), customer_id -> customers.id, plan, status, current_period_end, canceled_at

### error_codes
code, component, source, trigger_condition, user_message, internal_description, severity, suggested_fix

## How to investigate
1. Start with lookup_customer to find the customer
2. Drill into relevant area (projects, events, subscription)
3. Cross-reference data between tables
4. Check error_codes if the user mentions an error
5. Provide clear diagnosis with specific data

## TIP: Table mapping
Map common questions to the correct table. For example:
- "How many subscribers?" -> subscriptions table (status = 'active'), NOT customers count
- "How many customers?" -> customers table (status = 'active')
Define your own mappings here based on your schema to avoid the AI querying the wrong table.

## Response guidelines
- Be concise and direct. Lead with the diagnosis.
- Include specific data: IDs, timestamps, counts.
- If you find the problem, explain what's wrong AND suggest how to fix it.
- If unsure, say so and rate confidence: high/medium/low.
- If code changes are needed, flag for escalation.
- ALWAYS answer in the same language the user writes in. If the user writes in Hungarian, your ENTIRE response must be in Hungarian. If English, respond in English. The database results are in English but your response language must match the user's language.
- Format responses as plain text. Do NOT use Markdown formatting (no **, no ##, no ```). Use simple line breaks and dashes for structure.
- NEVER expose secrets, tokens, or passwords.

## Escalation rules
Flag for escalation when:
- Issue requires code changes
- Cannot determine root cause
- Billing dispute or contract question
- Potential bug found (data inconsistency)
"""


class GeminiService:
    def __init__(self, api_key: str, db: DatabaseService):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",  # or "gemini-2.5-pro" for better reasoning
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            system_instruction=SYSTEM_PROMPT,
        )
        self.db = db

    async def _execute_function_call(self, function_call) -> tuple[dict, str]:
        """Execute a function call and return (result, tool_name)."""
        name = function_call.name
        args = dict(function_call.args)

        # Map tool names to database methods
        # UPDATE THIS when you add/remove tools
        func_map = {
            "lookup_customer": self.db.lookup_customer,
            "get_customer_details": self.db.get_customer_details,
            "get_customer_projects": self.db.get_customer_projects,
            "get_recent_activity": self.db.get_recent_activity,
            "get_subscription": self.db.get_subscription,
            "count_active_customers": self.db.count_active_customers,
            "lookup_error_code": self.db.lookup_error_code,
            "run_dynamic_query": self.db.run_dynamic_query,
        }

        if name in func_map:
            result = await func_map[name](**args)
            return result, name
        return {"error": f"Unknown function: {name}"}, name

    async def chat(
        self,
        message: str,
        history: list = None,
        image_bytes: bytes = None,
        image_mime: str = "image/jpeg",
    ) -> tuple[str, list[str], list[str], str]:
        """
        Send a message to Gemini with function calling and optional image.
        Returns: (response_text, queries_run, tools_used, confidence)
        """
        # Build conversation history
        contents = []
        if history:
            for msg in history:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        # Build current message (text + optional image)
        parts = []
        if image_bytes:
            parts.append({"inline_data": {"mime_type": image_mime, "data": base64.b64encode(image_bytes).decode()}})
        parts.append({"text": message})
        contents.append({"role": "user", "parts": parts})

        queries_run = []
        tools_used = []

        # Generate with function calling loop (max 8 rounds)
        response = self.model.generate_content(contents)

        for _ in range(8):
            has_fc = False
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, "function_call") and part.function_call.name:
                        has_fc = True
                        fc = part.function_call
                        result, tool_name = await self._execute_function_call(fc)
                        tools_used.append(tool_name)
                        queries_run.append(json.dumps({"tool": tool_name, "args": dict(fc.args)}))

                        # Append function call + result to conversation
                        contents.append({
                            "role": "model",
                            "parts": [{"function_call": {"name": fc.name, "args": dict(fc.args)}}],
                        })
                        contents.append({
                            "role": "user",
                            "parts": [{
                                "function_response": {
                                    "name": tool_name,
                                    "response": {"result": json.loads(json.dumps(result, default=str))},
                                }
                            }],
                        })

            if not has_fc:
                break
            response = self.model.generate_content(contents)

        # Extract text response
        response_text = ""
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    response_text += part.text

        # Detect confidence level from response text
        confidence = "high"
        low_signals = ["not sure", "unclear", "can't determine", "escalat", "don't know"]
        medium_signals = ["likely", "probably", "seems like", "appears to", "might be"]

        for signal in low_signals:
            if signal in response_text.lower():
                confidence = "low"
                break
        if confidence == "high":
            for signal in medium_signals:
                if signal in response_text.lower():
                    confidence = "medium"
                    break

        return response_text, queries_run, tools_used, confidence
