import requests
import json

url = "https://graph.facebook.com/v22.0/729844620223276/messages"
ACCESS_TOKEN = "EAAYtyB9hTPsBPtJDJlWIKVAUDZAUXedhocIFduHHGY3sbnns0yP9NGNGBS8A3Jz1wJn7c3YjunespGydPY2VezZAY8DuL1bAihZCvZCv0YXznUxw0USaZBfByrA3mzB8MtVxUgGff1FCZAjy38Ynj0dSZAzLotfKUNcswscOUBmNqNem2YsPRpryFQrxYFZB1YIupzwNcZClxkLwi67NH6l2whnDbF3qqYnyd0fMXSg4HZBfcaiAZDZD"  # from Meta App Dashboard

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

payload = {
    "messaging_product": "whatsapp",
    "to": "918459644404",  # recipient's WhatsApp number in international format
    "type": "template",
    "template": {
        "name": "hello_world",   # must exist in your WhatsApp template library
        "language": {
            "code": "en_US"
        }
    }
}

response = requests.post(url, headers=headers, data=json.dumps(payload))

print("Status Code:", response.status_code)
print("Response:", response.json())
