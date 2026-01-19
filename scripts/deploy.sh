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
pkill -f "python -m teacharm.main" || true
pkill -f "vite" || true
sleep 2

# Python環境のセットアップ
echo "🐍 Setting up Python environment..."
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    UV_PYTHON_PREFERENCE=managed uv venv --python 3.11
fi

source .venv/bin/activate
echo "Installing Python dependencies..."
uv pip install -r requirements.txt

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
nohup python -m teacharm.main > logs/backend.log 2>&1 &
echo $! > .backend.pid
echo "Backend PID: $(cat .backend.pid)"

# Control Panelを起動（バックグラウンド）
echo "🎨 Starting Control Panel..."
cd control-panel
nohup npm run preview > ../logs/frontend.log 2>&1 &
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
