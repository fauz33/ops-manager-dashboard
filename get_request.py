# data_functions.py
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime, timezone
import pandas as pd

def get_organization_list(domain_url, public_key, private_key):
    try:
        resp = requests.get(f"{domain_url}/api/public/v1.0/orgs?pretty=true", headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        }, auth=HTTPDigestAuth(public_key, private_key))
        resp.raise_for_status()
        data = resp.json()
        return [{"org_name": item['name'], "org_id": item['id']} for item in data['results'] if not item['isDeleted']]
    except:
        return []

def get_project_list(domain_url, public_key, private_key, org_obj):
    try:
        resp = requests.get(f"{domain_url}/api/public/v1.0/orgs/{org_obj['org_id']}/groups?pretty=true", headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        }, auth=HTTPDigestAuth(public_key, private_key))
        resp.raise_for_status()
        data = resp.json()
        org_obj['projects'] = [{"project_name": r['name'], "project_id": r['id']} for r in data.get('results', [])]
        return org_obj
    except:
        return None

def get_clusters(domain_url, public_key, private_key, project_id):
    try:
        resp = requests.get(f"{domain_url}/api/public/v1.0/groups/{project_id}/clusters?pretty=true", headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        }, auth=HTTPDigestAuth(public_key, private_key))
        resp.raise_for_status()
        clusters = resp.json().get("results", [])
        return [cluster for cluster in clusters if 'shardName' not in cluster]
    except:
        return []

def get_backup_config(domain_url, public_key, private_key, project_id, cluster_id):
    try:
        resp = requests.get(f"{domain_url}/api/public/v1.0/groups/{project_id}/backupConfigs/{cluster_id}?pretty=true", headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        }, auth=HTTPDigestAuth(public_key, private_key))
        if resp.status_code == 200:
            data = resp.json()
            return {
                'username': data.get("username"),
                'backup_status': data.get("statusName"),
                'encryption_enabled': data.get("encryptionEnabled"),
                'ssl_enabled': data.get("sslEnabled")
            }
        else:
            return None
    except:
        return None

def get_status_from_last_ping(last_ping_str):
    if not last_ping_str:
        return None
    try:
        last_ping_time_naive = datetime.strptime(last_ping_str, '%Y-%m-%dT%H:%M:%SZ')
        last_ping_time = last_ping_time_naive.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - last_ping_time
        total_seconds = diff.total_seconds()
        if total_seconds > 86400:
            days = int(total_seconds // 86400)
            return f"{days} days"
        elif total_seconds > 3600:
            hours = int(total_seconds // 3600)
            return f"{hours} hours"
        elif total_seconds > 60:
            minutes = int(total_seconds // 60)
            return f"{minutes} minutes"
        else:
            seconds = int(total_seconds)
            return f"{seconds} seconds"
    except:
        return None

def create_project_dataframe(all_clusters_data, domain_url=None):
    rows = []
    for cluster in all_clusters_data:
        rs_name = cluster['replica_set_name']
        backup_info = cluster['backup_info']
        last_heartbeat = get_status_from_last_ping(cluster['last_heartbeat'])
        ops_manager_domain = domain_url.replace('https://', '').replace('http://', '') if domain_url else ''
        if backup_info:
            rows.append({
                'Replica Set Name': rs_name,
                'Ops Manager': ops_manager_domain,
                'Username': backup_info['username'],
                'Last Ping': last_heartbeat,
                'Backup Status': backup_info['backup_status']
            })
    return pd.DataFrame(rows)

def gather_data_for_credentials(domain_url, public_key, private_key):
    all_projects_data = []

    org_list = get_organization_list(domain_url, public_key, private_key)
    for org in org_list:
        org = get_project_list(domain_url, public_key, private_key, org)
        if not org:
            continue
        for project in org['projects']:
            project_id = project['project_id']
            project_name = project['project_name']
            clusters = get_clusters(domain_url, public_key, private_key, project_id)
            all_clusters_data = []

            for cluster in clusters:
                cluster_id = cluster['id']
                rs_name = cluster.get('replicaSetName') or cluster.get('clusterName')
                last_heartbeat = cluster.get('lastHeartbeat', None)
                backup_info = get_backup_config(domain_url, public_key, private_key, project_id, cluster_id)
                all_clusters_data.append({
                    'cluster_id': cluster_id,
                    'replica_set_name': rs_name,
                    'last_heartbeat': last_heartbeat,
                    'backup_info': backup_info
                })

            df = create_project_dataframe(all_clusters_data, domain_url)
            df['Project'] = project_name
            cols = ['Project'] + [col for col in df.columns if col != 'Project']
            df = df[cols]
            all_projects_data.append(df)

    if all_projects_data:
        combined_df = pd.concat(all_projects_data, ignore_index=True)
        return combined_df.to_dict(orient='records')
    return []

