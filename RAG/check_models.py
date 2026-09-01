"""Quick check: list all models available for your Groq API key."""
from groq import Groq

client = Groq(api_key="your_groq_api_key_here")
models = client.models.list()

print("=== Models available for your Groq key ===")
for m in sorted(models.data, key=lambda x: x.id):
    print(f"  - {m.id}")
