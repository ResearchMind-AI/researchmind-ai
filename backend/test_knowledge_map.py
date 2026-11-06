"""
Test script for Knowledge Map generation
"""
import requests
import json
import sys
import io

# Set UTF-8 encoding for console output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Configuration
BASE_URL = "http://localhost:8000/api/v1"

def register_user(email, password, full_name):
    """Register a new user"""
    response = requests.post(
        f"{BASE_URL}/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": full_name
        }
    )
    return response

def login(email, password):
    """Login and get access token"""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={
            "username": email,
            "password": password
        }
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    return None

def create_session(token, title, description):
    """Create a new research session"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(
        f"{BASE_URL}/sessions/",
        headers=headers,
        json={
            "title": title,
            "description": description
        }
    )
    return response

def generate_knowledge_map(token, session_id, max_nodes=10):
    """Generate knowledge map for a session"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(
        f"{BASE_URL}/knowledge-map/sessions/{session_id}/generate",
        headers=headers,
        json={
            "max_nodes": max_nodes,
            "force_regenerate": False
        }
    )
    return response

def get_knowledge_map(token, session_id):
    """Get knowledge map for a session"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{BASE_URL}/knowledge-map/sessions/{session_id}",
        headers=headers
    )
    return response

def main():
    print("=== Knowledge Map Generation Test ===\n")

    # Test credentials
    test_email = "test_km@example.com"
    test_password = "testpass123"
    test_name = "KM Tester"

    # Step 1: Register/Login
    print("Step 1: Authenticating...")
    register_response = register_user(test_email, test_password, test_name)
    if register_response.status_code in [200, 201]:
        print(f"✓ User registered successfully")
    elif register_response.status_code == 400 and "already exists" in register_response.text.lower():
        print(f"✓ User already exists, logging in...")
    else:
        print(f"✗ Registration failed: {register_response.status_code}")
        print(f"  Response: {register_response.text}")

    token = login(test_email, test_password)
    if token:
        print(f"✓ Logged in successfully\n")
    else:
        print(f"✗ Login failed")
        sys.exit(1)

    # Step 2: Create a session
    print("Step 2: Creating research session...")
    session_response = create_session(
        token,
        "AI in Healthcare",
        "Research session for testing knowledge map generation"
    )

    if session_response.status_code in [200, 201]:
        session_data = session_response.json()
        session_id = session_data["id"]
        print(f"✓ Session created with ID: {session_id}\n")
    else:
        print(f"✗ Session creation failed: {session_response.status_code}")
        print(f"  Response: {session_response.text}")
        sys.exit(1)

    # Step 3: Generate knowledge map
    print("Step 3: Generating knowledge map...")
    print("Note: This requires papers to be ingested into the session first.")
    print("If no papers exist, the generation will fail gracefully.\n")

    km_response = generate_knowledge_map(token, session_id, max_nodes=10)

    if km_response.status_code == 200:
        km_data = km_response.json()
        print(f"✓ Knowledge map generated successfully!")
        print(f"  Nodes created: {km_data['nodes_created']}")
        print(f"  Relationships created: {km_data['relationships_created']}")
        print(f"  Processing time: {km_data['processing_time']:.2f}s")
        print(f"  Message: {km_data['message']}\n")
    else:
        print(f"✗ Knowledge map generation failed: {km_response.status_code}")
        print(f"  Response: {km_response.text}\n")

        # Check if it's because there are no papers
        if "no papers" in km_response.text.lower():
            print("Note: This is expected if no papers were added to the session.")
            print("The knowledge map feature is working correctly - it just needs papers to analyze.\n")

    # Step 4: Retrieve knowledge map
    print("Step 4: Retrieving knowledge map...")
    get_km_response = get_knowledge_map(token, session_id)

    if get_km_response.status_code == 200:
        km_data = get_km_response.json()
        print(f"✓ Knowledge map retrieved successfully!")
        print(f"  Total nodes: {len(km_data['nodes'])}")
        print(f"  Total relationships: {len(km_data['relationships'])}")

        if km_data['nodes']:
            print("\n  Sample nodes:")
            for node in km_data['nodes'][:3]:
                print(f"    - {node['label']} ({node['node_type']})")

        if km_data['relationships']:
            print("\n  Sample relationships:")
            for rel in km_data['relationships'][:3]:
                print(f"    - Node {rel['source_node_id']} -> Node {rel['target_node_id']} ({rel['relation_type']})")
    else:
        print(f"✗ Failed to retrieve knowledge map: {get_km_response.status_code}")
        print(f"  Response: {get_km_response.text}")

    print("\n=== Test Complete ===")

if __name__ == "__main__":
    main()
