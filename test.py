import requests
import json

url = "https://graph.facebook.com/v22.0/729844620223276/messages"
ACCESS_TOKEN = "EAAYtyB9hTPsBPkEQecrHNpAAmv4vGNM4xbyuZB9nl7sftURrZAItnBqMxx8RiYkqLZB3MWF7eOs2ZBOvUZBdxM6QD0kikyeYC5vOJDbVwGU9piZBiE3jt0hvu06zOjr2pa4UZARVbu2pZBnJsslZBoqskZBBsw4WbV1DcZChs3lVaNVVKacfrHerP9AvMdKeswGR2qlTrnSm60sE2aIwrAPWzzr6hXKpzts1M1DhzbjuSYv7g3x3CwZD"  # from Meta App Dashboard

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

payload = {
    "messaging_product": "whatsapp",
    "to": "919503747690",  # recipient's WhatsApp number in international format
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
