# MongoDB Ops Manager Dashboard

A modern **Material Design** dashboard for monitoring MongoDB Ops Manager environments with **offline-first capabilities** and enhanced user experience.

![Dashboard Preview](https://img.shields.io/badge/Status-Production%20Ready-brightgreen) ![Python](https://img.shields.io/badge/Python-3.7%2B-blue) ![Flask](https://img.shields.io/badge/Flask-2.3%2B-lightgrey) ![Offline](https://img.shields.io/badge/Offline-Ready-orange)

## ✨ Features

### 🎨 Modern Material UI
- **Tabler.io Framework** - Clean, responsive Material Design interface
- **5800+ Icons** - Complete Tabler icons set (fully offline)
- **MongoDB Branding** - Custom color scheme with MongoDB green (#13AA52)
- **Mobile Responsive** - Works perfectly on desktop, tablet, and mobile devices

### 🚀 Advanced Functionality
- **Multi-Environment Monitoring** - Monitor backup and monitoring users across environments
- **Smart Filtering** - Advanced multi-column filtering with search and bulk selection
- **Intelligent Pagination** - Optimized for large datasets (1000+ records)
- **Real-time Data** - Concurrent API calls for fast data retrieval
- **CSV Export** - Export filtered data with timestamps
- **Cache System** - Intelligent caching for improved performance

### 🌐 Offline-First Design
- **100% Offline Capable** - All assets served locally, no CDN dependencies
- **Air-Gap Ready** - Perfect for secure, isolated environments
- **Fast Loading** - No network timeouts or external resource delays
- **Self-Contained** - Complete standalone operation

### ⏰ Enhanced User Experience
- **Local Timezone** - Automatic conversion to user's browser timezone
- **Loading States** - Smooth loading experience with progress indicators
- **Error Handling** - Graceful fallback to cached data when API unavailable
- **Performance Optimized** - Smart caching and optimized asset delivery

## 🏗️ Architecture

```
MongoDB Ops Manager Dashboard
├── Flask Backend (adminlte.py)
├── MongoDB API Integration (get_*.py)
├── Material UI Templates (templates/)
├── Offline Assets (static/)
├── Intelligent Cache (cache/)
└── Configuration (list-opsmanager-all.json)
```

## 📋 Requirements

### System Requirements
- **Python 3.7+** (tested up to Python 3.11)
- **Modern Web Browser** with JavaScript enabled
- **Network Access** to MongoDB Ops Manager APIs (for data retrieval)

### Python Dependencies
- **Flask 2.3+** - Web framework
- **Requests 2.31+** - HTTP library for API calls
- **Standard Library** - No additional packages needed

## 🚀 Quick Start

### 1. Clone Repository
```bash
git clone <repository-url>
cd dashboard-opsmanager
```

### 2. Install Dependencies
```bash
# Using pip
pip install -r requirements.txt

# Or using pip3
pip3 install -r requirements.txt
```

### 3. Configure Ops Managers
Edit `list-opsmanager-all.json` with your MongoDB Ops Manager details:

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

### 4. Run Dashboard
```bash
python3 adminlte.py
```

### 5. Access Dashboard
Open your browser and navigate to: **http://localhost:5000**

## 📁 Project Structure

```
dashboard-opsmanager/
│
├── adminlte.py                 # Flask application
├── get_request.py              # Backup API integration  
├── get_monitoring.py           # Monitoring API integration
├── list-opsmanager-all.json    # Configuration file
├── requirements.txt            # Python dependencies
├── README.md                   # This file
│
├── templates/                  # Material UI Templates
│   ├── base_material.html      # Base template with Material Design
│   ├── main_material.html      # Dashboard homepage
│   ├── backup_material.html    # Backup users monitoring
│   └── monitoring_material.html # Monitoring users overview
│
├── static/                     # Offline Assets (9.3MB)
│   ├── css/                    # AdminLTE & Bootstrap CSS
│   ├── js/                     # JavaScript libraries
│   ├── fonts/                  # Source Sans 3 typography
│   ├── assets/img/             # Images and logos
│   └── tabler/                 # Tabler.io framework
│       ├── css/                # Tabler CSS
│       ├── js/                 # Tabler JavaScript
│       └── icons/              # Icon fonts (5800+ icons)
│
└── cache/                      # Data Cache
    ├── backup/                 # Backup user cache files
    └── monitoring/             # Monitoring user cache files
```

## ⚙️ Configuration

### MongoDB Ops Manager Setup

1. **API Keys**: Generate public/private API key pairs in Ops Manager
2. **Permissions**: Ensure API keys have read access to:
   - Organizations
   - Projects
   - Clusters
   - Backup configurations
   - Monitoring agents

3. **Network**: Dashboard server needs HTTPS access to Ops Manager APIs

### Environment Variables (Optional)
```bash
export FLASK_ENV=production
export FLASK_HOST=0.0.0.0
export FLASK_PORT=5000
```

## 🚀 Production Deployment

### Option 1: Gunicorn (Recommended)
```bash
# Install Gunicorn
pip install gunicorn

# Run with Gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 adminlte:app
```

### Option 2: Docker Deployment
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 5000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "adminlte:app"]
```

### Option 3: Systemd Service
```ini
[Unit]
Description=MongoDB Ops Manager Dashboard
After=network.target

[Service]
Type=exec
User=dashboard
Group=dashboard
WorkingDirectory=/opt/dashboard-opsmanager
ExecStart=/usr/bin/python3 adminlte.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## 🌐 Offline Deployment

Perfect for **air-gapped environments** and **secure networks**:

1. **No Internet Required** - All assets (CSS, JS, fonts, icons) are included
2. **Self-Contained** - No external CDN or API dependencies  
3. **Complete Functionality** - Full feature set available offline
4. **Fast Performance** - No network delays or timeouts

Simply copy the entire project directory to your target system and run!

## 📊 Performance Features

### Smart Caching
- **Automatic Caching** - API responses cached locally for faster loading
- **Cache Validation** - Intelligent cache refresh based on data age
- **Offline Fallback** - Uses cached data when API unavailable

### Optimized UI
- **Smart Pagination** - Handles 1000+ records efficiently  
- **Advanced Filtering** - Multi-column filters with search
- **Lazy Loading** - Progressive loading for better performance
- **Compressed Assets** - Minified CSS/JS for faster loading

## 🔧 Troubleshooting

### Common Issues

**Q: Dashboard shows "No Data" or blank pages**
- **A**: Check API keys and network connectivity to Ops Manager
- Verify Ops Manager URLs are accessible from dashboard server
- Check browser console for JavaScript errors

**Q: Icons not displaying properly**
- **A**: Ensure `static/tabler/icons/` directory contains font files
- Check browser developer tools for 404 errors on font files
- Verify static file serving is working: `http://localhost:5000/static/tabler/icons/tabler-icons.min.css`

**Q: Slow performance with large datasets**
- **A**: Increase pagination limit in templates (default: 50 rows)
- Enable browser caching for static assets
- Consider implementing API pagination for very large environments

**Q: Timezone issues**
- **A**: JavaScript automatically detects browser timezone
- Check browser console for timezone conversion errors
- Verify `convertTimestampToLocal()` function in templates

### Debug Mode
```bash
# Enable Flask debug mode
export FLASK_ENV=development
python3 adminlte.py
```

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙋 Support

- **Documentation**: Check this README and inline code comments
- **Issues**: Report bugs and feature requests via GitHub Issues
- **Configuration**: Review `list-opsmanager-all.json` for setup examples

## 🎯 Roadmap

- [ ] **Dark Mode** - Toggle between light and dark themes  
- [ ] **Real-time Updates** - WebSocket integration for live data
- [ ] **Multi-language** - Internationalization support
- [ ] **Advanced Analytics** - Charts and trend analysis
- [ ] **User Management** - Authentication and role-based access
- [ ] **API Integration** - RESTful API for external integrations

---

**Built with ❤️ for MongoDB Ops Manager administrators**

*Modern • Offline-Ready • Performance-Optimized • Production-Ready*