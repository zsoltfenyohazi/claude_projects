FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Amsterdam
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alfred ./alfred
RUN useradd --create-home alfred && mkdir -p /app/data && chown alfred /app/data
USER alfred
EXPOSE 8000
CMD ["uvicorn", "alfred.main:api", "--host", "0.0.0.0", "--port", "8000"]
