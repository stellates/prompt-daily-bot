import os
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai.errors import ServerError
from notion_client import Client

# -----------------------
# 初期設定
# -----------------------
load_dotenv()

USE_LOCAL = os.getenv("USE_LOCAL_REPORT") == "true"

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

client = genai.Client(api_key=GEMINI_API_KEY)
notion = Client(auth=NOTION_TOKEN)

# -----------------------
# Slack送信
# -----------------------
def post_to_slack(blocks):
    payload = {
        "text": "SESプロンプト配信",
        "blocks": blocks
    }
    res = requests.post(SLACK_WEBHOOK, json=payload)
    if res.status_code != 200:
        raise Exception(res.text)

# -----------------------
# Gemini（リトライ付き）
# -----------------------
def generate_text(prompt, max_retry=3):
    for i in range(max_retry):
        try:
            res = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            return res.text.strip()

        except ServerError:
            if i == max_retry - 1:
                raise

            wait = 2 ** i
            print(f"503リトライ {i+1}/{max_retry} ({wait}s)")
            time.sleep(wait)

# -----------------------
# JSON安全処理
# -----------------------
def safe_json_load(text):
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1])
    return json.loads(text)

# -----------------------
# ローカル読み込み
# -----------------------
def load_local_report():
    with open("report.json", encoding="utf-8") as f:
        return json.load(f)

# -----------------------
# レポート生成
# -----------------------
def get_report(prompt):
    text = generate_text(prompt)
    return safe_json_load(text)

# -----------------------
# 類似チェック
# -----------------------
def check_similarity(report, backnumbers, prompt):
    input_text = f"""
{prompt}

新規report:
{json.dumps(report, ensure_ascii=False)}

backnumber:
{json.dumps(backnumbers, ensure_ascii=False)}
"""
    text = generate_text(input_text)
    return safe_json_load(text)

# -----------------------
# Notion保存
# -----------------------
def save_to_notion(report):
    title = report[1]["text"]["text"]

    content = "\n\n".join([
        b["text"]["text"]
        for b in report if b["type"] == "section"
    ])

    print(notion.databases.retrieve(database_id=NOTION_DATABASE_ID))

    notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties={
            "Name": {
                "title": [{"text": {"content": title}}]
            },
            "Date": {
                "date": {"start": datetime.now().isoformat()}
            },
            "Content": {
                "rich_text": [
                    {"text": {"content": content[:2000]}}
                ]
            }
        }
    )

# -----------------------
# Block整形
# -----------------------
def build_blocks(report):
    blocks = []

    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "🚀 本日のプロンプトテクニック（SES実務向け）",
            "emoji": True
        }
    })

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "生成AIを使う上で、プロンプトの書き方は重要です。\nこの配信では毎日、SES現場でそのまま使えるテクニックを紹介します。"
        }
    })

    blocks.append({"type": "divider"})
    blocks.extend(report)

    return blocks

# -----------------------
# メイン
# -----------------------
def main():
    with open("trick_make.prompt", encoding="utf-8") as f:
        make_prompt = f.read()

    with open("check.prompt", encoding="utf-8") as f:
        check_prompt = f.read()

    # -----------------------
    # モード分岐（重要）
    # -----------------------
    if USE_LOCAL:
        print("LOCAL MODE")
        report = load_local_report()
        similarity = None

    else:
        print("GEMINI MODE")
        backnumbers = []
        report = get_report(make_prompt)
        similarity = check_similarity(report, backnumbers, check_prompt)

    blocks = build_blocks(report)

    # 類似注釈
    if similarity and similarity.get("is_similar"):
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"※過去（{similarity['similar_date']}）にも類似テーマあり"
            }
        })

    post_to_slack(blocks)

    # Notion保存
    save_to_notion(report)

    print("完了")

if __name__ == "__main__":
    main()