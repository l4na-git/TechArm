# TeachArm プロトタイプ実行環境

本リポジトリは、TeachArm 展示デモのための FastAPI ベース実行環境と、管理 UI（Control Panel）をまとめたものです。`docs/` 以下の仕様書に沿って、Vision/Mapping/Dialogue/Arm を統合するサーバと、監視・手動操作用の React UI を提供します。

## 構成

- `teacharm/` – FastAPI サーバ側の Python パッケージ。設定読み込み、教材・スクリプト処理、各サービス stub を含む。
- `config/` – Arm 安全領域や VOICEVOX パラメータ、9 点キャリブレーションなどの JSON/YAML。
- `materials/` – 教材 A/B の領域定義ファイル。
- `scripts/common.yaml` – 先生ロール・台本コマンド・ネガティブルール。
- `.env.example` – 環境変数テンプレート（Tailscale IP、Ollama/VOICEVOX URL 等）。
- `control-panel/` – React + Vite 製のコントロールパネル UI。

## クイックスタート（サーバ側）

TeachArm サーバは Python 3.11 + [uv](https://github.com/astral-sh/uv) を推奨。Python バージョンは `pyproject.toml` の `requires-python` に固定している。

```bash
UV_PYTHON_PREFERENCE=managed uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env  # Tailscale IP などを実値で記入
python -m teacharm.main
```

デフォルトで `http://0.0.0.0:8000` で待ち受けます。主なエンドポイント：

- `GET /health`
- `GET /api/materials`
- `POST /api/materials/select`
- `POST /api/events/pointer`
- `POST /api/dialogue`
- `POST /api/arm/move`
- `POST /api/arm/safe_pose`
- `GET /api/state`

### 設定チェックリスト

- `.env`：Tailscale IP、Ollama モデル名、Control Panel URL を実値にする。
- `config/arm_limits.json`：so-101 の安全領域・Safe Pose を測定値で設定。
- `config/arm_calibration.json`：9 点 (u,v)→(x,y,z) を入力。
- `materials/material_*.json`：教材領域（question/line）を実データで記入。
- `config/voicevox_params.yaml`：VOICEVOX の話速/抑揚などを調整（必要に応じて）。

現時点では Vision/Arm 実装にスタブを含んでおり、ログ出力で動作を確認できます。実機が揃い次第、該当サービスを差し替えてください。

## Control Panel（React UI）

`control-panel/` ディレクトリにあるコントロールパネルは Node.js が必要です。

```bash
cd control-panel
npm install
npm run dev
```

デフォルトでは `http://localhost:8000` のサーバに接続します。別ホストへ向ける場合は `VITE_TEACHARM_API_URL` を指定してください。

```bash
VITE_TEACHARM_API_URL=http://100.xxx.xxx.xxx:8000 npm run dev
```

UI 上で以下の操作が可能です：

- サーバヘルスの確認
- 教材選択の切り替え
- 手動のポインタイベント送信（`on_point` / `on_help`）
- ダイアログテキスト送信（LLM / 台本呼び出し）
- アーム座標指定・Safe Pose 戻し
- ログの時系列確認
- `scripts/common.yaml` の内容編集（YAML エディタで直接保存可能）

Control Panel は Tailscale 内でのみ公開し、`.env` の `CONTROL_PANEL_URL` にブラウザでアクセスする URL を記入してください。
