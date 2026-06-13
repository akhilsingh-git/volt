# Volt recommender service.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# internal_auth_required checks X-CLIENT-ID / X-CLIENT-SECRET against these.
ENV CLIENT_ID=volt-local
ENV CLIENT_SECRET=volt-local-secret

EXPOSE 5000
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "1", "app:app"]
