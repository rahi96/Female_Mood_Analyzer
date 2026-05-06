# Pulse_E

AI-powered FastAPI application.

## Project Structure

```
pulse_e/
├── ai/
│   ├── models/          # AI/ML model definitions
│   ├── routes/          # API route modules
│   ├── services/        # Business logic & AI services
│   ├── utils/           # Utility helpers
│   ├── workflows/       # Workflow definitions
│   └── config.py        # Application configuration
├── .github/workflows/    # CI/CD pipelines
├── main.py              # FastAPI entry point
├── requirements.txt     # Python dependencies
├── Dockerfile           # Container image
└── docker-compose.yml   # Docker orchestration
```

## Getting Started

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn main:app --reload

# Run with Docker Compose
docker-compose up --build
```
