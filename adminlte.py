from flask import Flask, render_template, request, redirect, url_for
import os
import json
import re
from datetime import datetime
import concurrent.futures
import threading
import time
from get_request import (
    get_organization_list,
    get_project_list,
    get_clusters,
    get_backup_config,
    get_status_from_last_ping,
    gather_data_for_credentials
)
from get_monitoring import gather_monitoring_data_for_credentials

app = Flask(__name__)

def truncate_ops_manager_url(url, max_length=35):
    """Smart truncation for Ops Manager URLs to fit in filter UI"""
    if len(url) <= max_length:
        return url
    
    # Handle different URL patterns
    if '.' not in url:
        # IP addresses or simple hostnames
        return url
    
    parts = url.split('.')
    
    # AWS ELB/NLB pattern
    if 'elb.amazonaws.com' in url or 'amazonaws.com' in url:
        # Extract service identifier and region
        service_parts = parts[0].split('-')
        service_id = '-'.join(service_parts[:3]) if len(service_parts) >= 3 else parts[0]
        # Find region part
        region_part = next((part for part in parts if 'us-' in part or 'eu-' in part), parts[-3])
        return f"...{service_id}...{region_part}.amazonaws.com"
    
    # Corporate domain pattern (opsmanager.region.env.company.com)
    if len(parts) >= 4:
        # Keep environment and company parts
        important_parts = []
        for part in parts[1:]:  # Skip first part (usually 'opsmanager')
            if any(env in part for env in ['prod', 'dev', 'staging', 'test', 'non-prod']):
                important_parts.append(part)
            elif any(region in part for region in ['us-east', 'us-west', 'eu-', 'ap-']):
                important_parts.append(part)
        
        # Keep last 2 parts (company.com) and important middle parts
        if important_parts:
            result = f"...{'.'.join(important_parts)}.{parts[-2]}.{parts[-1]}"
        else:
            result = f"...{parts[-3]}.{parts[-2]}.{parts[-1]}"
        
        # Add port if present
        if ':' in url:
            port = url.split(':')[-1]
            result += f":{port}"
        
        return result
    
    # Default: show end of URL with ellipsis
    if ':' in url:
        base_url, port = url.rsplit(':', 1)
        truncated_base = "..." + base_url[-(max_length-len(port)-4):]
        return f"{truncated_base}:{port}"
    
    return "..." + url[-(max_length-3):]

@app.template_filter('truncate_url')
def truncate_url_filter(url):
    """Template filter for URL truncation"""
    return truncate_ops_manager_url(url)

# Load list of all Ops Managers
with open('list-opsmanager-all.json') as f:
    list_opsmanager = json.load(f)

CACHE_DIR = 'cache'

# Ensure cache directory and subfolders exist
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)
for subfolder in ['backup', 'monitoring']:
    subfolder_path = os.path.join(CACHE_DIR, subfolder)
    if not os.path.exists(subfolder_path):
        os.makedirs(subfolder_path)

# Prepare options for dropdown
ops_manager_options = [
    {
        'name': item.get('name', item['url']),
        'url': item['url'],
        'public_key': item['public_key'],
        'private_key': item['private_key']
    }
    for item in list_opsmanager.get('ops_manager', [])
]

def get_cache_filename(ops_manager_name, cache_type='backup'):
    # Sanitize filename
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', ops_manager_name)
    filename = f"cached_{safe_name}.json"
    # Return full path inside cache subfolder
    return os.path.join(CACHE_DIR, cache_type, filename)

def load_cache(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            cache_content = json.load(f)
            # Handle both old format (direct data) and new format (with timestamp)
            if isinstance(cache_content, dict) and 'data' in cache_content:
                return cache_content['data']
            else:
                # Old format - return as is for backwards compatibility
                return cache_content
    return None

def save_cache(data, filename):
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'data': data
        }
        
        with open(filename, 'w') as f:
            json.dump(cache_data, f, indent=2)
        
        print(f"DEBUG: Successfully saved {len(data) if isinstance(data, list) else 'non-list'} records to {filename}")
        
    except Exception as e:
        print(f"ERROR: Failed to save cache to {filename}: {str(e)}")
        raise  # Re-raise so caller knows save failed

def get_cache_timestamp(filename):
    """Get the timestamp when cache was last updated"""
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            cache_content = json.load(f)
            if isinstance(cache_content, dict) and 'timestamp' in cache_content:
                return cache_content['timestamp']
    return None

def clear_cache(filename):
    if os.path.exists(filename):
        os.remove(filename)

def fetch_and_cache_data(ops_manager, data_type='backup'):
    """
    Fetch data from API for the given ops manager and save to cache.
    Returns (data, error_message) tuple.
    """
    try:
        domain_url = ops_manager['url']
        public_key = ops_manager['public_key']
        private_key = ops_manager['private_key']
        
        print(f"Fetching {data_type} data from API for {domain_url}...")
        
        if data_type == 'monitoring':
            data = gather_monitoring_data_for_credentials(domain_url, public_key, private_key)
        else:
            data = gather_data_for_credentials(domain_url, public_key, private_key)
        
        if data is not None:  # Changed: Allow empty list [] as valid data
            filename = get_cache_filename(domain_url, data_type)
            try:
                save_cache(data, filename)
                print(f"Successfully retrieved and cached {len(data)} {data_type} records for {domain_url}")
                return data, None
            except Exception as cache_error:
                print(f"WARNING: Data retrieved but caching failed for {domain_url}: {cache_error}")
                # Still return the data even if caching failed
                return data, None
        else:
            error_msg = f"No {data_type} data returned from API for {domain_url}"
            print(error_msg)
            return [], error_msg
            
    except Exception as e:
        error_msg = f"Failed to fetch {data_type} data from {ops_manager['url']}: {str(e)}"
        print(error_msg)
        return [], error_msg

def fetch_multiple_ops_managers_concurrent(ops_managers_list, data_type='backup', max_workers=4, refresh_requested=False):
    """
    Fetch data from multiple Ops Managers concurrently
    
    Args:
        ops_managers_list: List of ops manager configurations
        data_type: Type of data to fetch ('backup' or 'monitoring')
        max_workers: Maximum number of concurrent workers
    
    Returns:
        Tuple: (all_data, status_message, status_type, fetched_count, cached_count, errors)
    """
    print(f"DEBUG: Starting concurrent processing for {len(ops_managers_list)} ops managers with data_type={data_type}")
    all_data = []
    total_fetched = 0
    total_cached = 0
    errors = []
    
    def fetch_single_ops_manager(ops_manager):
        """Fetch data for a single ops manager"""
        try:
            domain_url = ops_manager['url']
            filename = get_cache_filename(domain_url, data_type)
            cached_data = load_cache(filename)
            
            # If refresh requested or no cache exists, fetch from API
            if refresh_requested or not cached_data:
                print(f"DEBUG: Fetching from API for {ops_manager.get('url', 'unknown')} (refresh_requested={refresh_requested}, has_cache={bool(cached_data)})")
                if refresh_requested and cached_data:
                    clear_cache(filename)
                
                fresh_data, error_msg = fetch_and_cache_data(ops_manager, data_type)
                if error_msg:
                    # If fresh fetch failed, try to use existing cache
                    if cached_data:
                        return {
                            'data': cached_data,
                            'fetched': 0,
                            'cached': len(cached_data),
                            'error': f"{ops_manager.get('region', 'Unknown')}-{ops_manager.get('environment', 'Unknown')}: {error_msg} (using cache)"
                        }
                    else:
                        return {
                            'data': [],
                            'fetched': 0,
                            'cached': 0,
                            'error': f"{ops_manager.get('region', 'Unknown')}-{ops_manager.get('environment', 'Unknown')}: {error_msg}"
                        }
                else:
                    return {
                        'data': fresh_data,
                        'fetched': len(fresh_data),
                        'cached': 0,
                        'error': None
                    }
            else:
                # Use existing cache
                print(f"DEBUG: Using cached data for {ops_manager.get('url', 'unknown')} ({len(cached_data)} records)")
                return {
                    'data': cached_data,
                    'fetched': 0,
                    'cached': len(cached_data),
                    'error': None
                }
        except Exception as e:
            return {
                'data': [],
                'fetched': 0,
                'cached': 0,
                'error': f"{ops_manager.get('url', 'Unknown')}: Unexpected error: {str(e)}"
            }
    
    # Use ThreadPoolExecutor for concurrent processing
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_ops_manager = {
            executor.submit(fetch_single_ops_manager, ops_manager): ops_manager
            for ops_manager in ops_managers_list
        }
        
        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_ops_manager):
            ops_manager = future_to_ops_manager[future]
            try:
                result = future.result()
                all_data.extend(result['data'])
                total_fetched += result['fetched']
                total_cached += result['cached']
                
                if result['error']:
                    errors.append(result['error'])
                    
            except Exception as e:
                error_msg = f"{ops_manager.get('url', 'Unknown')}: Exception during processing: {str(e)}"
                errors.append(error_msg)
    
    # Generate completion status message
    if errors:
        if total_fetched > 0 or total_cached > 0:
            if refresh_requested:
                status_message = f"Refresh completed with warnings. Fetched {total_fetched} records, used {total_cached} cached records from {len(ops_managers_list)} Ops Managers. Issues: {'; '.join(errors[:3])}{'...' if len(errors) > 3 else ''}"
            else:
                status_message = f"Data loaded with warnings. Fetched {total_fetched} records from API (cache missing), used {total_cached} cached records from {len(ops_managers_list)} Ops Managers. Issues: {'; '.join(errors[:3])}{'...' if len(errors) > 3 else ''}"
            status_type = "warning"
        else:
            if refresh_requested:
                status_message = f"Refresh failed. Errors: {'; '.join(errors[:3])}{'...' if len(errors) > 3 else ''}"
            else:
                status_message = f"Data loading failed. Errors: {'; '.join(errors[:3])}{'...' if len(errors) > 3 else ''}"
            status_type = "error"
    else:
        if refresh_requested:
            status_message = f"Refresh successful! Fetched {total_fetched} records from {len(ops_managers_list)} Ops Managers simultaneously."
        else:
            status_message = f"Data loaded successfully! Fetched {total_fetched} records from API (cache was missing) across {len(ops_managers_list)} Ops Managers."
        status_type = "success"
    
    return all_data, status_message, status_type, total_fetched, total_cached, errors

@app.route('/', methods=['GET', 'POST'])
def index():
    selected_ops_manager = None
    data = []
    refresh_requested = False
    status_message = ""
    status_type = ""

    # Determine selected Ops Manager from form or URL args
    if request.method == 'POST':
        if 'refresh' in request.form:
            refresh_requested = True
            selected_ops_manager = request.form.get('ops_manager')
        elif 'ops_manager' in request.form:
            selected_ops_manager = request.form.get('ops_manager')
    else:
        # For GET requests, check URL args
        selected_ops_manager = request.args.get('ops_manager')

    # Load data for selected Ops Manager
    if selected_ops_manager:
        filename = get_cache_filename(selected_ops_manager, 'backup')
        cached_data = load_cache(filename)
        
        # If refresh requested or no cache exists, fetch from API
        if refresh_requested or not cached_data:
            if refresh_requested and cached_data:
                clear_cache(filename)
            
            selected = next((o for o in ops_manager_options if o['name'] == selected_ops_manager), None)
            if selected:
                fresh_data, error_msg = fetch_and_cache_data(selected)
                if error_msg:
                    status_message = f"Failed to refresh data: {error_msg}"
                    status_type = "error"
                    # Use existing cache if refresh failed
                    if cached_data:
                        data = cached_data
                        status_message = f"Refresh failed, using cached data: {error_msg}"
                        status_type = "warning"
                else:
                    data = fresh_data
                    if refresh_requested:
                        status_message = f"Data refreshed successfully! Loaded {len(data)} clusters from API."
                        status_type = "success"
                    else:
                        status_message = f"Auto-loaded {len(data)} clusters from API (cache was missing)."
                        status_type = "info"
        else:
            # Use existing cache
            data = cached_data

    # Prepare list of unique usernames for filtering (handle null values)
    unique_usernames = set()
    if data:
        for record in data:
            username = record.get('Username')
            if username and username != 'null' and str(username).strip():
                unique_usernames.add(username)
            else:
                unique_usernames.add('NONE')

    # Get cache timestamp for display
    cache_timestamp = None
    if selected_ops_manager:
        filename = get_cache_filename(selected_ops_manager, 'backup')
        cache_timestamp = get_cache_timestamp(filename)

    return render_template(
        'main_material.html',
        options=ops_manager_options,
        data=data,
        selected_ops_manager=selected_ops_manager,
        unique_usernames=sorted(unique_usernames),
        status_message=status_message,
        status_type=status_type,
        cache_timestamp=cache_timestamp
    )

@app.route('/backup', methods=['GET', 'POST'])
def backup_page():
    unique_region = {record['region'] for record in list_opsmanager['ops_manager']}
    unique_env = {record['environment'] for record in list_opsmanager['ops_manager']}
    
    all_data = []
    selected_regions = []
    selected_environments = []
    refresh_requested = False
    status_message = ""
    status_type = ""
    
    if request.method == 'POST':
        print(f"DEBUG: POST request received for backup route")
        print(f"DEBUG: Form data: {dict(request.form)}")
        selected_regions = request.form.getlist('regions')
        selected_environments = request.form.getlist('environments')
        refresh_requested = 'refresh_data' in request.form
        print(f"DEBUG: refresh_requested={refresh_requested}")
        
        if refresh_requested and not (selected_regions or selected_environments):
            print("DEBUG: refresh_requested=True but no regions/environments selected!")
            status_message = "Please select regions or environments before refreshing data."
            status_type = "warning"
    
    if selected_regions or selected_environments:
        matching_ops_managers = []
        for ops_manager in list_opsmanager['ops_manager']:
            region_match = not selected_regions or ops_manager['region'] in selected_regions
            env_match = not selected_environments or ops_manager['environment'] in selected_environments
            if region_match and env_match:
                matching_ops_managers.append(ops_manager)
        
        # Check if we need concurrent processing (refresh requested OR multiple cache files missing)
        missing_cache_count = 0
        for ops_manager in matching_ops_managers:
            filename = get_cache_filename(ops_manager['url'], 'backup')
            cached_data = load_cache(filename)
            if not cached_data:
                missing_cache_count += 1
        
        # Use concurrent processing if refresh requested OR if 2+ cache files are missing
        use_concurrent = refresh_requested or (missing_cache_count >= 2)
        
        if use_concurrent:
            print(f"DEBUG: Using concurrent processing for backup - refresh_requested={refresh_requested}, missing_cache={missing_cache_count}")
            all_data, status_message, status_type, total_fetched, total_cached, errors = fetch_multiple_ops_managers_concurrent(
                matching_ops_managers, 'backup', max_workers=4, refresh_requested=refresh_requested
            )
        else:
            # Handle data loading sequentially
            total_fetched = 0
            total_cached = 0
            errors = []
            
            for ops_manager in matching_ops_managers:
                filename = get_cache_filename(ops_manager['url'], 'backup')
                cached_data = load_cache(filename)
                
                # If refresh requested or no cache exists, fetch from API
                if refresh_requested or not cached_data:
                    if refresh_requested and cached_data:
                        clear_cache(filename)
                    
                    fresh_data, error_msg = fetch_and_cache_data(ops_manager, 'backup')
                    if error_msg:
                        errors.append(f"{ops_manager['region']}-{ops_manager['environment']}: {error_msg}")
                        # Try to use existing cache if refresh failed
                        if cached_data:
                            all_data.extend(cached_data)
                            total_cached += len(cached_data)
                    else:
                        all_data.extend(fresh_data)
                        total_fetched += len(fresh_data)
                else:
                    # Use existing cache
                    all_data.extend(cached_data)
                    total_cached += len(cached_data)
            
            # Set status message
            if refresh_requested:
                if errors:
                    status_message = f"Refresh completed with errors. Fetched {total_fetched} clusters, used {total_cached} cached clusters. Errors: {'; '.join(errors)}"
                    status_type = "warning"
                else:
                    status_message = f"Data refreshed successfully! Fetched {total_fetched} clusters from API."
                    status_type = "success"
            elif total_fetched > 0:
                status_message = f"Data retrieval completed! Fetched {total_fetched} clusters from API (cache was missing)."
                status_type = "success"
    
    # Extract unique usernames, backup statuses, ops managers, and replica sets from the filtered data
    unique_usernames = set()
    unique_backup_statuses = set()
    unique_opsmanagers = set()
    unique_replicasets = set()
    
    if all_data:
        for record in all_data:
            # Handle username
            username = record.get('Username')
            if username and username != 'null' and str(username).strip():
                unique_usernames.add(username)
            else:
                unique_usernames.add('NONE')
            
            # Handle backup status
            backup_status = record.get('Backup Status')
            if backup_status and backup_status != 'null' and str(backup_status).strip():
                unique_backup_statuses.add(backup_status)
            else:
                unique_backup_statuses.add('NONE')
                
            # Handle ops manager
            ops_manager = record.get('Ops Manager')
            if ops_manager and ops_manager != 'null' and str(ops_manager).strip():
                unique_opsmanagers.add(ops_manager)
            else:
                unique_opsmanagers.add('NONE')
                
            # Handle replica set
            replica_set = record.get('Replica Set Name')
            if replica_set and replica_set != 'null' and str(replica_set).strip():
                unique_replicasets.add(replica_set)
            else:
                unique_replicasets.add('NONE')
                
    
    print(f"DEBUG: Rendering backup.html with {len(all_data)} records, status='{status_message}', type='{status_type}'")
    
    # Get cache timestamp for display
    cache_timestamp = None
    if selected_regions or selected_environments:
        # For backup, check the latest cache timestamp from any selected ops manager
        latest_timestamp = None
        for record in list_opsmanager['ops_manager']:
            if ((not selected_regions or record.get('region') in selected_regions) and 
                (not selected_environments or record.get('environment') in selected_environments)):
                filename = get_cache_filename(record.get('name', record['url']), 'backup')
                timestamp = get_cache_timestamp(filename)
                if timestamp and (not latest_timestamp or timestamp > latest_timestamp):
                    latest_timestamp = timestamp
        cache_timestamp = latest_timestamp
    
    return render_template('backup_material.html', 
                         unique_region=unique_region, 
                         unique_env=unique_env,
                         data=all_data,
                         selected_regions=selected_regions,
                         selected_environments=selected_environments,
                         unique_usernames=sorted(unique_usernames),
                         unique_backup_statuses=sorted(unique_backup_statuses),
                         unique_opsmanagers=sorted(unique_opsmanagers),
                         unique_replicasets=sorted(unique_replicasets),
                         status_message=status_message,
                         status_type=status_type,
                         cache_timestamp=cache_timestamp,
                         list_opsmanager=list_opsmanager)

@app.route('/monitoring', methods=['GET', 'POST'])
def monitoring_page():
    unique_region = {record['region'] for record in list_opsmanager['ops_manager']}
    unique_env = {record['environment'] for record in list_opsmanager['ops_manager']}
    
    all_data = []
    selected_regions = []
    selected_environments = []
    refresh_requested = False
    status_message = ""
    status_type = ""
    
    if request.method == 'POST':
        print(f"DEBUG: POST request received for monitoring route")
        print(f"DEBUG: Form data: {dict(request.form)}")
        selected_regions = request.form.getlist('regions')
        selected_environments = request.form.getlist('environments')
        refresh_requested = 'refresh_data' in request.form
        print(f"DEBUG: refresh_requested={refresh_requested}")
        
        if refresh_requested and not (selected_regions or selected_environments):
            print("DEBUG: refresh_requested=True but no regions/environments selected!")
            status_message = "Please select regions or environments before refreshing data."
            status_type = "warning"
    
    if selected_regions or selected_environments:
        matching_ops_managers = []
        for ops_manager in list_opsmanager['ops_manager']:
            region_match = not selected_regions or ops_manager['region'] in selected_regions
            env_match = not selected_environments or ops_manager['environment'] in selected_environments
            if region_match and env_match:
                matching_ops_managers.append(ops_manager)
        
        # Check if we need concurrent processing (refresh requested OR multiple cache files missing)
        missing_cache_count = 0
        for ops_manager in matching_ops_managers:
            filename = get_cache_filename(ops_manager['url'], 'monitoring')
            cached_data = load_cache(filename)
            if not cached_data:
                missing_cache_count += 1
        
        # Use concurrent processing if refresh requested OR if 2+ cache files are missing
        use_concurrent = refresh_requested or (missing_cache_count >= 2)
        
        if use_concurrent:
            print(f"DEBUG: Using concurrent processing for monitoring - refresh_requested={refresh_requested}, missing_cache={missing_cache_count}")
            all_data, status_message, status_type, total_fetched, total_cached, errors = fetch_multiple_ops_managers_concurrent(
                matching_ops_managers, 'monitoring', max_workers=4, refresh_requested=refresh_requested
            )
        else:
            # Handle data loading sequentially
            total_fetched = 0
            total_cached = 0
            errors = []
            
            for ops_manager in matching_ops_managers:
                filename = get_cache_filename(ops_manager['url'], 'monitoring')
                cached_data = load_cache(filename)
                
                # If refresh requested or no cache exists, fetch from API
                if refresh_requested or not cached_data:
                    if refresh_requested and cached_data:
                        clear_cache(filename)
                    
                    fresh_data, error_msg = fetch_and_cache_data(ops_manager, 'monitoring')
                    if error_msg:
                        errors.append(f"{ops_manager['region']}-{ops_manager['environment']}: {error_msg}")
                        # Try to use existing cache if refresh failed
                        if cached_data:
                            all_data.extend(cached_data)
                            total_cached += len(cached_data)
                    else:
                        all_data.extend(fresh_data)
                        total_fetched += len(fresh_data)
                else:
                    # Use existing cache
                    all_data.extend(cached_data)
                    total_cached += len(cached_data)
            
            # Set status message
            if refresh_requested:
                if errors:
                    status_message = f"Refresh completed with errors. Fetched {total_fetched} hosts, used {total_cached} cached hosts. Errors: {'; '.join(errors)}"
                    status_type = "warning"
                else:
                    status_message = f"Data refreshed successfully! Fetched {total_fetched} hosts from API."
                    status_type = "success"
            elif total_fetched > 0:
                status_message = f"Data retrieval completed! Fetched {total_fetched} hosts from API (cache was missing)."
                status_type = "success"
    
    # Extract unique usernames, ops managers, and replica sets from the filtered data
    unique_usernames = set()
    unique_opsmanagers = set()
    unique_replicasets = set()
    
    if all_data:
        for record in all_data:
            # Handle username
            username = record.get('Username')
            if username and username != 'null' and str(username).strip():
                unique_usernames.add(username)
            else:
                unique_usernames.add('NONE')
                
            # Handle ops manager
            ops_manager = record.get('Ops Manager')
            if ops_manager and ops_manager != 'null' and str(ops_manager).strip():
                unique_opsmanagers.add(ops_manager)
            else:
                unique_opsmanagers.add('NONE')
                
            # Handle replica set
            replica_set = record.get('Replica Set Name')
            if replica_set and replica_set != 'null' and str(replica_set).strip():
                unique_replicasets.add(replica_set)
            else:
                unique_replicasets.add('NONE')
                
    
    print(f"DEBUG: Rendering monitoring.html with {len(all_data)} records, status='{status_message}', type='{status_type}'")
    
    # Get cache timestamp for display
    cache_timestamp = None
    if selected_regions or selected_environments:
        # For monitoring, check the latest cache timestamp from any selected ops manager
        latest_timestamp = None
        for record in list_opsmanager['ops_manager']:
            if ((not selected_regions or record.get('region') in selected_regions) and 
                (not selected_environments or record.get('environment') in selected_environments)):
                filename = get_cache_filename(record.get('name', record['url']), 'monitoring')
                timestamp = get_cache_timestamp(filename)
                if timestamp and (not latest_timestamp or timestamp > latest_timestamp):
                    latest_timestamp = timestamp
        cache_timestamp = latest_timestamp
    
    return render_template('monitoring_material.html', 
                         unique_region=unique_region, 
                         unique_env=unique_env,
                         data=all_data,
                         selected_regions=selected_regions,
                         selected_environments=selected_environments,
                         unique_usernames=sorted(unique_usernames),
                         unique_opsmanagers=sorted(unique_opsmanagers),
                         unique_replicasets=sorted(unique_replicasets),
                         status_message=status_message,
                         status_type=status_type,
                         cache_timestamp=cache_timestamp,
                         list_opsmanager=list_opsmanager)

if __name__ == '__main__':
    app.run(debug=True, port=5000)