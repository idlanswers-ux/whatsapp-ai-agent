import time
from google import genai

client = genai.Client()

print("Sending request to Gemini...")
start_time = time.time()

response = client.models.generate_content(
    model='gemini-3.6-flash',
    contents="Hi"
)

end_time = time.time()
print(f"Reply: {response.text}")
print(f"Time taken: {end_time - start_time:.2f} seconds")