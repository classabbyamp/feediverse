FROM python:3.14-alpine

WORKDIR /app
RUN apk add tini && python3 -m venv /env

COPY run.sh /run.sh
COPY feediverse.py pyproject.toml README.md .

RUN chmod +x /run.sh && /env/bin/pip install /app

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/run.sh"]
