from flask import Flask, render_template, request, redirect, url_for
import os
import json
import re
from datetime import datetime
import concurrent.futures
import threading
import time
import requests
from requests.auth import HTTPDigestAuth
from urllib.parse import urlparse
from get_request import (
    get_organization_list,
    get_project_list,
    get_clusters,
    get_backup_config,
    get_status_from_last_ping,
    gather_data_for_credentials
)
from get_monitoring import gather_monitoring_data_for_credentials
from get_backup_storage import gather_backup_storage_for_credentials

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
for subfolder in ['backup', 'monitoring', 'backup_storage']:
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
        elif data_type == 'backup_storage':
            data = gather_backup_storage_for_credentials(domain_url, public_key, private_key)
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

def check_ops_manager_accessibility(url):
    """
    Check if Ops Manager URL is accessible with retry logic.
    
    Args:
        url: The Ops Manager URL to check
        
    Returns:
        dict: {'status': 'accessible'|'unreachable'|'timeout', 'response_time': float, 'attempts': int, 'details': str}
    """
    attempts = []
    total_start_time = time.time()
    
    # First attempt: 5 second timeout
    try:
        start_time = time.time()
        response = requests.get(f"{url}/", timeout=5, verify=False)
        response_time = time.time() - start_time
        attempts.append({'attempt': 1, 'status': 'success', 'response_time': response_time, 'timeout': 5})
        
        if response.status_code in [200, 401, 403]:  # These indicate the service is running
            total_time = time.time() - total_start_time
            return {
                'status': 'accessible', 
                'response_time': total_time,
                'attempts': 1,
                'details': f'Connected successfully on first attempt (HTTP {response.status_code})',
                'attempt_details': attempts
            }
        else:
            # Unexpected status code, try second attempt
            attempts.append({'attempt': 1, 'status': 'unexpected_status', 'status_code': response.status_code, 'response_time': response_time})
    except requests.exceptions.Timeout:
        attempts.append({'attempt': 1, 'status': 'timeout', 'response_time': 5.0, 'timeout': 5})
    except requests.exceptions.ConnectionError as e:
        attempts.append({'attempt': 1, 'status': 'connection_error', 'response_time': time.time() - start_time, 'error': str(e)})
    except Exception as e:
        attempts.append({'attempt': 1, 'status': 'error', 'response_time': time.time() - start_time, 'error': str(e)})
    
    # Second attempt: 3 second timeout (faster)
    try:
        start_time = time.time()
        response = requests.get(f"{url}/", timeout=3, verify=False)
        response_time = time.time() - start_time
        attempts.append({'attempt': 2, 'status': 'success', 'response_time': response_time, 'timeout': 3})
        
        if response.status_code in [200, 401, 403]:  # These indicate the service is running
            total_time = time.time() - total_start_time
            return {
                'status': 'accessible', 
                'response_time': total_time,
                'attempts': 2,
                'details': f'Connected successfully on second attempt (HTTP {response.status_code})',
                'attempt_details': attempts
            }
        else:
            attempts.append({'attempt': 2, 'status': 'unexpected_status', 'status_code': response.status_code, 'response_time': response_time})
            total_time = time.time() - total_start_time
            return {
                'status': 'unreachable', 
                'response_time': total_time,
                'attempts': 2,
                'details': f'Unexpected status code: {response.status_code} (tried 2 times)',
                'attempt_details': attempts
            }
            
    except requests.exceptions.Timeout:
        attempts.append({'attempt': 2, 'status': 'timeout', 'response_time': 3.0, 'timeout': 3})
        total_time = time.time() - total_start_time
        return {
            'status': 'timeout', 
            'response_time': total_time,
            'attempts': 2,
            'details': 'Both attempts timed out (5s + 3s)',
            'attempt_details': attempts
        }
    except requests.exceptions.ConnectionError as e:
        attempts.append({'attempt': 2, 'status': 'connection_error', 'response_time': time.time() - start_time, 'error': str(e)})
        total_time = time.time() - total_start_time
        return {
            'status': 'unreachable', 
            'response_time': total_time,
            'attempts': 2,
            'details': 'Connection failed on both attempts',
            'attempt_details': attempts
        }
    except Exception as e:
        attempts.append({'attempt': 2, 'status': 'error', 'response_time': time.time() - start_time, 'error': str(e)})
        total_time = time.time() - total_start_time
        return {
            'status': 'error', 
            'response_time': total_time,
            'attempts': 2,
            'details': f'Error on both attempts: {str(e)}',
            'attempt_details': attempts
        }

def check_api_authentication(url, public_key, private_key):
    """
    Check if API credentials can authenticate with Ops Manager.
    
    Args:
        url: The Ops Manager URL
        public_key: API public key
        private_key: API private key
        
    Returns:
        dict: {'status': 'authenticated'|'unauthorized'|'timeout'|'error', 'response_time': float}
    """
    try:
        start_time = time.time()
        # Use a simple API endpoint to test authentication
        api_url = f"{url}/api/public/v1.0/orgs"
        
        response = requests.get(
            api_url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            auth=HTTPDigestAuth(public_key, private_key),
            timeout=10,
            verify=False
        )
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            return {'status': 'authenticated', 'response_time': response_time}
        elif response.status_code in [401, 403]:
            return {'status': 'unauthorized', 'response_time': response_time}
        else:
            return {'status': 'error', 'response_time': response_time, 'status_code': response.status_code}
            
    except requests.exceptions.Timeout:
        return {'status': 'timeout', 'response_time': 10.0}
    except requests.exceptions.ConnectionError:
        return {'status': 'unreachable', 'response_time': 0.0}
    except Exception as e:
        return {'status': 'error', 'response_time': 0.0, 'error': str(e)}

def get_ops_manager_version(url):
    """
    Retrieve the MongoDB Ops Manager version from the version manifest endpoint.
    
    Args:
        url: The Ops Manager URL
        
    Returns:
        str: Version string or 'Unknown' if retrieval fails
    """
    try:
        # Use the unauth version manifest endpoint
        version_url = f"{url}/api/public/v1.0/unauth/versionManifest"
        
        response = requests.get(
            version_url,
            headers={"Accept": "application/json"},
            timeout=10,
            verify=False
        )
        
        # Extract version from X-MongoDB-Service-Version header
        version_header = response.headers.get('X-MongoDB-Service-Version', '')
        
        if 'versionString=' in version_header:
            # Parse: "gitHash=abc123; versionString=7.0.1.123456789"
            parts = version_header.split(';')
            for part in parts:
                part = part.strip()
                if part.startswith('versionString='):
                    version = part.split('=', 1)[1]
                    return version if version else 'Unknown'
        
        return 'Unknown'
        
    except requests.exceptions.Timeout:
        return 'Unknown'
    except requests.exceptions.ConnectionError:
        return 'Unknown'
    except Exception as e:
        return 'Unknown'

def check_ops_manager_status(ops_manager):
    """
    Check accessibility, authentication, and version for a single Ops Manager.
    
    Args:
        ops_manager: Dict containing url, public_key, private_key, region, environment
        
    Returns:
        dict: Combined status information including version
    """
    url = ops_manager['url']
    public_key = ops_manager['public_key']
    private_key = ops_manager['private_key']
    
    # Check accessibility
    accessibility_result = check_ops_manager_accessibility(url)
    
    # Check authentication only if accessible
    if accessibility_result['status'] == 'accessible':
        auth_result = check_api_authentication(url, public_key, private_key)
        # Also get version if accessible
        version = get_ops_manager_version(url)
    else:
        auth_result = {'status': 'not_checked', 'response_time': 0.0}
        version = 'Unknown'
    
    return {
        'url': url,
        'hostname': urlparse(url).hostname or url,
        'region': ops_manager['region'],
        'environment': ops_manager['environment'],
        'accessibility': accessibility_result,
        'authentication': auth_result,
        'version': version
    }

@app.route('/', methods=['GET', 'POST'])
def ops_manager_status():
    """
    Main dashboard showing status of all Ops Manager instances.
    """
    status_results = []
    refresh_requested = False
    
    # Record when status checks are performed
    check_timestamp = datetime.now()
    
    if request.method == 'POST' and 'refresh' in request.form:
        refresh_requested = True
    
    # Check status for all Ops Managers concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_ops_manager = {
            executor.submit(check_ops_manager_status, ops_manager): ops_manager
            for ops_manager in list_opsmanager['ops_manager']
        }
        
        for future in concurrent.futures.as_completed(future_to_ops_manager):
            try:
                result = future.result()
                status_results.append(result)
            except Exception as e:
                ops_manager = future_to_ops_manager[future]
                status_results.append({
                    'url': ops_manager['url'],
                    'hostname': urlparse(ops_manager['url']).hostname or ops_manager['url'],
                    'region': ops_manager['region'],
                    'environment': ops_manager['environment'],
                    'accessibility': {'status': 'error', 'response_time': 0.0, 'error': str(e)},
                    'authentication': {'status': 'not_checked', 'response_time': 0.0}
                })
    
    # Sort results by region and environment
    status_results.sort(key=lambda x: (x['region'], x['environment']))
    
    # Calculate summary statistics
    total_ops_managers = len(status_results)
    accessible_count = sum(1 for r in status_results if r['accessibility']['status'] == 'accessible')
    authenticated_count = sum(1 for r in status_results if r['authentication']['status'] == 'authenticated')
    
    return render_template(
        'status_dashboard.html',
        status_results=status_results,
        total_ops_managers=total_ops_managers,
        accessible_count=accessible_count,
        authenticated_count=authenticated_count,
        refresh_requested=refresh_requested,
        check_timestamp=check_timestamp.isoformat()
    )

@app.route('/single-bkp-opsmanager', methods=['GET', 'POST'])
def single_bkp_opsmanager():
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
    
    # Extract unique usernames, backup statuses, ops managers from the filtered data
    unique_usernames = set()
    unique_backup_statuses = set()
    unique_opsmanagers = set()
    
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
    
    # Extract unique usernames and ops managers from the filtered data
    unique_usernames = set()
    unique_opsmanagers = set()
    
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
                         status_message=status_message,
                         status_type=status_type,
                         cache_timestamp=cache_timestamp,
                         list_opsmanager=list_opsmanager)

@app.route('/backup-storage', methods=['GET', 'POST'])
def backup_storage_page():
    unique_region = {record['region'] for record in list_opsmanager['ops_manager']}
    unique_env = {record['environment'] for record in list_opsmanager['ops_manager']}
    
    all_data = []
    selected_regions = []
    selected_environments = []
    refresh_requested = False
    status_message = ""
    status_type = ""
    
    if request.method == 'POST':
        print(f"DEBUG: POST request received for backup storage route")
        print(f"DEBUG: Form data: {dict(request.form)}")
        selected_regions = request.form.getlist('regions')
        selected_environments = request.form.getlist('environments')
        refresh_requested = 'refresh' in request.form
        print(f"DEBUG: refresh_requested={refresh_requested}")
        
        # If refresh is requested, automatically select all regions and environments
        if refresh_requested:
            if not selected_regions and not selected_environments:
                selected_regions = list(unique_region)
                selected_environments = list(unique_env)
                print(f"DEBUG: Refresh requested - auto-selecting all regions: {selected_regions} and environments: {selected_environments}")
    
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
            filename = get_cache_filename(ops_manager['url'], 'backup_storage')
            cached_data = load_cache(filename)
            if not cached_data:
                missing_cache_count += 1
        
        # Use concurrent processing if refresh requested OR if 2+ cache files are missing
        use_concurrent = refresh_requested or (missing_cache_count >= 2)
        
        if use_concurrent:
            print(f"DEBUG: Using concurrent processing for backup storage - refresh_requested={refresh_requested}, missing_cache={missing_cache_count}")
            all_data, status_message, status_type, total_fetched, total_cached, errors = fetch_multiple_ops_managers_concurrent(
                matching_ops_managers, 'backup_storage', max_workers=4, refresh_requested=refresh_requested
            )
        else:
            # Handle data loading sequentially
            total_fetched = 0
            total_cached = 0
            errors = []
            
            for ops_manager in matching_ops_managers:
                filename = get_cache_filename(ops_manager['url'], 'backup_storage')
                cached_data = load_cache(filename)
                
                # If refresh requested or no cache exists, fetch from API
                if refresh_requested or not cached_data:
                    if refresh_requested and cached_data:
                        clear_cache(filename)
                    
                    fresh_data = gather_backup_storage_for_credentials(
                        ops_manager['url'], 
                        ops_manager['public_key'], 
                        ops_manager['private_key']
                    )
                    
                    if fresh_data:
                        try:
                            save_cache(fresh_data, filename)
                            all_data.extend(fresh_data)
                            total_fetched += len(fresh_data)
                        except Exception as cache_error:
                            print(f"WARNING: Data retrieved but caching failed for {ops_manager['url']}: {cache_error}")
                            all_data.extend(fresh_data)
                            total_fetched += len(fresh_data)
                    else:
                        errors.append(f"{ops_manager['region']}-{ops_manager['environment']}: No backup storage data returned")
                        # Try to use existing cache if fetch failed
                        if cached_data:
                            all_data.extend(cached_data)
                            total_cached += len(cached_data)
                else:
                    # Use existing cache
                    all_data.extend(cached_data)
                    total_cached += len(cached_data)
            
            # Set status message
            if refresh_requested:
                if errors:
                    status_message = f"Refresh completed with errors. Fetched {total_fetched} storage configs, used {total_cached} cached configs. Errors: {'; '.join(errors)}"
                    status_type = "warning"
                else:
                    status_message = f"Data refreshed successfully! Fetched {total_fetched} backup storage configurations from API."
                    status_type = "success"
            elif total_fetched > 0:
                status_message = f"Data retrieval completed! Fetched {total_fetched} backup storage configurations from API (cache was missing)."
                status_type = "success"
    
    # Separate data by storage type AND extract unique values from the filtered data
    snapshot_blockstore_data = []
    snapshot_s3_data = []
    oplog_store_data = []
    oplog_s3_data = []
    
    unique_storage_types = set()
    unique_opsmanagers = set()
    
    if all_data:
        for record in all_data:
            # Handle storage type
            storage_type = record.get('type')
            if storage_type and storage_type != 'null' and str(storage_type).strip():
                unique_storage_types.add(storage_type)
                
                # Separate by storage type
                if storage_type == 'snapshot_blockstore':
                    snapshot_blockstore_data.append(record)
                elif storage_type == 'snapshot_s3':
                    snapshot_s3_data.append(record)
                elif storage_type == 'oplog_store':
                    oplog_store_data.append(record)
                elif storage_type == 'oplog_s3':
                    oplog_s3_data.append(record)
            else:
                unique_storage_types.add('NONE')
                
            # Handle ops manager
            ops_manager = record.get('Ops Manager')
            if ops_manager and ops_manager != 'null' and str(ops_manager).strip():
                unique_opsmanagers.add(ops_manager)
            else:
                unique_opsmanagers.add('NONE')
                
    
    print(f"DEBUG: Rendering backup-storage.html with {len(all_data)} records, status='{status_message}', type='{status_type}'")
    
    # Get cache timestamp for display
    cache_timestamp = None
    if selected_regions or selected_environments:
        # For backup storage, check the latest cache timestamp from any selected ops manager
        latest_timestamp = None
        for record in list_opsmanager['ops_manager']:
            if ((not selected_regions or record.get('region') in selected_regions) and 
                (not selected_environments or record.get('environment') in selected_environments)):
                filename = get_cache_filename(record.get('name', record['url']), 'backup_storage')
                timestamp = get_cache_timestamp(filename)
                if timestamp and (not latest_timestamp or timestamp > latest_timestamp):
                    latest_timestamp = timestamp
        cache_timestamp = latest_timestamp
    
    return render_template('backup_storage_material.html', 
                         unique_region=unique_region, 
                         unique_env=unique_env,
                         data=all_data,  # Keep for backward compatibility
                         snapshot_blockstore_data=snapshot_blockstore_data,
                         snapshot_s3_data=snapshot_s3_data,
                         oplog_store_data=oplog_store_data,
                         oplog_s3_data=oplog_s3_data,
                         selected_regions=selected_regions,
                         selected_environments=selected_environments,
                         unique_storage_types=sorted(unique_storage_types),
                         unique_opsmanagers=sorted(unique_opsmanagers),
                         status_message=status_message,
                         status_type=status_type,
                         cache_timestamp=cache_timestamp,
                         list_opsmanager=list_opsmanager)

if __name__ == '__main__':
    app.run(debug=True, port=5000)