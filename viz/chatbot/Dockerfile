FROM python:3.10-slim

WORKDIR /app

COPY chatbot/requirements.txt /tmp/chatbot-requirements.txt
COPY chatbot/requirements-test.txt /tmp/requirements-test.txt
RUN pip install --no-cache-dir -r /tmp/chatbot-requirements.txt

COPY __init__.py /app/viz/__init__.py
COPY chatbot /app/viz/chatbot

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "viz.chatbot.app:app", "--host", "0.0.0.0", "--port", "8000"]
