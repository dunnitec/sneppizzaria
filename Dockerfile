FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# APP_ENV=production exige SECRET_KEY própria e cookie de login só por HTTPS
ENV PORT=8080 FLASK_APP=run.py APP_ENV=production
EXPOSE 8080

CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:8080"]
