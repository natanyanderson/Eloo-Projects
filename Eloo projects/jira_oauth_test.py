import requests
import json

# The URL of the Flask application
url = 'http://localhost:5001/create_task'

# The JSON payload for creating a task
payload = {
    "summary": "Test Task",
    "description": "This is a test task description"
}

# The headers for the request
headers = {
    'Content-Type': 'application/json'
}

# Send the POST request
response = requests.post(url, headers=headers, data=json.dumps(payload))

# Print the response
print("Status Code:", response.status_code)
print("Response Text:", response.text)

