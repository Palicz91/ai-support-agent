"""
Supabase database service.
Predefined queries, dynamic SQL fallback, chat history, and logging.

CUSTOMIZE THIS FILE: Replace the example queries with ones that match your schema.
"""

import json
import re
from datetime import datetime, timedelta, timezone

from supabase import create_client, Client


class DatabaseService:
    def __init__(self, url: str, key: str):
        self.client: Client = create_client(url, key)

    # =========================================================
    # PREDEFINED QUERIES
    #
    # Add your own queries here. Each method should:
    # 1. Query one or more Supabase tables
    # 2. Return a dict with "query" (name) and "results" (data)
    #
    # These are examples - replace them with your actual schema.
    # =========================================================

    async def lookup_customer(self, search_term: str) -> dict:
        """Find a customer by name, email, or country.

        Example: lookup_customer("Acme Corp")
        """
        result = (
            self.client.table("customers")
            .select("id, name, email, phone, country, plan, status, created_at")
            .or_(
                f"name.ilike.%{search_term}%,"
                f"email.ilike.%{search_term}%,"
                f"country.ilike.%{search_term}%"
            )
            .execute()
        )
        return {"query": "lookup_customer", "results": result.data}

    async def get_customer_details(self, customer_id: str) -> dict:
        """Get full customer profile by ID."""
        result = self.client.table("customers").select("*").eq("id", customer_id).execute()
        return {"query": "get_customer_details", "results": result.data}

    async def get_customer_projects(self, customer_id: str) -> dict:
        """Get all projects for a customer."""
        result = (
            self.client.table("projects")
            .select("id, name, status, config, created_at, updated_at")
            .eq("customer_id", customer_id)
            .execute()
        )
        return {"query": "get_customer_projects", "results": result.data}

    async def get_recent_activity(self, customer_id: str, days: int = 30) -> dict:
        """Get recent activity/events for a customer."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = (
            self.client.table("events")
            .select("id, event_type, metadata, created_at")
            .eq("customer_id", customer_id)
            .gte("created_at", since)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        return {"query": "get_recent_activity", "results": result.data}

    async def get_subscription(self, customer_id: str) -> dict:
        """Get subscription details for a customer."""
        result = (
            self.client.table("subscriptions")
            .select("id, plan, status, current_period_end, canceled_at, created_at")
            .eq("customer_id", customer_id)
            .execute()
        )
        return {"query": "get_subscription", "results": result.data}

    async def count_active_customers(self, country: str = None) -> dict:
        """Count active customers, optionally by country."""
        query = self.client.table("customers").select("id, name, country", count="exact").eq("status", "active")
        if country:
            query = query.ilike("country", f"%{country}%")
        result = query.execute()
        return {"query": "count_active_customers", "results": {"count": result.count, "customers": result.data}}

    async def lookup_error_code(self, search_term: str) -> dict:
        """Look up an error code or search by error message text."""
        # Exact code match
        result = self.client.table("error_codes").select("*").eq("code", search_term.upper()).execute()
        if result.data:
            return {"query": "lookup_error_code", "results": result.data}
        # Fuzzy search
        result = (
            self.client.table("error_codes")
            .select("*")
            .or_(
                f"user_message.ilike.%{search_term}%,"
                f"internal_description.ilike.%{search_term}%,"
                f"code.ilike.%{search_term}%"
            )
            .execute()
        )
        return {"query": "lookup_error_code", "results": result.data}

    # =========================================================
    # DYNAMIC SQL FALLBACK (read-only SELECT only)
    # =========================================================

    async def run_dynamic_query(self, sql: str) -> dict:
        """Run a read-only SQL SELECT. Used as fallback when no predefined tool fits."""
        cleaned = sql.strip().upper()
        if not cleaned.startswith("SELECT"):
            return {"query": "dynamic_query", "error": "Only SELECT queries are allowed."}

        # Block mutation keywords
        blocked = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE", "EXECUTE"]
        for keyword in blocked:
            if re.search(r"\b" + keyword + r"\b", cleaned):
                return {"query": "dynamic_query", "error": f"Blocked keyword: {keyword}"}

        # Block SQL injection patterns
        if "--" in sql or "/*" in sql:
            return {"query": "dynamic_query", "error": "SQL comments not allowed."}

        sql = sql.strip().rstrip(";")

        try:
            result = self.client.rpc("run_readonly_query", {"query_text": sql}).execute()
            return {"query": "dynamic_query", "sql": sql, "results": result.data}
        except Exception as e:
            return {"query": "dynamic_query", "sql": sql, "error": str(e)}

    # =========================================================
    # CHAT HISTORY (30-minute sliding window)
    # =========================================================

    async def save_chat_message(self, telegram_user_id: int, role: str, content: str):
        self.client.table("chat_history").insert(
            {"telegram_user_id": telegram_user_id, "role": role, "content": content}
        ).execute()

    async def get_chat_history(self, telegram_user_id: int, limit: int = 10) -> list:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        result = (
            self.client.table("chat_history")
            .select("role, content, created_at")
            .eq("telegram_user_id", telegram_user_id)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return list(reversed(result.data))

    async def cleanup_old_chat_history(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        self.client.table("chat_history").delete().lt("created_at", cutoff).execute()

    # =========================================================
    # INTERACTION LOGGING
    # =========================================================

    async def log_interaction(
        self,
        telegram_user_id: int,
        user_name: str,
        question: str,
        answer: str,
        queries_run: list,
        tools_used: list,
        escalated: bool,
        escalation_reason: str = None,
        confidence: str = "high",
        response_time_ms: int = None,
    ):
        self.client.table("agent_logs").insert(
            {
                "telegram_user_id": telegram_user_id,
                "user_name": user_name,
                "question": question,
                "answer": answer,
                "queries_run": queries_run,
                "tools_used": tools_used,
                "escalated": escalated,
                "escalation_reason": escalation_reason,
                "confidence": confidence,
                "response_time_ms": response_time_ms,
            }
        ).execute()
