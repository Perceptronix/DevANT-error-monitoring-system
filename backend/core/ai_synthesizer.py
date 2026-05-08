"""
AI Synthesis Engine — LLM-powered dynamic operational reasoning.

Generates repository-specific, incident-specific analysis that:
- Explains what happened and why
- Adapts reasoning to repository type
- Provides actionable recommendations
- Uses evidence from enrichment context
- Avoids templated generic summaries

Requires GROQ_API_KEY (uses Groq for LLM inference).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from core.groq_cache import get_groq_client, is_groq_available

logger = logging.getLogger(__name__)

# Try to import Groq (for type hints)
try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False
    logger.warning("Groq not available. Synthesis will use template fallback.")


class AISynthesisEngine:
    """
    Generates dynamic, repository-specific operational analysis using LLM.
    
    Analyzes:
    - Repository type (frontend, backend, infra, ml, data)
    - Error patterns and their domain-specific meaning
    - Service topology implications
    - Deployment impact
    - Historical context and learnings
    
    Produces:
    - Narrative operational brief
    - Repository-specific reasoning
    - Actionable recommendations
    - Confidence assessments
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        # Use global cached Groq client — initializes once, reused across all requests
        self._client = get_groq_client(api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def synthesize_operational_brief(
        self,
        clusters: List[Dict[str, Any]],
        repository_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate comprehensive operational synthesis.
        
        Input:
        - clusters: enriched error clusters with context
        - repository_info: repo metadata (language, topics, size)
        
        Returns:
        {
            narrative: str,
            key_insights: [str],
            recommended_actions: [str],
            repository_specific_reasoning: str,
            confidence: float,
        }
        """
        if not clusters:
            return self._empty_synthesis()
        
        # Detect repository type
        repo_type = self._detect_repository_type(repository_info)
        
        # Generate repository-specific analysis
        if HAS_GROQ and self._client:
            try:
                # Wrap with timeout: LLM synthesis must complete in 15 seconds
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._llm_synthesis,
                        clusters,
                        repository_info,
                        repo_type,
                    ),
                    timeout=15.0,
                )
                return result
            except asyncio.TimeoutError:
                logger.warning("LLM synthesis timed out after 15s")
                return self._template_synthesis(clusters, repository_info, repo_type)
        else:
            # Fallback to template-based synthesis
            return self._template_synthesis(clusters, repository_info, repo_type)

    async def generate_root_cause_explanation(
        self,
        cluster: Dict[str, Any],
        context: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Generate detailed root cause explanation for a cluster.
        
        Uses evidence from context attachments and error patterns.
        
        Timeout: 10 seconds.
        """
        if not HAS_GROQ or not self._client:
            return cluster.get("root_cause", "Error detected")
        
        prompt = self._build_root_cause_prompt(cluster, context)
        
        try:
            # Wrap with timeout
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._call_groq,
                    prompt,
                    500,  # max_tokens
                ),
                timeout=10.0,
            )
            return response
        except asyncio.TimeoutError:
            logger.warning("Root cause generation timed out")
            return cluster.get("root_cause", "Error detected")
        except Exception as e:
            logger.warning(f"LLM root cause generation failed: {e}")
            return cluster.get("root_cause", "Error detected")

        Timeout: 8 seconds.
        """
        if not HAS_GROQ or not self._client:
            return self._default_action_recommendation(cluster, deployment_correlated)
        
        prompt = self._build_action_prompt(
            cluster,
            deployment_correlated,
            historical_similar,
        )
        
        try:
            # Wrap with timeout
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._call_groq,
                    prompt,
                    300,  # max_tokens
                ),
                timeout=8.0,
            )
            return response
        except asyncio.TimeoutError:
            logger.warning("Action recommendation timed out")
            return self._default_action_recommendation(cluster, deployment_correlated)
        except Exception as e:
            logger.warning(f"LLM action generation failed: {e}")
            return self._default_action_recommendation(cluster, deployment_correlated)lar,
        )
        
        try:
            response = await asyncio.to_thread(
                self._call_groq,
                prompt,
                max_tokens=300,
            )
            return response
        except Exception as e:
            logger.warning(f"LLM action generation failed: {e}")
            return self._default_action_recommendation(cluster, deployment_correlated)

    # ------------------------------------------------------------------
    # LLM synthesis
    # ------------------------------------------------------------------

    def _llm_synthesis(
        self,
        clusters: List[Dict[str, Any]],
        repository_info: Dict[str, Any],
        repo_type: str,
    ) -> Dict[str, Any]:
        """Call LLM for synthesis."""
        prompt = self._build_synthesis_prompt(clusters, repository_info, repo_type)
        
        try:
            response = self._call_groq(prompt, max_tokens=1500)
            
            # Try to parse structured response
            if "---" in response:
                sections = response.split("---")
                return {
                    "narrative": sections[0].strip(),
                    "key_insights": self._parse_list_section(sections[1] if len(sections) > 1 else ""),
                    "recommended_actions": self._parse_list_section(sections[2] if len(sections) > 2 else ""),
                    "repository_specific_reasoning": sections[3].strip() if len(sections) > 3 else "",
                    "confidence": min(0.95, 0.8 + (len(clusters) / 100.0)),
                }
            else:
                return {
                    "narrative": response,
                    "key_insights": [],
                    "recommended_actions": [],
                    "repository_specific_reasoning": "",
                    "confidence": 0.85,
                }
        
        except Exception as e:
            logger.warning(f"LLM synthesis failed: {e}")
            return self._template_synthesis(clusters, repository_info, repo_type)

    def _call_groq(self, prompt: str, max_tokens: int = 1000) -> str:
        """Call Groq API."""
        if not self._client:
            return "" with timeout protection."""
        if not self._client:
            return ""
        
        try:
            message = self._client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="mixtral-8x7b-32768",  # Groq model
                max_tokens=max_tokens,
                temperature=0.7,
                timeout=15.0,  # ← TIMEOUT ADDED
            )
            
            return message.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"Groq API call failed: {e}")
            return ""---------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_synthesis_prompt(
        self,
        clusters: List[Dict[str, Any]],
        repository_info: Dict[str, Any],
        repo_type: str,
    ) -> str:
        """Build prompt for comprehensive synthesis."""
        critical = [c for c in clusters if c.get("severity") in ("S1", "S2")]
        
        cluster_summary = "\n".join([
            f"- {c.get('root_cause')}: {c.get('error_count')} errors in {', '.join(c.get('affected_services', [])[:2])}"
            for c in clusters[:5]
        ])
        
        return f"""You are an expert operational reliability engineer analyzing production incidents.

Repository Type: {repo_type}
Repository Info: {json.dumps(repository_info, indent=2)[:500]}

Current Incident Clusters ({len(clusters)} total, {len(critical)} critical):
{cluster_summary}

Provide a concise operational brief that:
1. Summarizes the key operational issues
2. Explains the likely root causes with {repo_type}-specific context
3. Identifies which services are most affected
4. Rates current operational status (normal/degraded/critical)
5. Recommends specific actions

Format your response with sections separated by '---':
[Narrative brief]
---
[Key insights as bullet points]
---
[Recommended actions as bullet points]
---
[Repository-specific reasoning explaining why these errors are significant for {repo_type}]

Be concise, technical, and actionable."""

    def _build_root_cause_prompt(
        self,
        cluster: Dict[str, Any],
        context: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Build prompt for root cause explanation."""
        context_str = ""
        if context:
            context_str = "\n".join([
                f"- {c.get('title')}: {c.get('snippet', 'N/A')[:100]}"
                for c in context[:3]
            ])
        
        return f"""Analyze this production error cluster and provide a technical root cause explanation.

Error Summary:
- Root Cause: {cluster.get('root_cause')}
- Affected Services: {', '.join(cluster.get('affected_services', [])[:3])}
- Error Count: {cluster.get('error_count')}
- Severity: {cluster.get('severity')}
- Deployment Related: {cluster.get('deployment_related', False)}

Context Evidence:
{context_str}

Provide a 2-3 sentence technical explanation of what likely caused this error and why it's happening now.
Be specific and avoid generic statements."""

    def _build_action_prompt(
        self,
        cluster: Dict[str, Any],
        deployment_correlated: bool,
        historical_similar: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build prompt for action recommendation."""
        history = ""
        if historical_similar:
            history = f"\nHistorical Context: Similar incident before, resolved via: {historical_similar.get('resolution_method')}"
        
        return f"""Recommend specific operational actions for this production incident.

Issue:
- Root Cause: {cluster.get('root_cause')}
- Severity: {cluster.get('severity')}
- Affected Services: {', '.join(cluster.get('affected_services', [])[:3])}
- Deployment Related: {deployment_correlated}{history}

Provide 1-2 specific, actionable steps to investigate and resolve this incident immediately.
Format as brief action items, not general advice."""

    # ------------------------------------------------------------------
    # Template fallback
    # ------------------------------------------------------------------

    def _template_synthesis(
        self,
        clusters: List[Dict[str, Any]],
        repository_info: Dict[str, Any],
        repo_type: str,
    ) -> Dict[str, Any]:
        """Template-based synthesis (when LLM unavailable)."""
        critical = [c for c in clusters if c.get("severity") in ("S1", "S2")]
        deployment_correlated = sum(1 for c in clusters if c.get("deployment_related"))
        
        narrative = self._generate_template_narrative(
            len(clusters),
            len(critical),
            deployment_correlated,
            repo_type,
        )
        
        return {
            "narrative": narrative,
            "key_insights": [
                f"{len(clusters)} incident cluster(s) detected",
                f"{len(critical)} critical cluster(s) requiring attention",
                f"{deployment_correlated} cluster(s) correlated with deployments" if deployment_correlated else "No deployment correlation",
            ],
            "recommended_actions": [
                "Investigate critical clusters immediately",
                "Review recent deployments for correlation",
                "Check service dependencies and topology",
                "Monitor MTTR and escalation status",
            ],
            "repository_specific_reasoning": self._get_repo_specific_reasoning(repo_type),
            "confidence": 0.75,
        }

    def _generate_template_narrative(
        self,
        total_clusters: int,
        critical_count: int,
        deployment_correlation: int,
        repo_type: str,
    ) -> str:
        """Generate template narrative."""
        if critical_count >= 3:
            status = "**CRITICAL**: Multiple severe incidents detected"
        elif critical_count >= 1:
            status = "**DEGRADED**: One or more critical incident clusters"
        else:
            status = "**MONITORING**: Several incident clusters under observation"
        
        repo_context = self._get_repo_type_context(repo_type)
        
        return f"""{status} requiring investigation.

{total_clusters} incident cluster(s) identified.
{deployment_correlation} cluster(s) show deployment correlation.

{repo_context}

Recommended immediate action: Investigate critical clusters and verify deployment impact."""

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _detect_repository_type(self, repo_info: Dict[str, Any]) -> str:
        """Detect repository type from metadata."""
        language = repo_info.get("language", "").lower()
        topics = [t.lower() for t in repo_info.get("topics", [])]
        name = repo_info.get("name", "").lower()
        
        # Check language
        if language in ("typescript", "javascript", "jsx"):
            return "frontend"
        elif language in ("python", "go", "rust", "java"):
            return "backend"
        
        # Check topics
        if any(t in topics for t in ["frontend", "react", "vue", "angular"]):
            return "frontend"
        if any(t in topics for t in ["kubernetes", "infrastructure", "devops", "terraform"]):
            return "infrastructure"
        if any(t in topics for t in ["ml", "machine-learning", "data-science"]):
            return "ml"
        if any(t in topics for t in ["backend", "api", "database"]):
            return "backend"
        
        # Check name
        if any(x in name for x in ["frontend", "client", "ui", "web"]):
            return "frontend"
        if any(x in name for x in ["backend", "api", "server", "service"]):
            return "backend"
        if any(x in name for x in ["infra", "kubernetes", "devops"]):
            return "infrastructure"
        
        return "general"

    def _get_repo_type_context(self, repo_type: str) -> str:
        """Get repository-type-specific context."""
        contexts = {
            "frontend": "Frontend errors may indicate UI rendering issues, API integration problems, or browser compatibility concerns.",
            "backend": "Backend errors suggest service logic failures, database issues, or external API integration problems.",
            "infrastructure": "Infrastructure errors may indicate deployment failures, resource constraints, or service topology issues.",
            "ml": "ML errors may indicate data pipeline failures, model serving issues, or inference performance problems.",
            "data": "Data errors suggest ETL pipeline failures, data quality issues, or storage/retrieval problems.",
            "general": "Investigation should focus on service dependencies and operational impact.",
        }
        return contexts.get(repo_type, contexts["general"])

    def _get_repo_specific_reasoning(self, repo_type: str) -> str:
        """Get reasoning specific to repository type."""
        reasoning = {
            "frontend": "Frontend errors significantly impact user experience and conversion rates. Prioritize fixes for UI/navigation issues.",
            "backend": "Backend errors affect all downstream services. Prioritize fixes that restore service availability.",
            "infrastructure": "Infrastructure errors cascade to all services. Focus on deployment stability and service topology.",
            "ml": "ML errors impact prediction quality and latency. Prioritize data pipeline and model serving fixes.",
            "data": "Data errors affect all data consumers. Prioritize data quality and pipeline reliability.",
            "general": "Prioritize errors affecting multiple services or critical user workflows.",
        }
        return reasoning.get(repo_type, reasoning["general"])

    def _parse_list_section(self, section: str) -> List[str]:
        """Parse bullet point list from text."""
        lines = section.strip().split("\n")
        items = [
            line.strip("- •* ").strip()
            for line in lines
            if line.strip() and line.strip()[0] in "-•*"
        ]
        return items[:5]  # Limit to 5 items

    def _default_action_recommendation(
        self,
        cluster: Dict[str, Any],
        deployment_correlated: bool,
    ) -> str:
        """Default action recommendation without LLM."""
        severity = cluster.get("severity", "S4")
        
        if severity == "S1":
            action = "Page on-call immediately. Begin incident investigation and prepare rollback."
        elif severity == "S2":
            action = "Create incident ticket and assign to on-call engineer."
        elif severity == "S3":
            if deployment_correlated:
                action = "Investigate deployment correlation. Consider rollback if impact continues."
            else:
                action = "Monitor trend and investigate root cause."
        else:
            action = "Log for monitoring. Investigate if error count increases."
        
        return action

    def _empty_synthesis(self) -> Dict[str, Any]:
        """Return empty synthesis when no clusters."""
        return {
            "narrative": "No incidents detected. Repository operating normally.",
            "key_insights": ["No critical incidents", "No errors detected"],
            "recommended_actions": ["Continue monitoring"],
            "repository_specific_reasoning": "No operational issues requiring attention.",
            "confidence": 1.0,
        }
