"""
JARVIS TRADER — Pattern Vision Analyst Agent (Phase 3.7)
========================================================
Captures TradingView chart snapshots and uses multi-modal LLMs (Claude Vision)
to visually confirm technical setups.

Provides a "third-eye" verification of patterns like Head & Shoulders,
Channels, and Harmonic structures.
"""

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from llm.client import JarvisLLMClient
from llm.model_router import MODEL_SONNET, route_task

try:
    from playwright.async_api import async_playwright

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger("jarvis_trader.agents.vision")

_VISION_PROMPT = """
You are a master technical analyst. Review the provided chart for {symbol}.
Identify the most significant price action features and patterns.

Verify:
1. Are there any clean classic patterns (Head & Shoulders, Double Top/Bottom, Triangles, Flags)?
2. Is price currently at a major Support or Resistance level?
3. Does the visual structure support a {bias} trade?
4. Are there any "traps" or "ugly" price action that should cause caution?

Return your response in valid JSON format:
{{
    "visual_verdict": "CONFIRMED" | "CAUTION" | "REJECTED",
    "patterns_detected": ["<pattern 1>", "<pattern 2>"],
    "support_resistance": "<description>",
    "structural_integrity": <float 0-1>,
    "reasoning": "<2-3 sentence visual assessment>"
}}
"""


class PatternVisionAnalystAgent:
    def __init__(self, llm_client=None):
        self.llm = llm_client or JarvisLLMClient()
        self.model = route_task("vision", default_model=MODEL_SONNET)
        self.screenshot_dir = Path("data/screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def capture_chart(self, symbol: str) -> Optional[str]:
        """
        Navigate to TradingView and capture a screenshot of the chart.
        Returns the absolute path to the screenshot.
        """
        if not _PLAYWRIGHT_AVAILABLE:
            logger.warning(
                "[Vision] playwright not installed — chart capture unavailable; run: pip install playwright && playwright install chromium"
            )
            return None

        logger.info(f"[Vision] Capturing chart for {symbol}...")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1920, "height": 1080})

                # TradingView Chart URL
                # Note: This is a public URL. In production, we might use a saved layout URL.
                url = f"https://www.tradingview.com/chart/?symbol={symbol}"
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Wait for chart to stabilize
                await asyncio.sleep(5)

                # Hide popups if possible (Best effort)
                try:
                    await page.click("button[aria-label='Close']", timeout=2000)
                except Exception:
                    pass

                path = self.screenshot_dir / f"{symbol}_{int(asyncio.get_event_loop().time())}.png"
                await page.screenshot(path=str(path))
                await browser.close()

                logger.info(f"[Vision] Screenshot saved to {path}")
                return str(path)
        except Exception as e:
            logger.error(f"[Vision] Capture failed for {symbol}: {e}")
            return None

    async def analyze(self, symbol: str, bias: str = "NEUTRAL") -> Dict[str, Any]:
        """
        Perform visual analysis of the chart.
        """
        img_path = await self.capture_chart(symbol)
        if not img_path:
            return {
                "visual_verdict": "CAUTION",
                "reasoning": "Visual capture failed. Proceeding with deterministic data only.",
                "data_quality": "unavailable",
            }

        try:
            # 1. Encode image
            with open(img_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")

            # 2. Call LLM with Vision
            # Note: JarvisLLMClient needs to support multi-modal messages.
            # We assume it follows the standard Claude message format.
            prompt = _VISION_PROMPT.format(symbol=symbol, bias=bias)

            # Construct multi-modal message
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": encoded_string,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ]

            llm_result = await self.llm.call(
                model=self.model,
                system="You are a senior technical analyst with expert chart pattern recognition skills.",
                messages=messages,
                max_tokens=1000,
                agent_name="pattern_vision",
            )

            if not llm_result.success:
                raise RuntimeError(llm_result.error)

            import json

            result_text = llm_result.content.strip()

            # Extract JSON block
            start = result_text.find("{")
            end = result_text.rfind("}") + 1
            if start != -1 and end > start:
                parsed = json.loads(result_text[start:end])
                logger.info(
                    f"[Vision] Analysis complete for {symbol}: {parsed.get('visual_verdict')}"
                )
                return parsed
            else:
                raise ValueError("No JSON found in vision response")

        except Exception as e:
            logger.error(f"[Vision] Analysis failed for {symbol}: {e}")
            return {"error": str(e), "visual_verdict": "CAUTION"}
