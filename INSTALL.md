# Quick Installation Guide

## 🚀 5-Minute Setup

### Prerequisites
- Python 3.7+ installed
- Network access to MongoDB Ops Manager APIs
- Modern web browser

### Step 1: Install Dependencies
```bash
pip install Flask requests
```

### Step 2: Configure Ops Manager
Edit `list-opsmanager-all.json`:
```json
{
  "ops_manager": [
    {
      "name": "Your Environment",
      "url": "https://your-ops-manager-url.com",
      "public_key": "your-public-api-key",
      "private_key": "your-private-api-key",
      "region": "your-region",
      "environment": "production"
    }
  ]
}
```

### Step 3: Run Dashboard
```bash
python3 adminlte.py
```

### Step 4: Access
Open: **http://localhost:5000**

That's it! 🎉

---

*For detailed instructions, see [README.md](README.md)*