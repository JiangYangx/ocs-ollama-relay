"""
图片题真实链路自测（需要真实的云端 key 或本地视觉模型）。

用途：v1.1.0 的图片题路由逻辑在开发时只用 mock 验证过请求构造，
没有跑过真实厂商。此脚本用一张真实生成的图片走完整链路，
确认 vision_model 真的"看懂"了图。

用法：
  # 云端（智谱，GLM-4V-Flash 免费）
  python tools/test_vision.py --backend openai \
      --api-base https://open.bigmodel.cn/api/paas/v4 \
      --api-key sk-xxxx --vision-model glm-4v-flash

  # 本地 Ollama（需先 ollama pull qwen2.5vl:7b 或 llava）
  python tools/test_vision.py --backend ollama --vision-model qwen2.5vl:7b

判定：程序会生成一张"红底白色大写字母 JY"的图，若模型回答里
包含 JY 字样即视为视觉链路通过。
"""
import argparse
import base64
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 不依赖 pillow 也能跑：手工构造一张最小 PNG 不可行（要画字母），
# 所以这里用纯 Python 生成 BMP 再转 PNG 太绕 —— 直接要求 pillow（沙箱/桌面一般都有）。
try:
    from PIL import Image, ImageDraw
except ImportError:
    print("需要 pillow：pip install pillow")
    sys.exit(1)


def make_test_png() -> str:
    """生成 256x128 红底白字 'JY' 图片，返回 data URL。"""
    img = Image.new("RGB", (256, 128), (200, 30, 30))
    d = ImageDraw.Draw(img)
    # 尽量大的字体画 JY
    try:
        from PIL import ImageFont
        font = None
        for size in (96, 72, 48, 32):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    d.text((128, 64), "JY", fill="white", font=font, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["ollama", "openai"], default="openai")
    ap.add_argument("--api-base", default="")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--vision-model", default="glm-4v-flash")
    ap.add_argument("--relay", default="http://127.0.0.1:5000",
                    help="已运行的中转服务地址（推荐方式）")
    args = ap.parse_args()

    import requests

    img = make_test_png()
    print(f"[1] 测试图已生成（红底白字 JY）")

    if args.backend == "openai":
        # 直连厂商验证视觉能力
        base = args.api_base.rstrip("/")
        if not base.endswith("/chat/completions"):
            base += "/chat/completions"
        r = requests.post(base, json={
            "model": args.vision_model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "图里写的是什么字母？只回答字母。"},
                {"type": "image_url", "image_url": {"url": img}},
            ]}],
            "max_tokens": 16,
        }, headers={"Authorization": f"Bearer {args.api_key}"}, timeout=60)
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        print(f"[2] {args.vision_model} 直连回答: {txt!r}")
        ok = "JY" in txt.upper().replace(" ", "")
        print(f"[3] 直连判定: {'✅ 模型看懂了图' if ok else '❌ 回答不含 JY，视觉链路有问题'}")

        if not ok:
            sys.exit(2)
        print("\n下一步：把 vision_model 配进中转服务控制台，然后用 OCS 实际答题验证。")
    else:
        # 本地：通过中转服务走完整链路（含路由）
        r = requests.post(f"{args.relay.rstrip('/')}/api/qa", json={
            "title": "图片里的字母是什么（作为选项参考）",
            "options": "A. XY\nB. JY\nC. AB",
            "type": "single",
            "images": [img],
        }, timeout=120)
        d = r.json()
        print(f"[2] 中转返回: answer={d.get('answer')!r} model={d.get('model')} route={d.get('route')}")
        ok = d.get("answer") and "JY" in str(d.get("answer")).upper()
        print(f"[3] 完整链路判定: {'✅ 通过' if ok else '❌ 未通过，检查 vision_model 是否安装'}")
        if not ok:
            sys.exit(2)


if __name__ == "__main__":
    main()
