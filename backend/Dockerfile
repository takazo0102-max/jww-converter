FROM python:3.11-slim

WORKDIR /app

# Install ODA File Converter dependencies (for DXF->DWG conversion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libfontconfig1 \
    libxrender1 \
    libxcb1 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# ODA File Converter must be manually downloaded from https://www.opendesign.com/guestfiles/oda_file_converter
# and placed as ODAFileConverter_QT6_lnxX64_8.3dll_25.3.deb (or similar) in the build context.
# Uncomment below if you have the .deb file:
# COPY ODAFileConverter*.deb /tmp/
# RUN dpkg -i /tmp/ODAFileConverter*.deb || apt-get install -f -y && rm /tmp/ODAFileConverter*.deb

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy frontend into backend for static file serving
COPY ../frontend /app/frontend_static
# Fallback: if COPY fails due to context, frontend is expected at /app/../frontend

RUN mkdir -p uploads outputs

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
