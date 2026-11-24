FROM registry.k8s.io/kubectl@sha256:5ed410ebac5dc976cc717098994dcdb29bbbd38f6bd65f582311f5be4ba719cf AS client
FROM docker.io/library/python@sha256:37fc60d303cb9294d3718b5b48998a0210bb1c73611c1399ef5eb7964c0536e5
COPY --from=client /bin/kubectl /usr/local/bin/kubectl
WORKDIR /app
COPY --chmod=0444 k8s_message_controller.py .
USER 10001:10001
ENTRYPOINT ["python", "-B", "k8s_message_controller.py"]
