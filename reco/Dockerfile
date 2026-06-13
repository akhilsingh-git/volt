# turing / clips-reco (local). Original k8s/Dockerfile pulled trained models
# from S3; here we seed synthetic models at startup and run unmodified.
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Seed synthetic models, then serve. internal_auth_required checks
# X-CLIENT-ID / X-CLIENT-SECRET against CLIENT_ID / CLIENT_SECRET env.
ENV CLIENT_ID=volt-local
ENV CLIENT_SECRET=volt-local-secret
ENV LOG_FILE_PATH=/tmp/app.log

EXPOSE 5000
CMD ["sh", "-c", "python seed_models.py && gunicorn -b 0.0.0.0:5000 -w 1 app:app"]
