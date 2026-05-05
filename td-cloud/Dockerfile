FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# On copie tout le répertoire — en Phase 2 on ajoutera des fichiers
# (client HTML, templates, etc.) qui doivent aussi être dans l'image.
COPY . .
ENV PORT=8080
ENV EVENTLET_NO_GREENDNS=yes
ENV GRPC_DNS_RESOLVER=native
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--worker-class", "gthread", "--threads", "8", "--workers", "1", "--timeout", "0", "--keep-alive", "5", "main:app"]
