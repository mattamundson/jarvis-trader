from pydantic import BaseModel, ConfigDict, Field, model_validator


class MorningAlphaConfig(BaseModel):
    """Immutable v1 policy/configuration for Morning Alpha."""

    model_config = ConfigDict(frozen=True)

    account_equity: float = Field(default=3000.0, gt=0)
    default_risk_fraction: float = Field(default=0.005, gt=0, le=0.01)
    max_risk_fraction: float = Field(default=0.01, gt=0, le=0.01)
    min_expected_r: float = Field(default=2.0, ge=2.0)
    min_price: float = Field(default=10.0, gt=0)
    min_avg_daily_shares: int = Field(default=750_000, gt=0)
    min_avg_dollar_volume_20d: float = Field(default=50_000_000.0, gt=0)
    max_initial_portfolio_heat: float = Field(default=0.0125, gt=0)
    max_theme_heat: float = Field(default=0.01, gt=0)

    @model_validator(mode="after")
    def validate_risk_bounds(self) -> "MorningAlphaConfig":
        if self.default_risk_fraction > self.max_risk_fraction:
            raise ValueError("default_risk_fraction cannot exceed max_risk_fraction")
        return self
