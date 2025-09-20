"""
MongoDB Ops Manager Backup Storage Configuration Module

This module provides functions to retrieve backup storage configurations
from MongoDB Ops Manager including snapshot blockstores, S3 configs,
oplog storage, and S3 oplog configurations.
"""

import requests
from requests.auth import HTTPDigestAuth
from urllib.parse import urlparse
from typing import Dict, List, Optional

# Default headers for MongoDB Ops Manager API
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json"
}

def get_snapshot_blockstore(domain_url: str, public_key: str, private_key: str) -> List[Dict]:
    """
    Fetch snapshot MongoDB blockstore configurations from Ops Manager.
    
    Args:
        domain_url: The base URL of the Ops Manager instance
        public_key: API public key for authentication
        private_key: API private key for authentication
        
    Returns:
        List of snapshot blockstore configurations
    """
    url = f"{domain_url}/api/public/v1.0/admin/backup/snapshot/mongoConfigs?pretty=true&assignableOnly=false"
    
    try:
        response = requests.get(url, headers=HEADERS, auth=HTTPDigestAuth(public_key, private_key))
        response.raise_for_status()
        
        data = response.json()
        results = []
        
        if data.get('results'):
            for item in data['results']:
                config = {
                    'type': 'snapshot_blockstore',
                    'id': item.get('id'),
                    'uri': item.get('uri'),
                    'ops_manager': urlparse(domain_url).hostname
                }
                results.append(config)
                
        return results
        
    except Exception as e:
        print(f"Error fetching snapshot blockstore configs from {domain_url}: {str(e)}")
        return []

def get_snapshot_s3config(domain_url: str, public_key: str, private_key: str) -> List[Dict]:
    """
    Fetch snapshot S3 storage configurations from Ops Manager.
    
    Args:
        domain_url: The base URL of the Ops Manager instance
        public_key: API public key for authentication
        private_key: API private key for authentication
        
    Returns:
        List of snapshot S3 configurations
    """
    url = f"{domain_url}/api/public/v1.0/admin/backup/snapshot/s3Configs?pretty=true&assignableOnly=false"
    
    try:
        response = requests.get(url, headers=HEADERS, auth=HTTPDigestAuth(public_key, private_key))
        response.raise_for_status()
        
        data = response.json()
        results = []
        
        if data.get('results'):
            for item in data['results']:
                config = {
                    'type': 'snapshot_s3',
                    'id': item.get('id'),
                    'uri': item.get('uri'),
                    'bucket_name': item.get('s3BucketName', 'N/A'),
                    'ops_manager': urlparse(domain_url).hostname
                }
                results.append(config)
                
        return results
        
    except Exception as e:
        print(f"Error fetching snapshot S3 configs from {domain_url}: {str(e)}")
        return []

def get_oplog_store(domain_url: str, public_key: str, private_key: str) -> List[Dict]:
    """
    Fetch oplog MongoDB storage configurations from Ops Manager.
    
    Args:
        domain_url: The base URL of the Ops Manager instance
        public_key: API public key for authentication
        private_key: API private key for authentication
        
    Returns:
        List of oplog storage configurations
    """
    url = f"{domain_url}/api/public/v1.0/admin/backup/oplog/mongoConfigs?pretty=true&assignableOnly=false"
    
    try:
        response = requests.get(url, headers=HEADERS, auth=HTTPDigestAuth(public_key, private_key))
        response.raise_for_status()
        
        data = response.json()
        results = []
        
        if data.get('results'):
            for item in data['results']:
                config = {
                    'type': 'oplog_store',
                    'id': item.get('id'),
                    'uri': item.get('uri'),
                    'ops_manager': urlparse(domain_url).hostname
                }
                results.append(config)
                
        return results
        
    except Exception as e:
        print(f"Error fetching oplog storage configs from {domain_url}: {str(e)}")
        return []

def get_oplog_s3config(domain_url: str, public_key: str, private_key: str) -> List[Dict]:
    """
    Fetch oplog S3 storage configurations from Ops Manager.
    
    Args:
        domain_url: The base URL of the Ops Manager instance
        public_key: API public key for authentication
        private_key: API private key for authentication
        
    Returns:
        List of oplog S3 configurations
    """
    url = f"{domain_url}/api/public/v1.0/admin/backup/oplog/s3Configs?pretty=true&assignableOnly=false"
    
    try:
        response = requests.get(url, headers=HEADERS, auth=HTTPDigestAuth(public_key, private_key))
        response.raise_for_status()
        
        data = response.json()
        results = []
        
        if data.get('results'):
            for item in data['results']:
                config = {
                    'type': 'oplog_s3',
                    'id': item.get('id'),
                    'uri': item.get('uri'),
                    'bucket_name': item.get('s3BucketName', 'N/A'),
                    'ops_manager': urlparse(domain_url).hostname
                }
                results.append(config)
                
        return results
        
    except Exception as e:
        print(f"Error fetching oplog S3 configs from {domain_url}: {str(e)}")
        return []

def gather_backup_storage_for_credentials(domain_url: str, public_key: str, private_key: str) -> Optional[List[Dict]]:
    """
    Main function to gather all backup storage configurations for a single Ops Manager.
    This is the primary function to be used by the dashboard integration.
    
    Args:
        domain_url: The base URL of the Ops Manager instance
        public_key: API public key for authentication
        private_key: API private key for authentication
        
    Returns:
        List of all storage configurations or None if error
    """
    try:
        all_configs = []
        
        # Gather all storage configuration types
        all_configs.extend(get_snapshot_blockstore(domain_url, public_key, private_key))
        all_configs.extend(get_snapshot_s3config(domain_url, public_key, private_key))
        all_configs.extend(get_oplog_store(domain_url, public_key, private_key))
        all_configs.extend(get_oplog_s3config(domain_url, public_key, private_key))
        
        # Add Ops Manager URL to each configuration for display
        for config in all_configs:
            config['Ops Manager'] = urlparse(domain_url).hostname or domain_url
        
        return all_configs if all_configs else None
        
    except Exception as e:
        print(f"Error gathering backup storage data for {domain_url}: {str(e)}")
        return None