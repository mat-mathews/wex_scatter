"""Quick smoke test for Gemini API access and quota."""

import sys

import google.generativeai as genai


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_gemini_access.py YOUR_API_KEY [model_name]")
        sys.exit(1)

    api_key = sys.argv[1]
    model_name = sys.argv[2] if len(sys.argv) > 2 else "gemini-2.0-flash"

    genai.configure(api_key=api_key)

    # List available models
    print("Available generative models:")
    for m in genai.list_models():
        if "generateContent" in (m.supported_generation_methods or []):
            print(f"  {m.name}")

    # Try a minimal prompt
    print(f"\nTesting {model_name}...")
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content("Reply with just the word 'ok'.")
        print(f"Response: {response.text.strip()}")
        print("Success!")
    except Exception as e:
        print(f"Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
