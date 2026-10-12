FROM python:3.13-slim-trixie
ARG BRANCH_NAME=master
ENV BRANCH_NAME=${BRANCH_NAME}
ENV TINI_VERSION=v0.19.0
ENV KOMETA_DOCKER=True
ARG TARGETARCH
ARG TARGETVARIANT
COPY requirements.txt requirements.txt
RUN echo "**** install system packages ****" \
 && apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y tzdata --no-install-recommends \
 && apt-get install -y gcc g++ libxml2-dev libxslt-dev libz-dev libjpeg62-turbo-dev zlib1g-dev wget curl ffmpeg libsm6 libxext6 \
 && wget -O /tini https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini-"$(dpkg --print-architecture | awk -F- '{ print $NF }')" \
 && chmod +x /tini \
 && if [ "$TARGETARCH" = "arm" ] && [ "$TARGETVARIANT" = "v7" ]; then export PIP_EXTRA_INDEX_URL=https://www.piwheels.org/simple; apt-get install -y --no-install-recommends libopenblas0 libwebpdemux2 libavif16 libopenexr-3-1-30; fi \
 && pip3 install --no-cache-dir --upgrade --prefer-binary --requirement /requirements.txt \
 && apt-get --purge autoremove gcc g++ libxml2-dev libxslt-dev libz-dev -y \
 && apt-get clean \
 && apt-get update \
 && apt-get check \
 && apt-get -f install \
 && apt-get autoclean \
 && rm -rf /requirements.txt /tmp/* /var/tmp/* /var/lib/apt/lists/*
COPY . /
VOLUME /config
ENTRYPOINT ["/tini", "-s", "python3", "overlay_reset.py", "--"]
