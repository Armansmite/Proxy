FROM python:3.11-alpine
RUN pip install flask
COPY app.py /app.py
EXPOSE 8080
CMD ["python", "/app.py"]
