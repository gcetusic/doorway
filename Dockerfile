FROM python:3.7

RUN apt-get update

COPY ./requirements/ /app/etc/requirements
RUN pip install --requirement /app/etc/requirements/base.txt

COPY ./gateway.py /gateway.py

WORKDIR /

ENTRYPOINT ["gunicorn", "gateway:app", "--bind", "localhost:8080", "--worker-class", "aiohttp.GunicornWebWorker", "--workers", "8"]
