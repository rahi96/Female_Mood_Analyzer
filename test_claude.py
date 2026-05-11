from ai.config import settings
import anthropic

def test_claude():
    if not settings.CLAUDE_API_KEY or settings.CLAUDE_API_KEY == "sk-ant-xxxxx":
        print("Error: CLAUDE_API_KEY is not set in .env")
        return

    client = anthropic.Anthropic(api_key=settings.CLAUDE_API_KEY)

    try:
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=50,
            messages=[{"role": "user", "content": "Say hello in one word."}]
        )
        print(f"Success! Model: {settings.CLAUDE_MODEL}")
        print(f"Response: {response.content[0].text}")
    except anthropic.AuthenticationError as e:
        print(f"Auth Error: Invalid API key. {e}")
    except anthropic.NotFoundError as e:
        print(f"Model Error: {settings.CLAUDE_MODEL} not found. {e}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    test_claude()
