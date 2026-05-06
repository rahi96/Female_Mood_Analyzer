# Deployment Guide

## Docker Deployment

Build and push the Docker image:

```bash
docker build -t pulse_e:latest .
docker push <registry>/pulse_e:latest
```

## Environment Variables

Create a `.env` file with the required variables:

```env
APP_NAME=Pulse_E
APP_VERSION=1.0.0
DEBUG=false
```

## GitHub Actions

The CI/CD pipeline is defined in `.github/workflows/deploy.yml`.
It triggers on pushes to the `main` branch.
