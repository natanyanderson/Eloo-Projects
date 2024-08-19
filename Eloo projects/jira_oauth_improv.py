import requests
import json
import webbrowser
import os
from flask import Flask, request, redirect, jsonify

app = Flask(__name__)

# Replace these with actual credentials
client_id = os.getenv('JIRA_CLIENT_ID')
client_secret = os.getenv('JIRA_CLIENT_SECRET')
redirect_uri = os.getenv('JIRA_REDIRECT_URI', 'http://localhost:5001/callback')
auth_url_link = 'https://auth.atlassian.com/authorize'
token_url = 'https://auth.atlassian.com/oauth/token'
api_url = 'https://api.atlassian.com/ex/jira/{cloudid}/rest/api/3'
project_key = 'KAN'

@app.route('/')
def login():
    auth_url = (f"{auth_url_link}?audience=api.atlassian.com&client_id={client_id}"
                f"&scope=read%3Ajira-user%20read%3Ajira-work%20write%3Ajira-work&redirect_uri={redirect_uri}&response_type=code&prompt=consent")
    return redirect(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_data = {
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'client_secret': client_secret,
        'code': code,
        'redirect_uri': redirect_uri,
    }
    token_response = requests.post(token_url, data=token_data)
    tokens = token_response.json()
    # Print the token response for debugging
    # print("Token Response Status Code:", token_response.status_code)
    # print("Token Response Text:", token_response.text)
    access_token = tokens['access_token']
    cloud_id = get_cloud_id(access_token)
    tasks = get_jira_tasks(access_token, cloud_id)
    tasks_json = convert_to_json(tasks)

    # Save the tokens
    with open('tokens.json', 'w') as token_file:
        json.dump(tokens, token_file)

    return json.dumps(tasks_json, indent=4)

@app.route('/create_task', methods=['POST'])
def create_task():
    task_data = request.json

    # Validate required fields
    if not task_data.get('summary'):
        return jsonify({"error": "Task summary is required."}), 400
    if not task_data.get('description'):
        return jsonify({"error": "Task description is required."}), 400

    # Load tokens
    try:
        with open('tokens.json', 'r') as token_file:
            tokens = json.load(token_file)
        access_token = tokens['access_token']
    except (FileNotFoundError, KeyError) as e:
        return jsonify({"error": f"Token issue: {str(e)}. Please authenticate first."}), 400

    try:
        cloud_id = get_cloud_id(access_token)

        issue = {
            "fields": {
                "project": {
                    "key": project_key
                },
                "summary": task_data.get('summary'),
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": task_data.get('description')
                                }
                            ]
                        }
                    ]
                },
                "issuetype": {
                    "name": "Task"
                }
            }
        }

        create_response = requests.post(
            f"{api_url.format(cloudid=cloud_id)}/issue",
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            },
            data=json.dumps(issue)
        )

        if create_response.status_code != 201:
            return jsonify({"error": "Failed to create task in Jira", "details": create_response.text}), 400

        created_issue = create_response.json()
        created_issue_key = created_issue.get('key')

        # Verify the content of the created task
        task = get_jira_task_by_key(access_token, cloud_id, created_issue_key)
        return jsonify(task)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to create task in Jira: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500


def get_cloud_id(access_token):
    try:
        response = requests.get(
            'https://api.atlassian.com/oauth/token/accessible-resources',
            headers={'Authorization': f'Bearer {access_token}'}
        )
        response.raise_for_status()
        resources = response.json()
        if not resources:
            raise Exception("No accessible resources found for the given access token.")

        cloud_id = resources[0]['id']
        return cloud_id

    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to get cloud ID: {str(e)}")

    except (json.JSONDecodeError, IndexError) as e:
        raise Exception(f"Failed to process cloud ID response: {str(e)}")

    except Exception as e:
        raise Exception(f"An unexpected error occurred while fetching cloud ID: {str(e)}")

def get_jira_tasks(access_token, cloud_id):
    start_at = 0
    all_tasks = []
    while True:
        query = {
            'jql': f'project={project_key}',
            'startAt': start_at,
            'maxResults': 100  # Fetch 100 tasks at a time
        }
        response = requests.get(
            f"{api_url.format(cloudid=cloud_id)}/search",
            headers={'Authorization': f'Bearer {access_token}'},
            params=query
        )
        if response.status_code != 200:
            raise Exception(f"Failed to fetch data from Jira: {response.status_code} {response.text}")
        tasks = response.json()
        all_tasks.extend(tasks.get('issues', []))
        if len(tasks.get('issues', [])) < 100:
            break
        start_at += 100
    return {'issues': all_tasks}

def get_jira_task_by_key(access_token, cloud_id, task_key):
    try:
        response = requests.get(
            f"{api_url.format(cloudid=cloud_id)}/issue/{task_key}",
            headers={'Authorization': f'Bearer {access_token}'}
        )
        # raises an HTTPError if response contains an HTTP error status code
        response.raise_for_status()
        task = response.json()
        return convert_to_json({'issues': [task]})[0]

    except requests.exceptions.RequestException as e:
        # Catch any request-related errors (e.g., network issues, invalid responses)
        raise Exception(f"Failed to fetch task {task_key} from Jira: {str(e)}")

    except json.JSONDecodeError as e:
        # Handle JSON decoding errors
        raise Exception(f"Failed to decode JSON response for task {task_key}: {str(e)}")

    except Exception as e:
        # Catch any other exceptions
        raise Exception(f"An unexpected error occurred while fetching task {task_key}: {str(e)}")

def get_field(fields, field_names):
    "Return the value of the first found field from the list of possible field names"
    for field_name in field_names:
        value = fields.get(field_name)
        if value:
            return value
    return None

def convert_to_json(tasks):
    issues = tasks.get("issues", [])
    tasks_list = []
    for issue in issues:
        fields = issue.get('fields', {})
        assignee = fields.get('assignee', {})
        task_data = {
            'key': issue.get('key'),
            'summary': get_field(fields, ['summary']),
            'status': get_field(fields, ['status', 'state']).get('name') if get_field(fields, ['status', 'state']) else None,
            'assignee': get_field(assignee, ['displayName', 'display_Name']) if assignee else None,
            'created': get_field(fields, ['created']),
            'updated': get_field(fields, ['updated']),
            'description': get_field(fields, ['description', 'desc'])
        }
        tasks_list.append(task_data)
    return tasks_list

if __name__ == "__main__":
    webbrowser.open('http://localhost:5001/')
    app.run(host='0.0.0.0', port=5001, debug=True)
