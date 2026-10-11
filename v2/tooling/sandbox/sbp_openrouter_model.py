"""mini-swe-agent model class, uploaded into the agent sandbox by locked_mini_swe.py.

Same as the stock LiteLLM model, except each call's cost is what OpenRouter actually billed (``usage.cost``)
instead of a LiteLLM price-table lookup. OpenRouter can route a model to providers with very different prices,
so this keeps mini-swe-agent's cost_limit exact. Falls back to the price table if a response has no cost.
"""
from minisweagent.models.litellm_model import LitellmModel


class OpenRouterCostLitellmModel(LitellmModel):
    def _calculate_cost(self, response) -> dict[str, float]:
        usage = getattr(response, "usage", None)
        cost = getattr(usage, "cost", None)
        if cost is None and usage is not None and hasattr(usage, "model_dump"):
            cost = usage.model_dump().get("cost")
        if cost:
            return {"cost": float(cost)}
        return super()._calculate_cost(response)
