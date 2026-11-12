# 采析绘 crawler_workflow — Flask + Selenium 爬虫工作流
# 镜像基于 backend/ 构建；前端为原生 JS，由 Flask 同源提供（无独立前端容器）。
ARG BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
# Mirrors are a DEPLOYMENT choice, not a fact about this image: the default is the China mirror the
# operator uses, and CI overrides both with the upstream hosts it can reach. Hardcoding them made a
# `docker build` outside China fail at the first apt line, which is why the build had no CI job.
ARG APT_MIRROR=mirrors.cloud.aliyuncs.com
ARG PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
FROM $BASE_IMAGE

ARG APT_MIRROR
ARG PIP_INDEX

# 系统依赖：Chromium 浏览器 + chromedriver（版本由 apt 自动匹配）+ 中文字体（爬中文站需 CJK 字体）
# The suite is READ FROM THE IMAGE, never hardcoded. Pinning `trixie` sources onto a `bookworm`
# python:3.11-slim (which is what that tag resolved to until it moved) is a mixed-system apt: the
# package names, the chromium version and the driver pairing all come from an OS the image is not,
# and the failure lands at `apt-get install` with a dependency error nobody local can reproduce.
# `VERSION_CODENAME` is the fact; `debian.sources` is rewritten rather than appended so a newer base
# image's own mirror config cannot win.
RUN . /etc/os-release \
 && echo "deb http://${APT_MIRROR}/debian ${VERSION_CODENAME} main" > /etc/apt/sources.list \
 && echo "deb http://${APT_MIRROR}/debian ${VERSION_CODENAME}-updates main" >> /etc/apt/sources.list \
 && echo "deb http://${APT_MIRROR}/debian-security ${VERSION_CODENAME}-security main" >> /etc/apt/sources.list \
 && rm -f /etc/apt/sources.list.d/*.sources

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
 && .venv/bin/pip install --no-cache-dir --timeout 120 --retries 10 -i ${PIP_INDEX} -r requirements.txt

ENV PATH="/app/backend/.venv/bin:$PATH"

# 对外/对内绑定与数据根（数据落在挂载卷里，避免写入镜像层）
ENV HOST=0.0.0.0
ENV PORT=5000
ENV CRAWLER_DATA_ROOT=/app

EXPOSE 5000

# The process does not need root: only the directory ownership is fixed once, in the
# entrypoint (a named volume first mounted as root would otherwise refuse the app's writes).
RUN useradd --system --uid 10001 --create-home app \
 && mkdir -p /app/data /app/logs \
 && chown -R app:app /app/data /app/logs

# Matplotlib builds its font cache on FIRST IMPORT, and this image installs two CJK families
# (hundreds of faces). Doing it here, as the runtime user and with the same HOME the server will
# have, keeps that scan out of the first request instead of paying for it once per new container.
RUN mkdir -p /home/app/.config \
 && chown -R app:app /home/app/.config \
 && setpriv --reuid=app --regid=app --init-groups env HOME=/home/app \
      python -c "import matplotlib.font_manager as fm; fm.fontManager"

COPY deploy/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5000/api/config | grep -qE '200|302|401' || exit 1
ENTRYPOINT ["/app/docker-entrypoint.sh"]
