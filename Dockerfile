FROM python:3.11-slim

WORKDIR /app

# Install system dependencies + ODA/Qt/Xvfb dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libfontconfig1 \
    libxrender1 \
    libxcb1 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-render-util0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    libdbus-1-3 \
    libxcb-cursor0 \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libxcb-randr0 \
    libxcb-sync1 \
    libxcb-shm0 \
    libxcb-util1 \
    libxcb-glx0 \
    libsm6 \
    libice6 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Install ODA File Converter from local deb
COPY ODAFileConverter.deb /tmp/ODAFileConverter.deb
RUN apt-get update && dpkg -i /tmp/ODAFileConverter.deb || apt-get install -f -y \
    && rm -f /tmp/ODAFileConverter.deb \
    && rm -rf /var/lib/apt/lists/*

# Use xcb via Xvfb (not offscreen - ODA doesn't bundle offscreen plugin)
ENV QT_PLUGIN_PATH=/usr/bin/ODAFileConverter_27.1.0.0/plugins
ENV DISPLAY=:99

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY frontend/ ./frontend_static/

RUN mkdir -p uploads outputs

EXPOSE 10000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
