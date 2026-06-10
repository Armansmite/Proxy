FROM alpine:latest

# Install Tinyproxy (proxy) and Python (web panel)
RUN apk add --no-cache tinyproxy python3 py3-pip

# Install Flask for the web management
RUN pip3 install flask

# Copy our config generator and web app
COPY entrypoint.sh /entrypoint.sh
COPY app.py /app.py
COPY templates/ /templates/

RUN chmod +x /entrypoint.sh

# Tinyproxy will use port 8888, web panel on 8080
EXPOSE 8888 8080

ENTRYPOINT ["/entrypoint.sh"]
