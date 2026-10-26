import configparser
import os
import sys
import time

sys.path.insert(0, r"D:\openai")  # openai 库安装目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # 双击运行时保证读得到同目录 config.ini
from openai import OpenAI

TYPING_DELAY = 0.015  # 每个字符之间的间隔（秒），调大更慢、调小更快

cfg = configparser.ConfigParser()
cfg.read("config.ini", encoding="utf-8")
client = OpenAI(base_url=cfg["llm"]["base_url"], api_key=cfg["llm"]["api_key"])
messages = []

while True:
    try:
        prompt = input("Please input your prompt ")
    except (EOFError, KeyboardInterrupt):
        break
    print("--")
    messages.append({"role": "user", "content": prompt})
    answer = ""
    try:
        stream = client.chat.completions.create(
            model=cfg["llm"]["model"], messages=messages, stream=True
        )
        for chunk in stream:
            piece = chunk.choices[0].delta.content if chunk.choices else None
            if piece:
                answer += piece
                for ch in piece:
                    print(ch, end="", flush=True)
                    time.sleep(TYPING_DELAY)
        print()
    except KeyboardInterrupt:
        print()
        continue
    except Exception as e:
        print("Error:", e)
        messages.pop()
        continue
    messages.append({"role": "assistant", "content": answer})
