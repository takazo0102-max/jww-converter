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
RUN dpkg -i /tmp/ODAFileConverter.deb || apt-get update && apt-get install -f -y \
    && rm -f /tmp/ODAFileConverter.deb

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY frontend/ ./frontend_static/

RUN mkdir -p uploads outputs

EXPOSE 10000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
