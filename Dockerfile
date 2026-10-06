FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# APP_ENV=production exige SECRET_KEY própria e cookie de login só por HTTPS
ENV PORT=8080 FLASK_APP=run.py APP_ENV=production
EXPOSE 8080

# "flask db upgrade" cria/atualiza as tabelas sem apagar dados. Roda na partida
# (e não como release_command do Fly) porque só aqui o volume do banco está montado.
CMD ["sh", "-c", "flask db upgrade && exec gunicorn run:app --bind 0.0.0.0:8080 --workers 2"]
