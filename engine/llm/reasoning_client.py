"""
JARVIS TRADER — Reasoning Chain Client (Phase 3.4)
=================================================
Two-step reasoning pattern:
1. DeepSeek-R1: explicit chain-of-thought reasoning (extracted from <think> tags)
2. Claude Sonnet: decision-making using the reasoning output

Implements the pattern from the trading-agent-reasoning-chains skill.
"""

import logging
import re
from typing import Optional, Tuple

from llm.client import JarvisLLMClient

logger = logging.getLogger("jarvis_trader.reasoning_client")

class ReasoningChainClient:
    """
    Client that pipes reasoning from a specialized reasoning model
    into a decision model.
    """

    def __init__(self, llm_client: Optional[JarvisLLMClient] = None):
        self.client = llm_client or JarvisLLMClient(api_key="") # API key read from env
        self.reasoning_model = "deepseek-reasoner"
        self.decision_model = "claude-sonnet-4-6"

    async def reason_then_decide(
        self,
        context: str,
        question: str,
        decision_prompt: str,
        agent_name: str = "unknown"
    ) -> dict:
        """
        1. Extract reasoning from DeepSeek-R1
        2. Pipe reasoning → Claude for final decision
        """
        logger.info(f"[ReasoningChain] Starting 2-step chain for {agent_name}")

        # Step 1: Reasoning
        # We ask the reasoner to simply "think about" the context and question
        reasoning_messages = [
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion:\n{question}\n\nPlease think through this situation step-by-step."}
        ]

        reasoning_result = await self.client.call(
            model=self.reasoning_model,
            system="You are a quantitative trading reasoning engine. Focus on identifying risks, hidden patterns, and confluence.",
            messages=reasoning_messages,
            max_tokens=2048,
            agent_name=f"{agent_name}_reasoner",
            temperature=0.0 # Force deterministic reasoning
        )

        if not reasoning_result.success:
            logger.warning(f"[ReasoningChain] Step 1 failed, falling back to direct decision: {reasoning_result.error}")
            reasoning = "Reasoning step failed."
        else:
            reasoning, _ = self.extract_reasoning(reasoning_result.content)

        # Step 2: Decision
        # We include the reasoning chain in the prompt for the decision model
        decision_messages = [
            {"role": "user", "content": f"Context:\n{context}\n\nOur specialized reasoning engine's analysis:\n<thought>\n{reasoning}\n</thought>\n\nFinal Question:\n{question}"}
        ]

        decision_result = await self.client.call(
            model=self.decision_model,
            system=decision_prompt,
            messages=decision_messages,
            max_tokens=1024,
            agent_name=agent_name,
            temperature=0.0
        )

        return {
            "reasoning": reasoning,
            "decision": decision_result.content if decision_result.success else "Decision failed.",
            "success": decision_result.success,
            "reasoning_model": self.reasoning_model,
            "decision_model": self.decision_model,
            "cost_usd": reasoning_result.cost_usd + decision_result.cost_usd,
            "latency_ms": reasoning_result.latency_ms + decision_result.latency_ms
        }

    @staticmethod
    def extract_reasoning(text: str) -> Tuple[str, str]:
        """
        Extract <think> content and final answer.
        """
        think_pattern = re.compile(r'<think>(.*?)</think>', re.DOTALL)
        match = think_pattern.search(text)

        if match:
            reasoning = match.group(1).strip()
            final_answer = text[match.end():].strip()
        else:
            reasoning = ""
            final_answer = text

        return reasoning, final_answer
