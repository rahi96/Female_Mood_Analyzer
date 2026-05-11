class LLMResponseParser:
    @staticmethod
    def extract_text(response) -> str:
        if not response.content:
            return ""
        blocks = []
        for block in response.content:
            if hasattr(block, "text"):
                blocks.append(block.text)
        return "\n".join(blocks)

    @staticmethod
    def get_usage(response) -> dict:
        usage = response.usage
        return {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }

    @staticmethod
    def is_stop(response) -> bool:
        return response.stop_reason in ("end_turn", "stop_sequence")
