FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY manga_bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py /app/
COPY manga_bot /app/manga_bot
COPY narration_style.txt /app/
COPY reference/style-calibration.json /app/reference/style-calibration.json
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python","-m","manga_bot.worker"]
CMD ["--config","/job/config.json"]
