"""mini-swe-agent model class, uploaded into the agent sandbox by locked_mini_swe.py.

Same as the stock LiteLLM model, except each call's cost is what OpenRouter actually billed (``usage.cost``)
instead of a LiteLLM price-table lookup. OpenRouter can route a model to providers with very different prices,
so this keeps mini-swe-agent's cost_limit exact. Falls back to the price table if a response has no cost
(direct provider APIs never have one).

Some models (GPT-6.1 Sol via the OpenAI API) return their text and their tool call as two separate choices;
mini-swe-agent only reads choices[0], so the choices are merged into one.
"""
from minisweagent.models.litellm_model import LitellmModel


def merge_choices(response):
    choices = getattr(response, "choices", None) or []
    if len(choices) < 2:
        return response
    first = choices[0]
    for c in choices[1:]:
        if c.message.tool_calls:
            first.message.tool_calls = list(first.message.tool_calls or []) + list(c.message.tool_calls)
            first.finish_reason = "tool_calls"
        if c.message.content and not first.message.content:
            first.message.content = c.message.content
    response.choices = [first]
    return response


class OpenRouterCostLitellmModel(LitellmModel):
    def _query(self, messages, **kwargs):
        return merge_choices(super()._query(messages, **kwargs))

    def _calculate_cost(self, response) -> dict[str, float]:
        usage = getattr(response, "usage", None)
        cost = getattr(usage, "cost", None)
        if cost is None and usage is not None and hasattr(usage, "model_dump"):
            cost = usage.model_dump().get("cost")
        if cost is not None:  # OpenRouter's billed amount; 0 is a real (free) charge, not a missing price
            return {"cost": float(cost)}
        return super()._calculate_cost(response)
