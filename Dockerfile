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
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install ODA File Converter
RUN curl -fsSL -o /tmp/oda.deb \
    'https://www.opendesign.com/guestfiles/get?filename=ODAFileConverter_QT6_lnxX64_8.3dll_27.1.deb' \
    && dpkg -i /tmp/oda.deb || apt-get install -f -y \
    && rm -f /tmp/oda.deb \
    || echo "ODA File Converter not available, DWG output will fallback to DXF"

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY frontend/ ./frontend_static/

RUN mkdir -p uploads outputs

EXPOSE 10000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
