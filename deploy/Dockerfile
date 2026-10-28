# 采析绘 crawler_workflow — Flask + Selenium 爬虫工作流
# 镜像基于 backend/ 构建；前端为原生 JS，由 Flask 同源提供（无独立前端容器）。
ARG BASE_IMAGE=mirror.ccs.tencentyun.com/library/python:3.11-slim
FROM $BASE_IMAGE

# 系统依赖：Chromium 浏览器 + chromedriver（版本由 apt 自动匹配）+ 中文字体（爬中文站需 CJK 字体）
RUN echo 'deb http://mirrors.tencentyun.com/debian trixie main' > /etc/apt/sources.list \
 && echo 'deb http://mirrors.tencentyun.com/debian trixie-updates main' >> /etc/apt/sources.list \
 && echo 'deb http://mirrors.tencentyun.com/debian-security trixie-security main' >> /etc/apt/sources.list

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      chromium \
      chromium-driver \
      fonts-wqy-zenhei \
      fonts-noto-cjk \
      curl \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Browser and driver, both by explicit path. ``CHROME_BIN``/``CHROME_PATH`` are read by
# utils/machine_deps (the one Chrome probe the crawler and the launcher share); ``CIXI_DRIVER_PATH`` is
# the name backend/config.py actually reads — the image used to export CHROMEDRIVER_PATH, which nothing
# looked at, so the deploy knob was decoration.
ENV CHROME_BIN=/usr/bin/chromium
ENV CIXI_DRIVER_PATH=/usr/bin/chromedriver

# The program's log lines and node names are Chinese, and a slim image starts with no locale: a C/ASCII
# stdout raises UnicodeEncodeError inside the logging handler, which swallows it, so the line simply
# vanishes. UTF-8 mode plus a UTF-8 locale is the container's own answer; backend/app.py also pins the
# streams at import for anyone who runs this image with LANG overridden.
ENV PYTHONUTF8=1
ENV LANG=C.UTF-8

WORKDIR /app
COPY requirements.txt /app/backend/requirements.txt
COPY backend/ /app/backend/
WORKDIR /app/backend

# 项目 venv（AGENTS.md 强制要求 .venv，且不可使用系统 Python）
RUN python -m venv .venv \
 && .venv/bin/pip install --no-cache-dir --upgrade pip \
 && .venv/bin/pip install --no-cache-dir -i https://mirrors.tencentyun.com/pypi/simple/ -r requirements.txt

ENV PATH="/app/backend/.venv/bin:$PATH"

# 对外/对内绑定与数据根（数据落在挂载卷里，避免写入镜像层）
ENV HOST=0.0.0.0
ENV PORT=5000
ENV CRAWLER_DATA_ROOT=/app

EXPOSE 5000

COPY deploy/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
