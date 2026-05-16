FROM python:3.11-slim

WORKDIR /app

# Install system dependencies + ODA File Converter dependencies
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
    && rm -rf /var/lib/apt/lists/*

# Install ODA File Converter from local deb
COPY ODAFileConverter.deb /tmp/ODAFileConverter.deb
RUN apt-get update && dpkg -i /tmp/ODAFileConverter.deb || apt-get install -f -y \
    && rm -f /tmp/ODAFileConverter.deb \
    && rm -rf /var/lib/apt/lists/*

# Find and set Qt plugin path from ODA installation
RUN QT_DIR=$(find /usr -path "*/ODAFileConverter*/plugins" -type d 2>/dev/null | head -1) \
    && echo "QT plugins found at: $QT_DIR" \
    && if [ -n "$QT_DIR" ]; then echo "$QT_DIR" > /etc/oda_qt_path; fi

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY frontend/ ./frontend_static/

RUN mkdir -p uploads outputs

ENV QT_QPA_PLATFORM=offscreen

EXPOSE 10000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
