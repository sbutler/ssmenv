FROM python:3.8-alpine

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ssmenv.py ./
COPY *.md ./

CMD [ "python", "/usr/src/app/ssmenv.py" ]

VOLUME /ssmenv

ENV OUTPUT /ssmenv/environment