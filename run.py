"""Chạy trong GitHub Actions: nhắn tin cho từng người trong config.json bằng cookie TikTok."""
import json, os, random, re, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

LOGIN = '[data-e2e="top-login-button"]'
MSG_BTN = re.compile(r"^(message|nhắn tin|tin nhắn)$", re.I)
SAME = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict"}


def parse_cookies(raw):
    raw = raw.strip()
    if not raw:
        sys.exit("Thiếu secret COOKIES_JSON")
    if raw[0] not in "[{":  # chỉ dán giá trị sessionid
        return [{"name": n, "value": raw, "domain": ".tiktok.com", "path": "/", "secure": True}
                for n in ("sessionid", "sessionid_ss")]
    data = json.loads(raw)
    out = []
    for c in (data if isinstance(data, list) else [data]):
        item = {"name": c["name"], "value": c["value"], "domain": c.get("domain", ".tiktok.com"),
                "path": c.get("path", "/"), "secure": bool(c.get("secure", True)),
                "httpOnly": bool(c.get("httpOnly", False))}
        same = SAME.get(str(c.get("sameSite", "")).lower())
        if same:
            item["sameSite"] = same
        exp = c.get("expirationDate") or c.get("expires")
        if isinstance(exp, (int, float)) and exp > 0:
            item["expires"] = exp
        out.append(item)
    return out


def notify(text):
    url = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not url:
        return
    req = urllib.request.Request(url, json.dumps({"content": text}).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "streak-bot"})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print("Webhook lỗi:", e)


def main():
    cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
    targets, msg = cfg.get("targets", []), cfg.get("message") or "❤️"
    if not targets:
        sys.exit("config.json chưa có người nhận")
    cookies = parse_cookies(os.environ.get("COOKIES_JSON", ""))
    Path("shots").mkdir(exist_ok=True)
    ok, bad = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False,
                                    args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 800})
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto("https://www.tiktok.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        if page.locator(LOGIN).count():
            page.screenshot(path="shots/expired.png")
            notify("⚠️ Cookie TikTok đã hết hạn. Mở trang quản lý và lưu cookie mới.")
            print("SESSION_EXPIRED")
            sys.exit(2)

        for i, name in enumerate(targets):
            try:
                page.goto(f"https://www.tiktok.com/@{name}", wait_until="domcontentloaded")
                page.get_by_role("button", name=MSG_BTN).first.click(timeout=20000)
                box = page.locator('div[contenteditable="true"]').last
                box.wait_for(timeout=20000)
                box.click()
                page.wait_for_timeout(random.randint(500, 1500))
                page.keyboard.insert_text(msg)
                page.keyboard.press(cfg.get("sendKey", "Enter"))
                page.wait_for_timeout(2500)
                ok.append(name)
                print(f"OK   @{name}")
            except Exception as e:
                bad.append(name)
                page.screenshot(path=f"shots/{name}.png")
                print(f"FAIL @{name}: {type(e).__name__}")
            if i < len(targets) - 1:
                time.sleep(random.randint(15, 40))
        browser.close()

    notify(("✅ Đã gửi: " + ", ".join(ok) if ok else "") + ("\n❌ Lỗi: " + ", ".join(bad) if bad else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
