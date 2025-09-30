import requests
import json

url = "https://graph.facebook.com/v22.0/729844620223276/messages"
ACCESS_TOKEN = "EAAYtyB9hTPsBPgNnzYp5d5fs2bLbbZAbJSrQVV5Ls25P4FJVtZB6Lw3I1rTVtePAnFBdBsnWVQNonfC63RkZByDRfgEiyPZCOri4cZC2AuDAZBm4vkCvIIN6sNCdclaYk8y8FeaBXBQQeJIwc3yVFhJdv2RTplgsoa8v3PaoHc0Cib95esRJ83ZAVoAZCuSZBErv1vxrdlrHAnVMYn81BR8ZAAOVrRd2FQike9KAiRvBZBHxOwOKuAZD"  # from Meta App Dashboard

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

payload = {
    "messaging_product": "whatsapp",
    "to": "918484846888",  # recipient's WhatsApp number in international format
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
