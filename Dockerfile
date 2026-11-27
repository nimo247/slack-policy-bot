FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY policy_bot ./policy_bot
COPY examples/sample-lab-notice.pdf ./examples/
RUN useradd --uid 10001 --no-create-home app
USER app
CMD ["python", "-m", "policy_bot"]
