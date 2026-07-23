FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt ./

RUN python -m pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium --with-deps

COPY . .

CMD ["python", "bot.py"]
