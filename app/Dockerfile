# store-pos: standard library only, on the SUSE BCI Python base
FROM registry.suse.com/bci/python:3.12
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} PYTHONUNBUFFERED=1
WORKDIR /app
COPY app.py .
USER 1000:1000
EXPOSE 8080
HEALTHCHECK CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"
CMD ["python3", "/app/app.py"]
