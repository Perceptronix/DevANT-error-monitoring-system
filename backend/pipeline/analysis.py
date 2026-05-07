"""
LLM-powered severity analysis for error clusters.

Determines:
- Severity (S1-S4)
- Status (NEW, REGRESSION, ONGOING)
- Root cause and impact
- Whether to alert (suppression logic)
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Literal

from pydantic import BaseModel, Field

from schemas import PreviousErrorState
from state import get_state_manager
from backend.memory.hybrid_search import HybridRetriever

logger = logging.getLogger(__name__)


# Closed ticket states (case-insensitive)
CLOSED_STATES = [
    "completed", "done", "closed",
    "canceled", "cancelled",
    "finished", "resolved", "fixed", "complete",
    "wontfix", "won't fix", "wont do", "won't do",
    "rejected", "declined", "duplicate",
    "archived",
]


class ErrorAnalysis(BaseModel):
    """LLM output for error analysis."""
    severity: str = Field(description="Severity level: S1 (Critical), S2 (High), S3 (Medium), S4 (Low)")
    title: str = Field(description="Short actionable title (5-10 words) for tickets/alerts, e.g. 'Google Drive rate limits exceeded' or 'Database connection pool exhausted'")
    root_cause: str = Field(description="Brief explanation of the likely root cause")
    impact: str = Field(description="Description of the impact on users/system")
    suggested_action: str = Field(description="Recommended next steps to resolve")
    reasoning: str = Field(description="Explanation of how severity was determined")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score (0.0-1.0) for the analysis")
    evidence_count: int = Field(description="Number of evidence items used for reasoning")
    deployment_correlation: bool = Field(description="Whether a deployment correlation was found")
    historical_match: bool = Field(description="Whether historical incidents matched this one")


class ErrorAnalyzer:
    """
    Analyzes error clusters to determine severity, status, and alerting.
    
    Severity Levels:
    - S1 (Critical): Complete service outage, data loss, security breach
    - S2 (High): Major feature broken, significant user impact
    - S3 (Medium): Feature degraded, limited user impact
    - S4 (Low): Minor issue, no immediate action required
    
    Status:
    - NEW: First time seeing this error, no relevant ticket
    - REGRESSION: Error reoccurred after ticket was closed
    - ONGOING: Continues with open ticket or seen before
    
    Suppression Logic:
    - NEW → Always alert
    - REGRESSION → Always alert
    - ONGOING with open ticket → Suppress (don't spam)
    - ONGOING, alerted <24h ago → Suppress
    - S1/S2 severity → Always alert (override suppression)
    - Muted → Suppress
    """
    
    def __init__(self):
        self.last_reasoning: Optional[str] = None
        self.state = get_state_manager()
        self._init_llm()
        # Hybrid retriever for grounded operational evidence
        try:
            self.hybrid = HybridRetriever()
        except Exception:
            self.hybrid = None
    
    def _init_llm(self):
        """Initialize the LLM client."""
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        
        if anthropic_key and len(anthropic_key) > 10:  # Valid keys are much longer
            try:
                from langchain_anthropic import ChatAnthropic
                self.llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)
                self.provider = "anthropic"
                logger.info("Using Anthropic for LLM analysis")
            except Exception as e:
                logger.warning(f"Failed to initialize Anthropic: {e}")
                self.llm = None
                self.provider = None
        elif openai_key and len(openai_key) > 10:  # Valid keys are much longer
            try:
                from langchain_openai import ChatOpenAI
                self.llm = ChatOpenAI(model="gpt-4o", temperature=0)
                self.provider = "openai"
                logger.info("Using OpenAI for LLM analysis")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI: {e}")
                self.llm = None
                self.provider = None
        else:
            self.llm = None
            self.provider = None
            logger.warning("No LLM API key configured - analysis will use fallback logic")
    
    async def analyze_errors(
        self, 
        clusters: List[Dict[str, Any]], 
        context_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze each error cluster with context to determine severity.
        
        Args:
            clusters: List of error clusters from clustering step
            context_results: Context search results from Airweave
            
        Returns:
            List of analysis results per cluster
        """
        analyses = []
        all_reasoning = []
        
        # Note: context_results (legacy) may still be provided but we will
        # prefer hybrid retrieval that produces a grounded evidence bundle.
        
        for cluster in clusters:
            signature = cluster.get("signature", "")
            # Hybrid retrieval: get grounded evidence bundle
            evidence_bundle = None
            try:
                if self.hybrid:
                    evidence_bundle = await self.hybrid.retrieve(cluster)
            except Exception as e:
                logger.warning(f"Hybrid retrieval failed for {signature[:40]}: {e}")

            # If hybrid retrieval failed, fall back to legacy context mapping
            context = (evidence_bundle or {}).get("evidences") if evidence_bundle else None

            if self.llm:
                try:
                    analysis = await self._llm_analyze(cluster, evidence_bundle or {})
                except Exception as e:
                    logger.error(f"LLM analysis failed: {e}", exc_info=True)
                    analysis = self._fallback_analysis(cluster, evidence_bundle or {})
            else:
                analysis = self._fallback_analysis(cluster, evidence_bundle or {})
            
            analyses.append(analysis)
            if analysis.get("reasoning"):
                all_reasoning.append(f"[{signature[:50]}]: {analysis['reasoning']}")
        
        self.last_reasoning = "\n\n".join(all_reasoning)
        return analyses
    
    async def _llm_analyze(
        self, 
        cluster: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use LLM to analyze the error cluster."""
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import JsonOutputParser
        
        parser = JsonOutputParser(pydantic_object=ErrorAnalysis)
        
        # Build context string from grounded evidence bundle or legacy context
        context_parts = []

        # If evidence bundle produced by HybridRetriever
        if isinstance(context, dict) and context.get("evidences") is not None:
            evidences = context.get("evidences", [])
            if evidences:
                context_parts.append("**Top Evidence:**")
                for ev in evidences[:4]:
                    title = ev.get("title") or ev.get("metadata", {}).get("title", "")
                    src = ev.get("source")
                    url = ev.get("url") or ev.get("metadata", {}).get("url", "")
                    context_parts.append(f"- [{src}] {title} ({url}) Score:{ev.get('final_score', ev.get('base_score', 0)):.2f}")

            dep = context.get("deployment_correlation")
            if dep:
                context_parts.append(f"**Deployment Correlation:** matched={dep.get('matched', False)} score={dep.get('score', 0):.2f}")

            # include simple metadata
            meta = context.get("metadata") or {}
            if meta:
                context_parts.append(f"**Evidence Count:** {meta.get('evidence_count', 0)}  **Confidence:** {meta.get('confidence', 0):.2f}")

        else:
            # Legacy context format
            if context and isinstance(context, dict) and context.get("code_snippets"):
                context_parts.append("**Related Code:**")
                for snippet in context["code_snippets"][:2]:
                    context_parts.append(f"- {snippet.get('title', 'Code')}: {snippet.get('content', '')[:300]}")

            if context and isinstance(context, dict) and context.get("related_tickets"):
                context_parts.append("\n**Related Tickets:**")
                for ticket in context["related_tickets"][:2]:
                    context_parts.append(f"- {ticket.get('title', 'Ticket')}: {ticket.get('content', '')[:200]}")

        context_str = "\n".join(context_parts) if context_parts else "No additional context available."
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are analyzing production errors to determine severity and impact.

    MANDATES:
    - Do NOT invent deployments, commits, owners, metrics, or historical incidents.
    - Only use the provided, retrieved evidence and structured incident data.
    - Every factual claim MUST reference evidence by index, URL, or field from the evidence bundle.
    - If evidence is insufficient, respond with "Insufficient evidence" rather than guessing.

    Severity Guidelines (be conservative - most errors should be S3 or S4):
    - **S1 (Critical)**: Complete service outage, data loss/corruption, security breach, ALL users affected
    - **S2 (High)**: Major feature broken, significant user impact (>10% users), potential data issues
    - **S3 (Medium)**: Feature degraded, limited user impact (<10% users), workaround available
    - **S4 (Low)**: Minor issue, cosmetic, no immediate action required, single user affected

    Title Guidelines:
    - Create a short, actionable title (5-10 words) suitable for tickets and alerts
    - Focus on WHAT is happening, not the technical error class

    Output Requirements:
    - Provide a JSON object matching the required schema including `confidence`, `evidence_count`, `deployment_correlation`, and `historical_match`.
    - Include a brief `reasoning` field that cites evidence items (e.g., "evidence[0].url", "deployment_events[1]").

    {format_instructions}"""),
            ("user", """Analyze this error cluster:

    **Signature:** {signature}

    **Error Count:** {error_count}
    **Organizations Affected:** {orgs}

    **Sample Error:**
    {sample_message}

    **Evidence Bundle (do NOT invent additional facts):**
    {context}

    Determine severity, create an actionable title, identify root cause, assess impact, and suggest action. If you cannot reach a conclusion from evidence, state "Insufficient evidence" and set `confidence` accordingly.""")
        ])
        
        chain = prompt | self.llm | parser
        
        result = await chain.ainvoke({
            "format_instructions": parser.get_format_instructions(),
            "signature": cluster.get("signature", "Unknown"),
            "error_count": cluster.get("error_count", 1),
            "orgs": ", ".join(cluster.get("affected_orgs", ["Unknown"])),
            "sample_message": cluster.get("sample_message", "")[:500],
            "context": context_str,
        })
        
        analysis = ErrorAnalysis(**result)
        
        logger.info(f"Analysis for '{cluster.get('signature', '')[:50]}': {analysis.severity} - {analysis.title}")
        
        return {
            "signature": cluster.get("signature", ""),
            "severity": analysis.severity,
            "title": analysis.title,
            "root_cause": analysis.root_cause,
            "impact": analysis.impact,
            "suggested_action": analysis.suggested_action,
            "reasoning": analysis.reasoning,
            "error_count": cluster.get("error_count", 1),
            "affected_orgs": cluster.get("affected_orgs", []),
            "modules": cluster.get("modules", []),
        }
    
    def _fallback_analysis(
        self, 
        cluster: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Fallback analysis without LLM."""
        signature = cluster.get("signature", "").lower()
        error_count = cluster.get("error_count", 1)
        affected_orgs = cluster.get("affected_orgs", [])
        modules = cluster.get("modules", [])
        
        # Determine severity and generate title based on heuristics
        if any(word in signature for word in ["500", "502", "503", "outage", "down"]):
            severity = "S2"
            title = "Service errors indicating degradation"
            root_cause = "Server error indicating service degradation"
        elif any(word in signature for word in ["401", "403", "auth", "unauthorized"]):
            severity = "S3"
            if "oauth" in signature or "token" in signature or "refresh" in signature:
                title = "OAuth tokens expired - users need to reconnect"
            else:
                title = "Authentication failures with external service"
            root_cause = "Authentication or authorization failure"
        elif any(word in signature for word in ["429", "rate limit", "throttl"]):
            severity = "S3"
            if "google" in signature or "drive" in signature:
                title = "Google Drive API rate limits exceeded"
            elif "dropbox" in signature:
                title = "Dropbox API rate limits exceeded"
            elif "slack" in signature:
                title = "Slack API rate limits exceeded"
            else:
                title = "External API rate limiting errors"
            root_cause = "Rate limiting from external service"
        elif any(word in signature for word in ["timeout", "connection"]):
            severity = "S3" if error_count > 5 else "S4"
            if "database" in signature or "postgres" in signature or "pool" in signature:
                title = "Database connection issues"
            else:
                title = "Network connectivity issues"
            root_cause = "Network or connection issues"
        elif any(word in signature for word in ["pool", "exhaust"]):
            severity = "S3"
            title = "Database connection pool exhausted"
            root_cause = "Connection pool exhausted under load"
        elif any(word in signature for word in ["memory", "oom"]):
            severity = "S2"
            title = "Worker memory limit exceeded"
            root_cause = "Out of memory during processing"
        elif any(word in signature for word in ["pdf", "corrupt", "parse"]):
            severity = "S4"
            title = "Document processing failures"
            root_cause = "Unable to process corrupted or malformed files"
        else:
            severity = "S4"
            title = f"Errors in {modules[0] if modules else 'application'}"
            root_cause = "Unknown error - requires investigation"
        
        # Bump severity if many orgs affected
        if len(affected_orgs) > 3 and severity in ["S3", "S4"]:
            severity = "S2" if severity == "S3" else "S3"
        
        return {
            "signature": cluster.get("signature", ""),
            "severity": severity,
            "title": title,
            "root_cause": root_cause,
            "impact": f"Affecting {len(affected_orgs)} organization(s): {', '.join(affected_orgs[:3])}",
            "suggested_action": "Investigate error logs and implement appropriate fix",
            "reasoning": f"Fallback analysis based on error patterns. Error count: {error_count}, Orgs: {len(affected_orgs)}",
            "error_count": error_count,
            "affected_orgs": affected_orgs,
            "modules": modules,
        }
    
    # =========================================================================
    # Status Determination
    # =========================================================================
    
    def determine_status(
        self,
        signature: str,
        has_relevant_ticket: bool = False,
    ) -> tuple[Literal["NEW", "REGRESSION", "ONGOING"], PreviousErrorState]:
        """
        Determine error status based on history and ticket state.
        
        Args:
            signature: Error signature
            has_relevant_ticket: Whether a relevant ticket was found
            
        Returns:
            Tuple of (status, previous_state)
        """
        # Get previous state from storage
        prev_state = self.state.get_signature(signature)
        
        if prev_state is None:
            # Never seen before
            prev_state = PreviousErrorState(signature=signature)
            logger.info(f"[{signature[:30]}...] Status: NEW (first occurrence)")
            return "NEW", prev_state
        
        # Check for regression (ticket was closed, error came back)
        if prev_state.linear_issue_id and prev_state.linear_issue_status:
            status_lower = prev_state.linear_issue_status.lower()
            if status_lower in CLOSED_STATES:
                logger.info(
                    f"[{signature[:30]}...] Status: REGRESSION "
                    f"(ticket {prev_state.linear_issue_id} was {prev_state.linear_issue_status})"
                )
                return "REGRESSION", prev_state
        
        # Check if we have a relevant open ticket
        if has_relevant_ticket:
            logger.info(f"[{signature[:30]}...] Status: ONGOING (has relevant ticket)")
            return "ONGOING", prev_state
        
        # Seen before but no ticket
        if not prev_state.last_alerted:
            logger.info(f"[{signature[:30]}...] Status: NEW (seen but never alerted)")
            return "NEW", prev_state
        
        logger.info(f"[{signature[:30]}...] Status: ONGOING (seen before)")
        return "ONGOING", prev_state
    
    # =========================================================================
    # Suppression Logic
    # =========================================================================
    
    def should_alert(
        self,
        signature: str,
        status: Literal["NEW", "REGRESSION", "ONGOING"],
        severity: str,
        has_relevant_ticket: bool,
        prev_state: PreviousErrorState,
    ) -> tuple[bool, Optional[str]]:
        """
        Determine if we should send an alert for this error.
        
        Args:
            signature: Error signature
            status: Error status (NEW, REGRESSION, ONGOING)
            severity: Severity level (S1-S4)
            has_relevant_ticket: Whether a relevant ticket exists
            prev_state: Previous error state
            
        Returns:
            Tuple of (should_alert, suppression_reason)
        """
        # 1. Check if muted
        if self.state.is_muted(signature):
            mute_info = self.state.get_mute_info(signature)
            reason = f"Muted until {mute_info.get('muted_until', 'unknown')}"
            logger.info(f"[{signature[:30]}...] Suppressed: {reason}")
            return False, reason
        
        # 2. S1/S2 always alerts (override other suppression)
        if severity in ["S1", "S2"]:
            logger.info(f"[{signature[:30]}...] {severity} severity → always alert")
            return True, None
        
        # 3. NEW errors always alert
        if status == "NEW":
            logger.info(f"[{signature[:30]}...] NEW status → alert")
            return True, None
        
        # 4. REGRESSION always alerts
        if status == "REGRESSION":
            logger.info(f"[{signature[:30]}...] REGRESSION status → alert")
            return True, None
        
        # 5. ONGOING with open ticket → suppress
        if status == "ONGOING" and has_relevant_ticket:
            reason = "Has open ticket - suppressing to avoid spam"
            logger.info(f"[{signature[:30]}...] Suppressed: {reason}")
            return False, reason
        
        # 6. Check 24h sliding window
        if prev_state.last_alerted:
            now = datetime.now(timezone.utc)
            last_alerted = prev_state.last_alerted
            
            # Handle timezone-naive datetimes
            if last_alerted.tzinfo is None:
                last_alerted = last_alerted.replace(tzinfo=timezone.utc)
            
            time_since_alert = now - last_alerted
            if time_since_alert < timedelta(hours=24):
                hours_ago = time_since_alert.total_seconds() / 3600
                reason = f"Alerted {hours_ago:.1f}h ago (within 24h window)"
                logger.info(f"[{signature[:30]}...] Suppressed: {reason}")
                return False, reason
        
        # Default: alert
        logger.info(f"[{signature[:30]}...] No suppression rules matched → alert")
        return True, None
    
    def analyze_with_status(
        self,
        cluster: Dict[str, Any],
        context: Dict[str, Any],
        has_relevant_ticket: bool = False,
    ) -> Dict[str, Any]:
        """
        Full analysis including status determination and suppression.
        
        This is the main entry point for analysis in the enhanced pipeline.
        
        Args:
            cluster: Error cluster data
            context: Context from Airweave search
            has_relevant_ticket: Whether a matching ticket was found
            
        Returns:
            Analysis dict with status, severity, and alert decision
        """
        signature = cluster.get("signature", "")
        
        # Determine status
        status, prev_state = self.determine_status(signature, has_relevant_ticket)
        
        # Run LLM/fallback analysis for severity
        if self.llm:
            try:
                import asyncio
                analysis = asyncio.get_event_loop().run_until_complete(
                    self._llm_analyze(cluster, context)
                )
            except Exception as e:
                logger.error(f"LLM analysis failed: {e}")
                analysis = self._fallback_analysis(cluster, context)
        else:
            analysis = self._fallback_analysis(cluster, context)
        
        # Determine if we should alert
        should_alert, suppression_reason = self.should_alert(
            signature=signature,
            status=status,
            severity=analysis["severity"],
            has_relevant_ticket=has_relevant_ticket,
            prev_state=prev_state,
        )
        
        # Add status and suppression info to analysis
        analysis["status"] = status
        analysis["should_alert"] = should_alert
        analysis["suppression_reason"] = suppression_reason
        analysis["previous_state"] = prev_state.model_dump() if prev_state else None
        
        return analysis
