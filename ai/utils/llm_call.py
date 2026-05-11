from ai.utils.claude_llm import ClaudeLLM
from ai.utils.llm_response_parser import LLMResponseParser


def llm_call(
    prompt: str,
    system: str = None,
    max_tokens: int = 1024,
    temperature: float = None,
    return_usage: bool = False,
) -> str | dict:
    llm = ClaudeLLM()
    kwargs = {
        "prompt": prompt,
        "system": system,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = llm.generate(**kwargs)
    text = LLMResponseParser.extract_text(response)

    if return_usage:
        usage = LLMResponseParser.get_usage(response)
        return {"text": text, "usage": usage}
    return text
