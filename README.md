# AIしりとり (Flask + Gemini)

Gemini API と対戦できる日本語「しりとり」Webアプリです。Render.com にデプロイ可能な構成。

## 機能
- 難易度: やさしい / ふつう / むずかしい
- かな正規化、重複禁止、語尾「ん」禁止
- Gemini API を用いた AI 手番（失敗時はフォールバック語彙）
- シンプルな和モダンUI

## 環境変数
- `GEMINI_API_KEY`: Google Generative AI のAPIキー（必須）
- `FLASK_SECRET_KEY`: Flaskセッション鍵（任意/推奨）

## ローカル実行（Windows）
```powershell
# 1) 仮想環境（任意）
python -m venv .venv
.\.venv\Scripts\activate

# 2) 依存関係
pip install -r requirements.txt

# 3) 環境変数
$env:GEMINI_API_KEY = "YOUR_API_KEY"
$env:FLASK_SECRET_KEY = "dev-secret"

# 4) 起動
python app.py
# ブラウザで http://localhost:5000
```

## デプロイ（Render.com）
1. 本リポジトリを GitHub へプッシュ。
2. Render で New + Web Service。
3. Runtime: Python。Build Command: `pip install -r requirements.txt`。
4. Start Command: `gunicorn app:app`。
5. 環境変数に `GEMINI_API_KEY`, `FLASK_SECRET_KEY` を設定。

## ライセンス
MIT
