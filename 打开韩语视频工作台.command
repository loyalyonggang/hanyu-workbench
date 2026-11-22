#!/bin/zsh
set -eu
cd -- "${0:A:h}/workbench"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
port="${WORKBENCH_PORT:-8790}"
url="http://127.0.0.1:$port/"
if curl -fsS --max-time 2 "$url" | grep -q 'workbench-token'; then
    open "$url"
    exit
fi
if ! command -v uv >/dev/null; then
    print '请先安装 uv，再打开工作台。'
    exit 1
fi
if ! curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
    if command -v ollama >/dev/null; then
        mkdir -p data
        ollama serve > data/ollama.log 2>&1 &
    fi
fi
(
    for attempt in {1..90}; do
        if curl -fsS --max-time 1 "$url" 2>/dev/null | grep -q 'workbench-token'; then
            open "$url"
            exit
        fi
        sleep 1
    done
) &
exec uv run --python 3.12 --with-requirements requirements.txt python app.py
