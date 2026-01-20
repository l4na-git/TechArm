# GitHub Actions 自動デプロイガイド

このドキュメントでは、GitHub Actions を使用して Tailscale 経由で自宅サーバーに自動デプロイする方法を説明します。

## 前提条件

1. **自宅サーバーの準備**
   - Tailscale がインストールされ、ネットワークに接続されていること
   - **Tailscale SSH が有効化されていること**（[設定方法](https://tailscale.com/kb/1193/tailscale-ssh)）
   - Python 3.11 と uv、Node.js がインストールされていること

2. **GitHub リポジトリの準備**
   - このプロジェクトが GitHub にプッシュされていること
   - リポジトリの Settings にアクセスできること

## Tailscale SSH の利点

このワークフローは **Tailscale SSH** を使用します：

✅ **SSH鍵管理が不要** - Tailscaleの認証を利用  
✅ **より安全** - Tailscaleのアクセス制御を活用  
✅ **シンプル** - セットアップが簡単

## セットアップ手順

### 1. Tailscale SSH の有効化

サーバー側で Tailscale SSH を有効化します：

```bash
# Tailscale SSH を有効化
sudo tailscale up --ssh
```

また、[Tailscale Admin Console](https://login.tailscale.com/admin/acls) の ACL で SSH アクセスを許可：

```json
{
  "ssh": [
    {
      "action": "accept",
      "src": ["tag:ci"],
      "dst": ["autogroup:self"],
      "users": ["autogroup:nonroot", "root"]
    }
  ]
}
```

### 2. Tailscale OAuth Client の作成

1. [Tailscale Admin Console](https://login.tailscale.com/admin/settings/oauth) にアクセス
2. "Generate OAuth Client" をクリック
3. 以下の設定を選択：
   - **Tags**: `tag:ci` を作成・選択
   - **Scopes**: `devices:write` を選択
4. Client ID と Client Secret を控える

### 3. GitHub Secrets の設定

GitHub リポジトリで **Settings > Secrets and variables > Actions** を開き、以下の Secrets を追加します：

#### デプロイ設定

| Secret 名 | 説明 | 例 |
|----------|------|-----|
| `TAILSCALE_OAUTH_CLIENT_ID` | Tailscale OAuth Client ID | `kxxxxxxxxx` |
| `TAILSCALE_OAUTH_SECRET` | Tailscale OAuth Client Secret | `tskey-client-kxxxxxxxxx` |
| `DEPLOY_HOST` | サーバーの Tailscale ホスト名または IP | `my-server` または `100.xxx.xxx.xxx` |
| `DEPLOY_USER` | SSH 接続用ユーザー名 | `ubuntu` |
| `DEPLOY_PATH` | デプロイ先のディレクトリパス | `/home/ubuntu/TechArm` |

#### 環境変数（6項目のみ！）

> [!NOTE]
> **Secretsは機密情報のみ！**
> 
> VOICEVOXのパラメータ、ASR設定などの非機密情報は `.env.example` ファイルで管理されます。
> GitHub Secretsへの登録は不要です。

`.env.example`ファイルで管理されている非機密情報と組み合わせて、以下の**機密情報のみ**をGitHub Secretsとして設定：

**API URL（Tailscale IPを含む）:**

| Secret 名 | 説明 | 例 |
|----------|------|-----|
| `ENV_OLLAMA_BASE_URL` | LLM の URL | `http://100.xxx.xxx.xxx:11434` |
| `ENV_VOICEVOX_BASE_URL` | VOICEVOX の URL | `http://100.xxx.xxx.xxx:50021` |
| `ENV_VISION_OFFLOAD_URL` | Vision Offload URL（オプション） | `http://100.xxx.xxx.xxx:8000` |
| `ENV_CONTROL_PANEL_URL` | Control Panel の URL | `http://100.xxx.xxx.xxx:3000` |

**モデル名:**

| Secret 名 | 説明 | 例 |
|----------|------|-----|
| `ENV_OLLAMA_MODEL` | LLM モデル名 | `deepseek-r1:7b` |

**デバイス固有情報:**

| Secret 名 | 説明 | 例 |
|----------|------|-----|
| `ENV_SO101_PORT` | SO-101 ポート | `/dev/ttyUSB0` |

> [!TIP]
> **非機密情報の変更方法**
> 
> VOICEVOXのパラメータやASR設定を変更したい場合:
> 1. `.env.example` ファイルを編集
> 2. Git に commit & push
> 3. 自動的にデプロイされます（Secretsの変更不要！）

### 4. サーバー側の準備

デプロイ先のディレクトリを作成：

```bash
mkdir -p /home/ubuntu/TechArm
mkdir -p /home/ubuntu/TechArm/logs
```

### 5. デプロイの実行

`main` ブランチに push すると、自動的にデプロイが実行されます：

```bash
git add .
git commit -m "Deploy to production"
git push origin main
```

GitHub Actions のタブでデプロイの進行状況を確認できます。

## デプロイの仕組み

1. **Tailscale 接続**: GitHub Actions ランナーが Tailscale ネットワークに接続
2. **環境変数生成**: GitHub Secrets から `.env` ファイルを生成
3. **ファイル転送**: rsync で効率的にファイルをサーバーに転送
4. **デプロイスクリプト実行**: サーバー上で `scripts/deploy.sh` を実行
   - 既存プロセスの停止
   - Python 依存関係のインストール
   - Control Panel のビルド
   - バックエンドとフロントエンドの起動

## トラブルシューティング

### デプロイが失敗する場合

1. **GitHub Actions ログを確認**
   - リポジトリの "Actions" タブで詳細なログを確認

2. **Tailscale SSH 接続を確認**
   ```bash
   # ローカルから Tailscale SSH 経由で接続できるか確認
   ssh user@tailscale-hostname
   # または
   ssh user@100.xxx.xxx.xxx
   ```

3. **サーバーのログを確認**
   ```bash
   tail -f logs/backend.log
   tail -f logs/frontend.log
   ```

### プロセスが起動しない場合

手動でプロセスを確認：

```bash
# バックエンドのプロセスを確認
ps aux | grep "python -m teacharm.main"

# フロントエンドのプロセスを確認
ps aux | grep "vite"

# プロセスを手動で停止
pkill -f "python -m teacharm.main"
pkill -f "vite"

# デプロイスクリプトを手動で実行
cd /path/to/TechArm
bash scripts/deploy.sh
```

## 手動でのサービス管理

### サービスの停止

```bash
pkill -f "python -m teacharm.main"
pkill -f "vite"
```

### サービスの起動

```bash
cd /path/to/TechArm
bash scripts/deploy.sh
```

### ログの確認

```bash
# リアルタイムでログを確認
tail -f logs/backend.log
tail -f logs/frontend.log

# 最新の100行を表示
tail -n 100 logs/backend.log
```

## 注意事項

- `.env` ファイルは Git リポジトリに含まれません（`.gitignore` で除外）
- デプロイ時に GitHub Secrets から自動生成されます
- SSH 秘密鍵は GitHub Secrets で安全に管理されます
- Tailscale OAuth Client は適切なタグとスコープで制限されています
