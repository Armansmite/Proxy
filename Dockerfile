FROM alpine:latest

RUN wget -O /tmp/gost.gz \
      https://github.com/ginuerzh/gost/releases/download/v3.0.0-rc8/gost-linux-amd64-3.0.0-rc8.gz && \
    gunzip /tmp/gost.gz && \
    mv /tmp/gost /usr/local/bin/gost && \
    chmod +x /usr/local/bin/gost

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
