# ── Stage 1: Base with C++ runtime deps ──────────────────────────────
FROM ubuntu:18.04 AS base
RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  libgd-dev libzzip-dev libopencv-highgui-dev libjsoncpp-dev \
  protobuf-compiler libprotobuf-dev libopencv-videoio-dev && \
  apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Stage 2: Build C++ reanimator + Go server ────────────────────────
FROM base AS builder
RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  build-essential cmake wget git software-properties-common && \
  add-apt-repository ppa:longsleep/golang-backports && \
  apt-get update && \
  apt-get install -y --no-install-recommends golang-go && \
  rm -rf /var/lib/apt/lists/*

# Clone the GIF engine repo
RUN git clone --depth 1 https://github.com/guitarbeat/makesweet-server.git /src

# Build YARP (C++ dependency)
RUN cd /tmp && \
  wget https://github.com/robotology/yarp/archive/v2.3.72.tar.gz && \
  tar xzvf v2.3.72.tar.gz && \
  mkdir /yarp && cd /yarp && \
  cmake -DSKIP_ACE=TRUE /tmp/yarp-* && make

# Build makesweet reanimator
RUN cd /src/makesweet && mkdir build && cd build && \
  cmake -DUSE_OPENCV=ON -DUSE_DETAIL=ON -DYARP_DIR=/yarp .. && \
  make VERBOSE=1

RUN echo "#!/bin/bash" > /reanimator && \
  echo "/makesweet/build/bin/reanimator \"\$@\"" >> /reanimator && \
  chmod u+x /reanimator

# Build Go server
RUN cd /src/server && go mod download && go build -o /server/start .

# ── Stage 3: Final runtime ───────────────────────────────────────────
FROM base

# Install Python 3 + curl
RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  software-properties-common curl && \
  add-apt-repository ppa:deadsnakes/ppa && \
  apt-get update && \
  apt-get install -y --no-install-recommends \
  python3.11 python3.11-venv python3.11-distutils && \
  curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 && \
  ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
  ln -sf /usr/bin/python3.11 /usr/bin/python && \
  apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy built binaries
COPY --from=builder /yarp/ /yarp/
COPY --from=builder /src/makesweet/build/ /makesweet/build/
COPY --from=builder /reanimator /reanimator
COPY --from=builder /server/start /server/start

# Copy GIF templates
COPY --from=builder /src/makesweet/templates/ /makesweet/templates/

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy bot + startup script
COPY bot.py /app/bot.py
COPY start.sh /start.sh
RUN chmod +x /start.sh

RUN mkdir -p /makesweet/images

WORKDIR /app
ENTRYPOINT ["/start.sh"]
