FROM docker.io/library/python@sha256:37fc60d303cb9294d3718b5b48998a0210bb1c73611c1399ef5eb7964c0536e5
WORKDIR /app
COPY --chmod=0444 requirements-runtime.lock .
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-runtime.lock
COPY src/radea /app/radea
# Local lab source can be staged under a restrictive umask.
RUN chmod -R a+rX /app/radea
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
ENTRYPOINT ["python", "-c", "from radea.cli import main; main()"]
