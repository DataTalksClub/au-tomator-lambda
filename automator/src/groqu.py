import os
import requests


GROQ_API_KEY = os.getenv('GROQ_API_KEY')


def ai_request(prompt, model):
    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        'Authorization': f'Bearer {GROQ_API_KEY}'
    }

    ai_request = {
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "model": model,
    }

    response = requests.post(url, json=ai_request, headers=headers)
    response.raise_for_status()

    chat_completion = response.json()
    ai_response = chat_completion['choices'][0]['message']['content']
    
    return ai_response

