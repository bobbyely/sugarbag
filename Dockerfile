# Sugarbag: Python and nothing else. Built by compose; the database lives in the /data folder you mount.
FROM python:3.15-alpine
COPY sugarbag.py /app/sugarbag.py
COPY static /app/static
ENV SUGARBAG_BIND=0.0.0.0 SUGARBAG_DB=/data/sugarbag.db
WORKDIR /app
EXPOSE 8094
HEALTHCHECK --interval=60s --timeout=5s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8094/health', timeout=4)"
CMD ["python3", "/app/sugarbag.py"]
