import json
import logging
from typing import Dict, Any

from groq import Groq
from config import get_config

logger = logging.getLogger(__name__)

class SynthesisEngine:
    """
    AI Synthesis Engine responsible for converting raw operational signals and 
    pipeline evidence into human-readable operational reasoning.
    """
    
    def __init__(self):
        self.config = get_config()
        self.client = None
        if self.config.groq.is_configured:
            try:
                self.client = Groq(api_key=self.config.groq.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")

    def synthesize(self, evidence: Dict[str, Any], topology: Dict[str, Any], scores: Dict[str, Any], propagation: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Synthesize raw evidence into a human-readable operational brief.
        """
        if not self.client:
            return self._fallback_synthesis(scores)

        system_prompt = """You are an AI operational reliability analyst.
Your job is to analyze repository operational maturity, explain risks simply, explain uncertainty honestly, and recommend improvements.
Avoid hallucinations, avoid fake confidence, and prioritize operational meaning.

CRITICAL RULES:
- ALL OUTPUT MUST BE human-readable, operationally useful, plain English, concise, and professional.
- Use non-technical language when possible.
- NEVER output raw JSON payloads (other than the required structure), backend objects, internal engine terminology, raw signal dumps, or infrastructure jargon overload.
- Explain WHY confidence is low if applicable (e.g., "Confidence is limited because...").
- Recommended actions must be actionable next steps (e.g., "Add monitoring instrumentation").

OUTPUT FORMAT:
You MUST return ONLY a valid JSON object matching this schema exactly:
{
  "operational_summary": "A concise paragraph summarizing the operational state.",
  "main_risks": ["Risk 1", "Risk 2"],
  "recommended_actions": ["Action 1", "Action 2"],
  "confidence_explanation": "Explain why the system confidence score is what it is.",
  "final_assessment": "A brief final concluding sentence.",
  "severity": "low, medium, high, or critical",
  "health_state": "Healthy, Degraded, Vulnerable, or Unknown",
  "human_summary": "A 1-2 sentence high-level executive summary."
}
"""
        
        # Prepare the input payload, stripping heavy content to fit in context window
        minimal_evidence = {
            "services": len(evidence.get("services", [])),
            "workflows": len(evidence.get("workflows", [])),
            "dockerfiles": len(evidence.get("dockerfiles", [])),
            "k8s_manifests": len(evidence.get("kubernetes_manifests", [])),
            "helm_charts": len(evidence.get("helm_charts", [])),
            "terraform": len(evidence.get("terraform", [])),
            "prometheus": evidence.get("prometheus", False),
            "otel": evidence.get("otel", False),
        }
        
        minimal_topology = {
            "service_count": len(topology.get("services", [])),
            "edge_count": len(topology.get("edges", [])),
        }

        user_content = json.dumps({
            "evidence": minimal_evidence,
            "topology": minimal_topology,
            "scores": scores,
            "propagation": propagation or {}
        })

        try:
            response = self.client.chat.completions.create(
                model=self.config.groq.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=1024
            )
            
            content = response.choices[0].message.content
            return json.loads(content)
            
        except Exception as e:
            logger.error(f"Synthesis engine failed during Groq completion: {e}")
            return self._fallback_synthesis(scores)

    def _fallback_synthesis(self, scores: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback when Groq is unavailable or fails."""
        confidence = scores.get('operational_confidence', 0.0)
        risk = scores.get('regression_risk', 0.0)
        
        health_state = "Healthy"
        if risk > 0.7:
            health_state = "Vulnerable"
        elif risk > 0.4:
            health_state = "Degraded"
            
        severity = "low"
        if risk > 0.7:
            severity = "high"
        elif risk > 0.4:
            severity = "medium"
            
        return {
            "operational_summary": "The AI synthesis engine is currently offline. Basic heuristic scores are displayed.",
            "main_risks": ["Unable to generate AI-driven risk assessment due to offline synthesis engine."],
            "recommended_actions": ["Verify Groq API key configuration in the environment."],
            "confidence_explanation": f"Confidence is computed heuristically at {int(confidence*100)}% due to missing AI layer.",
            "final_assessment": "Basic checks completed without deep AI synthesis.",
            "severity": severity,
            "health_state": health_state,
            "human_summary": "Operational analysis completed using fallback heuristics."
        }
