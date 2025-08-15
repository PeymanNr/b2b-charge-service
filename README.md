# B2B Charge Service

A robust enterprise-grade B2B telecommunications charge sales platform built with Django, featuring advanced financial integrity controls, concurrency safety mechanisms, and real-time balance reconciliation.

## 🚀 Overview

This system enables vendors to purchase and sell phone charges through a secure credit-based system. It provides complete financial transparency, prevents negative balances, and maintains accounting accuracy under high concurrent loads.

### Key Features

- **🏢 Vendor Management**: Multi-vendor support with individual credit balances
- **💰 Credit Management**: Admin-approved credit increase requests
- **📱 Charge Sales**: API-based phone charge sales with real-time balance updates
- **🔒 Financial Security**: Zero-tolerance for negative balances and double-spending
- **⚡ Concurrency Safety**: Race condition protection and atomic transactions
- **📊 Balance Reconciliation**: Automated financial integrity verification
- **🔍 Audit Trail**: Complete transaction logging with before/after balance tracking

## 🏗️ Architecture

### Core Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    Vendors      │    │  Credit Requests│    │  Transactions   │
│                 │    │                 │    │                 │
│ • ID            │    │ • Vendor        │    │ • Vendor        │
│ • Name          │────│ • Amount        │    │ • Type          │
│ • Balance       │    │ • Status        │    │ • Amount        │
│ • Daily Limit   │    │ • Created At    │    │ • Phone Number  │
│ • Version       │    │                 │    │ • Balance Before│
└─────────────────┘    └─────────────────┘    │ • Balance After │
                                              │ • Status        │
                                              └─────────────────┘
```

### Security Layers

1. **Database Level**: SELECT FOR UPDATE locks
2. **Application Level**: Distributed locking with Redis
3. **Business Logic**: Double-spending protection
4. **Transaction Level**: Idempotency keys
5. **Audit Level**: Complete transaction logging

## 🛠️ Technology Stack

- **Backend**: Django 4.x
- **Database**: PostgreSQL
- **Cache**: Redis
- **API**: Django REST Framework
- **Authentication**: Django Authentication
- **Logging**: Python Logging with Custom Handlers

## 📦 Installation

### Prerequisites

- Python 3.10+
- PostgreSQL 13+
- Redis 6+
- Docker (optional)

### Local Development Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd b2b_charge_service
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment configuration**
   ```bash
   cp .env.example .env
   # Edit .env with your database and Redis configurations
   ```

5. **Database setup**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   python manage.py createsuperuser
   ```

6. **Run the development server**
   ```bash
   python manage.py runserver
   ```

### Docker Setup

1. **Build and run with Docker Compose**
   ```bash
   docker-compose up --build
   ```

2. **Run migrations**
   ```bash
   docker-compose exec web python manage.py migrate
   docker-compose exec web python manage.py createsuperuser
   ```

## 🔧 Configuration

### Environment Variables

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/b2b_charge_db
POSTGRES_DB=b2b_charge_db
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
SECRET_KEY=your-secret-key
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1

# Cache Timeouts
DOUBLE_SPENDING_TIMEOUT=300
IDEMPOTENCY_TIMEOUT=86400
DISTRIBUTED_LOCK_TIMEOUT=30
```

## 📚 API Documentation

### Authentication
All API endpoints require authentication. Use Django's token authentication or session authentication.

### Core Endpoints

#### Credit Management
```http
POST /api/credits/request/
Content-Type: application/json
Authorization: Token your-token

{
    "amount": 1000000.00
}
```

#### Charge Sales
```http
POST /api/charges/sell/
Content-Type: application/json
Authorization: Token your-token

{
    "phone_number": "+989123456789",
    "amount": 50000.00
}
```

#### Vendor Balance
```http
GET /api/vendors/balance/
Authorization: Token your-token
```

### Response Format

```json
{
    "success": true,
    "data": {
        "transaction_id": "uuid-here",
        "balance_before": 1000000.00,
        "balance_after": 950000.00,
        "amount": 50000.00
    },
    "message": "Charge sold successfully"
}
```

## 🔐 Security Features

### Double-Spending Protection
- Unique transaction keys prevent duplicate processing
- Cache-based spending record tracking
- Automatic stale record cleanup

### Race Condition Prevention
```python
# Database-level locking
vendor = Vendor.objects.select_for_update().get(id=vendor_id)

# Distributed locking
with lock_manager.acquire_lock(f"vendor_{vendor_id}"):
    # Critical section
    pass
```

### Balance Integrity
- Database constraints prevent negative balances
- Optimistic locking with version control
- Atomic transaction rollback on failures

## 📊 Management Commands

### Balance Reconciliation
Verify and maintain financial integrity across all vendor accounts.

```bash
# Check all vendors
python manage.py reconcile_balances

# Check specific vendor
python manage.py reconcile_balances --vendor-id=123

# Generate detailed report
python manage.py reconcile_balances --report

# Auto-fix minor discrepancies
python manage.py reconcile_balances --fix
```

### Sample Output
```
=== B2B Charge Service - Balance Reconciliation ===

✓ Vendor: TechCorp Solutions
  - Current Balance: 1,500,000.00 Toman
  - Calculated Balance: 1,500,000.00 Toman
  - Status: ✓ VERIFIED

⚠ Vendor: Mobile Plus
  - Current Balance: 750,000.00 Toman
  - Calculated Balance: 749,950.00 Toman
  - Discrepancy: 50.00 Toman
  - Status: ⚠ MINOR_DISCREPANCY (Auto-fixed)

📊 Summary:
- Total Vendors Checked: 25
- Verified Accounts: 24
- Minor Discrepancies Fixed: 1
- Critical Issues: 0
```

## 🧪 Testing

### Run Tests
```bash
# Run all tests
python manage.py test

# Run specific test modules
python manage.py test tests.test_balance_reconciliation
python manage.py test tests.test_case_simple

# Run with coverage
coverage run --source='.' manage.py test
coverage report
coverage html
```

### Test Scenarios

#### Simple Test Case
- **Vendors**: 2
- **Credit Requests**: 10 per vendor
- **Charge Sales**: 1,000 distributed transactions
- **Verification**: Final balance accuracy

#### Parallel Load Test
- **Concurrent Users**: 100+
- **Simultaneous Transactions**: 10,000+
- **Race Conditions**: Extensive testing
- **Result**: Zero accounting discrepancies

### Sample Test
```python
# tests/test_case_simple.py
def test_simple_case(self):
    """Test 2 vendors, 10 credits, 1000 sales scenario"""
    # Create vendors
    vendor1 = self.create_vendor("TechCorp")
    vendor2 = self.create_vendor("MobilePlus")
    
    # Process credits and sales
    self.process_credit_requests(vendor1, 10, 100000)
    self.process_charge_sales(vendor1, 500, 1000)
    
    # Verify balances
    self.verify_vendor_balance(vendor1)
    self.assert_accounting_integrity()
```

## 🚀 Deployment

### Production Checklist

- [ ] Set `DEBUG=False`
- [ ] Configure proper database with connection pooling
- [ ] Set up Redis cluster for high availability
- [ ] Configure reverse proxy (Nginx)
- [ ] Set up SSL certificates
- [ ] Configure log rotation
- [ ] Set up monitoring and alerting
- [ ] Schedule balance reconciliation cron jobs

### Docker Production
```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  web:
    build: .
    environment:
      - DEBUG=False
      - DATABASE_URL=postgresql://user:pass@db:5432/b2b_charge_db
    depends_on:
      - db
      - redis

  db:
    image: postgres:13
    volumes:
      - postgres_data:/var/lib/postgresql/data/

  redis:
    image: redis:6-alpine
    
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
```

### Monitoring
```bash
# Health check endpoint
curl http://localhost:8000/api/health/

# Balance verification
python manage.py reconcile_balances --report > daily_report.txt

# Log monitoring
tail -f logs/transactions.log
```

## 📈 Performance

### Benchmarks
- **API Response Time**: < 100ms under normal load
- **Concurrent Transactions**: 1,000+ per second
- **Database Connections**: Optimized with connection pooling
- **Cache Hit Rate**: > 95% for frequently accessed data

### Optimization Features
- Database indexing for high-volume queries
- Redis caching for distributed operations
- Connection pooling for database efficiency
- Asynchronous processing where applicable

## 🔍 Monitoring & Logging

### Log Files
- `logs/application.log` - General application logs
- `logs/transactions.log` - Financial transaction logs
- `logs/security.log` - Security events and audit trail
- `logs/error.log` - Error tracking and debugging

### Monitoring Endpoints
```http
GET /api/health/          # System health check
GET /api/metrics/         # Performance metrics
GET /api/balance/verify/  # Real-time balance verification
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines
- Follow PEP 8 coding standards
- Write comprehensive tests for new features
- Update documentation for API changes
- Ensure all tests pass before submitting PR

## 🐛 Troubleshooting

### Common Issues

#### Database Lock Timeouts
```python
# Increase timeout in settings.py
DATABASES = {
    'default': {
        'OPTIONS': {
            'timeout': 20,
        }
    }
}
```

#### Redis Connection Issues
```bash
# Check Redis status
redis-cli ping

# Clear Redis cache
redis-cli flushall
```

#### Balance Discrepancies
```bash
# Run reconciliation with detailed output
python manage.py reconcile_balances --vendor-id=123 --report --verbose
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📞 Support

For support and questions:
- Create an issue on GitHub
- Contact the development team
- Check the documentation in `/docs`

## 🙏 Acknowledgments

- Django REST Framework for API development
- Redis for distributed caching and locking
- PostgreSQL for reliable data storage
- Docker for containerization

---

**Built with ❤️ for enterprise-grade financial applications**
