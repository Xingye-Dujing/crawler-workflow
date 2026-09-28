# 采析绘 crawler_workflow — Flask + Selenium 爬虫工作流
# 镜像基于 backend/ 构建；前端为原生 JS，由 Flask 同源提供（无独立前端容器）。
FROM python:3.11-slim

# 系统依赖：Chromium 浏览器 + chromedriver（版本由 apt 自动匹配）+ 中文字体（爬中文站需 CJK 字体）
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      chromium \
      chromium-driver \
      fonts-wqy-zenhei \
      fonts-noto-cjk \
      curl \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Selenium 在 Linux 下通过这两个设置找到浏览器与驱动（crawlers/base.py 使用 driver_path）
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV CHROME_BIN=/usr/bin/chromium

WORKDIR /app
COPY backend/ /app/backend/
WORKDIR /app/backend

# 项目 venv（AGENTS.md 强制要求 .venv，且不可使用系统 Python）
RUN python -m venv .venv \
 && .venv/bin/pip install --no-cache-dir --upgrade pip \
 && .venv/bin/pip install --no-cache-dir -r requirements.txt

ENV PATH="/app/backend/.venv/bin:$PATH"

# 对外/对内绑定与数据根（数据落在挂载卷里，避免写入镜像层）
ENV HOST=0.0.0.0
ENV PORT=5000
ENV CRAWLER_DATA_ROOT=/app

EXPOSE 5000

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
