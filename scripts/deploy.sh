#!/bin/bash
set -e

echo "🚀 Starting deployment..."

# デプロイ先のディレクトリに移動
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "📂 Current directory: $PROJECT_DIR"

# 既存のプロセスを停止
echo "🛑 Stopping existing processes..."
stop_pid() {
    local pid_file="$1"
    local label="$2"
    if [ -f "$pid_file" ]; then
        local pid
        pid="$(cat "$pid_file")"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "Stopping $label (PID: $pid)..."
            kill "$pid" || true
            sleep 1
            if kill -0 "$pid" 2>/dev/null; then
                echo "$label did not stop, sending SIGKILL..."
                kill -9 "$pid" || true
            fi
        fi
        rm -f "$pid_file"
    fi
}

stop_pid ".backend.pid" "backend"
stop_pid ".frontend.pid" "frontend"
sleep 2

# Python環境のセットアップ
echo "🐍 Setting up Python environment..."
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Control Panelのビルド
echo "⚛️  Building Control Panel..."
cd control-panel
if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm install
fi
npm run build
cd ..

# バックエンドを起動（バックグラウンド）
echo "🚀 Starting FastAPI backend..."
mkdir -p logs
nohup python -m teacharm.main > logs/backend.log 2>&1 &
echo $! > .backend.pid
echo "Backend PID: $(cat .backend.pid)"

# Control Panelを起動（バックグラウンド）
echo "🎨 Starting Control Panel..."
cd control-panel
CONTROL_PANEL_HOST="${CONTROL_PANEL_HOST:-127.0.0.1}"
nohup npm run preview -- --host "$CONTROL_PANEL_HOST" > ../logs/frontend.log 2>&1 &
echo $! > ../.frontend.pid
cd ..
echo "Frontend PID: $(cat .frontend.pid)"

echo "✅ Deployment completed successfully!"
echo ""
echo "Services status:"
echo "  Backend PID: $(cat .backend.pid)"
echo "  Frontend PID: $(cat .frontend.pid)"
echo ""
echo "Logs:"
echo "  Backend: $PROJECT_DIR/logs/backend.log"
echo "  Frontend: $PROJECT_DIR/logs/frontend.log"
