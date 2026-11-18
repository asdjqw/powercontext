FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BRIDGE_PORT=8099 \
    BRIDGE_DATA=/data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
RUN mkdir -p /data

EXPOSE 8099
VOLUME ["/data"]
CMD ["python", "app.py"]
