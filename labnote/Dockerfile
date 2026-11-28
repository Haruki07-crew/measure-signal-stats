# labnote の Discord bot を Docker で動かす（任意。Raspberry Pi・Azure の VM 共通。docs/docker.md）
# 使い方：docker compose -f deploy/docker/compose.yaml up -d --build
# トークンは .env に書き、イメージには入れない（.dockerignore で除外）。

# 版は執筆時（2026年11月）のもの。上げるときは公式の変更履歴を読んでから（要確認）
FROM ghcr.io/astral-sh/uv:0.13.5 AS uv
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app

# 先に依存だけを入れる（コードを直しても、ここはキャッシュが効く）。uv.lock どおりの版に固定
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --extra bot --no-dev --no-install-project

COPY labnote ./labnote
RUN uv sync --locked --extra bot --no-dev \
 && rm /usr/local/bin/uv

# 記録の置き場所（compose.yaml で手元のフォルダをここにつなぐ）。.env はコンテナの中では読まない
ENV PATH=/app/.venv/bin:$PATH \
    LABNOTE_HOME=/data \
    LABNOTE_ENV_FILE=/nonexistent
VOLUME ["/data"]

# root では動かさない（compose.yaml の user: で、手元のユーザーの UID に合わせる）
USER 10001:10001
ENTRYPOINT ["labnote-bot"]
