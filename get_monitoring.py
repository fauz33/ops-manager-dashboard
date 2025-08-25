# monitoring_functions.py
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime, timezone
import pandas as pd
import concurrent.futures

def get_headers():
    return {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

def get_hosts_for_cluster(domain_url, public_key, private_key, project_id, cluster_id):
    """Get all host IDs for a specific cluster"""
    try:
        resp = requests.get(f"{domain_url}/api/public/v1.0/groups/{project_id}/hosts?clusterId={cluster_id}", 
                           headers=get_headers(), 
                           auth=HTTPDigestAuth(public_key, private_key))
        resp.raise_for_status()
        data = resp.json()
        return [host.get("id") for host in data.get("results", [])]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching hosts for cluster {cluster_id}: {e}")
        return []

def get_host_details(domain_url, public_key, private_key, project_id, host_id):
    """Get detailed information for a specific host"""
    try:
        resp = requests.get(f"{domain_url}/api/public/v1.0/groups/{project_id}/hosts/{host_id}", 
                           headers=get_headers(), 
                           auth=HTTPDigestAuth(public_key, private_key))
        resp.raise_for_status()
        data = resp.json()
        return {
            'hostname': data.get("hostname"),
            'port': data.get("port"),
            'username': data.get("username"),
            'replicaSetName': data.get("replicaSetName"),
            'lastPing': data.get("lastPing")
        }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching host details for {host_id}: {e}")
        return None

def get_status_from_last_ping(last_ping_str):
    """Convert last ping timestamp to readable status"""
    if not last_ping_str:
        return "Never"
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
    except ValueError as e:
        print(f"Error parsing timestamp {last_ping_str}: {e}")
        return "Unknown"

def create_monitoring_dataframe(all_clusters_data, domain_url=None):
    """Create a DataFrame from monitoring cluster data"""
    rows = []
    ops_manager_domain = domain_url.replace('https://', '').replace('http://', '') if domain_url else ''
    
    for cluster in all_clusters_data:
        rs_name = cluster['replica_set_name']
        for host in cluster['hosts']:
            last_ping = get_status_from_last_ping(host['lastPing'])
            rs_name_combined = rs_name
            
            # Combine replica set names if different
            if host['replicaSetName'] and rs_name != host['replicaSetName']:
                rs_name_combined = f"{rs_name}-{host['replicaSetName']}"
            
            rows.append({
                'Ops Manager': ops_manager_domain,
                'Replica Set Name': rs_name_combined,
                'Hostname:Port': f"{host['hostname']}:{host['port']}" if host['hostname'] and host['port'] else 'Unknown',
                'Username': host['username'],
                'Last Ping': last_ping
            })
    
    return pd.DataFrame(rows)

def fetch_host_detail_with_timeout(args):
    """Wrapper function for concurrent host detail fetching"""
    return get_host_details(*args)

def gather_monitoring_data_for_credentials(domain_url, public_key, private_key, max_workers=3):
    """
    Gather monitoring user data for all projects in an Ops Manager instance
    
    Args:
        domain_url: The Ops Manager URL
        public_key: API public key
        private_key: API private key
        max_workers: Maximum concurrent workers for API calls
    
    Returns:
        List of dictionaries containing monitoring data
    """
    # Import here to avoid circular imports
    from get_request import get_organization_list, get_project_list, get_clusters
    
    all_projects_data = []

    try:
        # Get all organizations
        org_list = get_organization_list(domain_url, public_key, private_key)
        
        for org in org_list:
            # Get projects for each organization
            org = get_project_list(domain_url, public_key, private_key, org)
            if not org:
                continue
                
            for project in org['projects']:
                project_id = project['project_id']
                project_name = project['project_name']
                print(f"Processing monitoring data for project: {project_name} (ID: {project_id})")
                
                # Get clusters for this project
                clusters = get_clusters(domain_url, public_key, private_key, project_id)
                all_clusters_data = []

                for cluster in clusters:
                    cluster_id = cluster['id']
                    rs_name = cluster.get('replicaSetName') or cluster.get('clusterName')
                    
                    # Get host IDs for this cluster
                    host_ids = get_hosts_for_cluster(domain_url, public_key, private_key, project_id, cluster_id)
                    
                    if host_ids:
                        # Fetch host details concurrently
                        hosts_info = []
                        if max_workers > 1:
                            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                                args_list = [(domain_url, public_key, private_key, project_id, host_id) 
                                           for host_id in host_ids]
                                hosts_info = list(executor.map(fetch_host_detail_with_timeout, args_list))
                        else:
                            # Sequential processing
                            for host_id in host_ids:
                                host_detail = get_host_details(domain_url, public_key, private_key, project_id, host_id)
                                if host_detail:
                                    hosts_info.append(host_detail)
                        
                        # Filter out None results
                        hosts_info = [host for host in hosts_info if host is not None]
                        
                        if hosts_info:
                            all_clusters_data.append({
                                'cluster_id': cluster_id,
                                'replica_set_name': rs_name,
                                'hosts': hosts_info
                            })

                if all_clusters_data:
                    # Create DataFrame for this project
                    df = create_monitoring_dataframe(all_clusters_data, domain_url)
                    df['Project'] = project_name
                    
                    # Reorder columns to put Project first
                    cols = ['Project'] + [col for col in df.columns if col != 'Project']
                    df = df[cols]
                    all_projects_data.append(df)

    except Exception as e:
        print(f"Error gathering monitoring data for {domain_url}: {e}")
        return []

    # Combine all project data
    if all_projects_data:
        combined_df = pd.concat(all_projects_data, ignore_index=True)
        return combined_df.to_dict(orient='records')
    
    return []

def create_monitoring_cache_data(ops_managers_list, max_workers=3):
    """
    Create monitoring cache data for multiple Ops Manager instances
    
    Args:
        ops_managers_list: List of Ops Manager configurations
        max_workers: Maximum concurrent workers for API calls
    
    Returns:
        Dictionary with domain URLs as keys and monitoring data as values
    """
    results = {}
    
    for ops_manager in ops_managers_list:
        domain_url = ops_manager['url']
        public_key = ops_manager['public_key']
        private_key = ops_manager['private_key']
        
        print(f"Gathering monitoring data for {domain_url}...")
        data = gather_monitoring_data_for_credentials(domain_url, public_key, private_key, max_workers)
        
        if data:
            results[domain_url] = data
            print(f"Successfully gathered {len(data)} monitoring records for {domain_url}")
        else:
            print(f"No monitoring data found for {domain_url}")
    
    return results