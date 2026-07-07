import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "jarvis-trading-493009")
DEFAULT_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
DEFAULT_MODEL_NAME = os.getenv("JARVIS_GEMINI_MODEL", "gemini-2.5-flash")


def build_prompt(ticker_symbol: str, current_price: float, close_series) -> str:
    return f"""
Act as a quantitative trading assistant.
The current price of {ticker_symbol} is ${current_price:.2f}.

Here is the closing price data for the last 5 days:
{close_series.to_string()}

Based on this specific short-term price action, provide a strict, 3-sentence technical assessment of the current momentum. Do not give financial advice, just analyze the data provided.
"""


@dataclass(slots=True)
class JarvisMarketData:
    ticker_symbol: str
    period: str
    current_price: float
    close_series: object


class YFinanceMarketDataProvider:
    """Fetch market data needed for the quick Jarvis snapshot."""

    def fetch(self, ticker_symbol: str, period: str) -> JarvisMarketData:
        try:
            import yfinance as yf
        except ModuleNotFoundError as exc:
            raise ImportError("yfinance is required for Jarvis quick analysis") from exc

        ticker = yf.Ticker(ticker_symbol)
        hist_data = ticker.history(period=period)
        if hist_data.empty or "Close" not in hist_data:
            raise ValueError(f"No market data returned for {ticker_symbol} with period={period}")

        current_price = float(hist_data["Close"].iloc[-1])
        return JarvisMarketData(
            ticker_symbol=ticker_symbol,
            period=period,
            current_price=current_price,
            close_series=hist_data["Close"],
        )


class VertexGeminiAnalysisProvider:
    """Generate Jarvis analysis text with Vertex AI Gemini."""

    def __init__(
        self,
        project_id: str = DEFAULT_PROJECT_ID,
        location: str = DEFAULT_LOCATION,
        model_name: str = DEFAULT_MODEL_NAME,
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate(self, prompt: str) -> str:
        try:
            from google import genai
        except ModuleNotFoundError as exc:
            raise ImportError("google-genai is required for Jarvis quick analysis") from exc

        client = genai.Client(
            vertexai=True,
            project=self._project_id,
            location=self._location,
        )
        response = client.models.generate_content(
            model=self._model_name,
            contents=prompt,
        )
        return (response.text or "").strip()


class JarvisAnalysisService:
    """Composable quick analysis service built from market-data and Gemini providers."""

    def __init__(
        self,
        market_data_provider: YFinanceMarketDataProvider | None = None,
        analysis_provider: VertexGeminiAnalysisProvider | None = None,
    ) -> None:
        self._market_data_provider = market_data_provider or YFinanceMarketDataProvider()
        self._analysis_provider = analysis_provider or VertexGeminiAnalysisProvider()

    @property
    def model_name(self) -> str:
        return self._analysis_provider.model_name

    def analyze(self, ticker_symbol: str = "SPY", period: str = "5d") -> str:
        market_data = self._market_data_provider.fetch(ticker_symbol, period)
        prompt = build_prompt(
            market_data.ticker_symbol,
            market_data.current_price,
            market_data.close_series,
        )
        return self._analysis_provider.generate(prompt)


_DEFAULT_SERVICE: JarvisAnalysisService | None = None


def get_default_service() -> JarvisAnalysisService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = JarvisAnalysisService()
    return _DEFAULT_SERVICE


def analyze_symbol(ticker_symbol: str = "SPY", period: str = "5d") -> str:
    """Run the default Jarvis quick analysis pipeline."""
    return get_default_service().analyze(ticker_symbol=ticker_symbol, period=period)


MODEL_NAME = DEFAULT_MODEL_NAME
