# syntax=docker/dockerfile:1
# Bulut servisleri — üretim imajı. Aynı imaj üç süreç olarak çalışır:
#
#   ati-cloud-api   --host 0.0.0.0 --port 8000   hesap, lisans, ödeme, yönetim API'si (varsayılan)
#   ati-cloud-relay --host 0.0.0.0 --port 8765   iPhone ↔ masaüstü aktarma (WebSocket)
#   ati-cloud-migrate                            veritabanı geçişleri (her dağıtımdan önce bir kez)
#
# Ayarlar ve gizli bilgiler çalışma anında ortam değişkeni olarak verilir (deploy/cloud.env.example);
# imaja gizli bilgi girmez. Süreç root olmayan kullanıcıyla çalışır.

FROM python:3.13.9-slim-bookworm AS build
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13.9-slim-bookworm
RUN useradd --system --uid 10001 --no-create-home ati
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER ati
# Sağlık denetimi platformun yük dengeleyicisinden yapılır: API /health (canlılık) ve /ready
# (veritabanı + şema), aktarma servisi /health.
EXPOSE 8000 8765
CMD ["ati-cloud-api", "--host", "0.0.0.0", "--port", "8000"]
