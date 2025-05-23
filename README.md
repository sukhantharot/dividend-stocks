# Thai Stock Dividend API

A FastAPI application that scrapes dividend information from Settrade for Thai stocks.

## Features

- Scrapes dividend information from Settrade website
- Caches results in Redis for 5 minutes
- Uses Playwright for JavaScript rendering
- BeautifulSoup for HTML parsing
- Docker and docker-compose support
- Environment variable configuration

## Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)

## Environment Configuration

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Edit `.env` file with your configuration:
```env
# Redis Configuration
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_USERNAME=default
REDIS_PASSWORD=your_redis_password

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000

# Cache Configuration
CACHE_EXPIRY=300  # 5 minutes in seconds
```

## Running with Docker Compose

1. Clone the repository
2. Configure your environment variables
3. Run the following command:
```bash
docker-compose up --build
```

The API will be available at `http://localhost:8000`

## API Usage

### Get Dividend Information

```
GET /dividends?symbol={stock_symbol}
```

Example:
```
GET /dividends?symbol=banpu
```

Response:
```json
{
    "symbol": "banpu",
    "dividends": [
        {
            "date": "2023-11-15",
            "type": "เงินปันผล",
            "value": "1.00",
            "payment_date": "2023-12-15"
        }
    ],
    "timestamp": 1700000000
}
```

## Local Development

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:
```bash
playwright install
```

4. Run the application:
```bash
uvicorn app:app --reload
```

## Error Handling

The API will return appropriate HTTP status codes:
- 200: Success
- 404: Symbol not found or dividend table not found
- 500: Server error or scraping error 