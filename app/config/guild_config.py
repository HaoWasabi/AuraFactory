"""Guild-level configuration."""

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class GuildConfig:
    """Configuration for a single Discord guild."""

    guild_id: str
    name: str
    budget_daily_usd: float = 5.0
    rate_limit_per_min: int = 30
    features: Dict[str, Any] = field(default_factory=dict)

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if a specific feature is enabled for this guild."""
        return self.features.get(feature_name, False)
