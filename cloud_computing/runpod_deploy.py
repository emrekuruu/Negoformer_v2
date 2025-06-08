#!/usr/bin/env python3
"""
Cleaned and modernized RunPod deployment script for Negoformer data collection.
Deploys one CPU pod per domain using the 'cpu5c-4-8' compute-oriented instance type.
"""

import os
import time
from typing import List, Dict
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

# Config
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY")
DOCKER_IMAGE = os.getenv("DOCKER_IMAGE", "emrekuruu/negoformer-data_collection:latest")
INSTANCE_ID = os.getenv("INSTANCE_ID", "cpu5c-4-8")
CONTAINER_DISK = int(os.getenv("CONTAINER_DISK", 20))

AWS_CONFIG = {
    "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID"),
    "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY"),
    "AWS_S3_BUCKET_NAME": os.getenv("AWS_S3_BUCKET_NAME"),
    "AWS_DEFAULT_REGION": os.getenv("AWS_DEFAULT_REGION")
}

def get_all_domains() -> List[str]:
    return  ['14']

def create_pod_for_domain(domain: str) -> Dict:
    env_list = [
        {"key": "POD_NAME", "value": f"negoformer-{domain}"},
        {"key": "DOMAIN_NAME", "value": domain},
        {"key": "PYTHONUNBUFFERED", "value": "1"},
    ] + [
        {"key": k, "value": v} for k, v in AWS_CONFIG.items() if v
    ]

    graphql_query = {
        "query": """
        mutation CreatePod($input: deployCpuPodInput!) {
          deployCpuPod(input: $input) {
            id
            imageName
          }
        }
        """,
        "variables": {
            "input": {
                "name": f"negoformer-{domain}",
                "imageName": DOCKER_IMAGE,
                "cloudType": "SECURE",
                "instanceId": INSTANCE_ID,
                "containerDiskInGb": CONTAINER_DISK,
                "env": env_list
            }
        }
    }

    try:
        response = requests.post(
            "https://api.runpod.io/graphql",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {RUNPOD_API_KEY}"},
            json=graphql_query
        )
        data = response.json()
        pod_data = data.get("data", {}).get("deployCpuPod")

        if pod_data:
            pod_id = pod_data.get("id")
            print(f"✅ Created pod for domain {domain}: {pod_id}")
            return {"id": pod_id}
        else:
            raise Exception(data.get("errors", "Unknown error"))
    except Exception as e:
        print(f"❌ Failed to create pod for domain {domain}: {str(e)}")
        return None

def deploy_all_domains(domains: List[str] = None, batch_size: int = 2):
    if not RUNPOD_API_KEY:
        print("❌ RUNPOD_API_KEY is not set. Aborting.")
        return

    domains = domains or get_all_domains()

    print(f"🚀 Deploying {len(domains)} domains using image: {DOCKER_IMAGE}\n")

    deployed_pods = []
    for i in range(0, len(domains), batch_size):
        batch = domains[i:i + batch_size]
        print(f"📦 Batch {i // batch_size + 1}: {batch}")

        for domain in batch:
            pod_info = create_pod_for_domain(domain)
            if pod_info:
                deployed_pods.append({
                    "domain": domain,
                    "pod_id": pod_info.get("id"),
                    "status": "deploying",
                    "created_at": time.time()
                })

        if i + batch_size < len(domains):
            print("⏳ Waiting 10 seconds before next batch...")
            time.sleep(5)

    print(f"\n✅ Deployment complete. {len(deployed_pods)} pods launched.")

if __name__ == "__main__":
    deploy_all_domains()
