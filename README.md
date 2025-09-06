# MongoDB Ops Manager Dashboard

Modern Material Design dashboard for monitoring MongoDB Ops Manager environments with offline capabilities.

## Requirements

- Python 3.7+
- Modern web browser

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Ops Managers
Edit `list-opsmanager-all.json`:
```json
{
  "ops_manager": [
    {
      "name": "Production Environment",
      "url": "https://your-ops-manager.com",
      "public_key": "your-public-api-key",
      "private_key": "your-private-api-key",
      "region": "us-west-2",
      "environment": "production"
    }
  ]
}
```

### 3. Run Dashboard
```bash
python3 adminlte.py
```

### 4. Access Dashboard
Open: http://localhost:5000

## Features

- Material Design UI with Tabler.io framework
- Multi-environment monitoring (backup & monitoring users)
- Advanced filtering and pagination
- CSV export functionality
- Local timezone conversion
- 100% offline capable (no CDN dependencies)
- Smart caching system