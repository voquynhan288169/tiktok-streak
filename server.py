"""Chạy trong GitHub Actions. `python server.py process` xử lý yêu cầu từ Issue; `python server.py run` nhắn tin giữ chuỗi."""
import base64, hashlib, hmac, json, os, random, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

D = Path("data/accounts")
PEM = os.environ.get("PRIVATE_KEY", "")
NAME = re.compile(r"^[A-Za-z0-9._]{1,24}$")
LOGIN = '[data-e2e="top-login-button"]'
MSG_BTN = re.compile(r"^(message|nhắn tin|tin nhắn)$", re.I)


def fernet():  # khóa lưu trữ suy ra từ PRIVATE_KEY, chỉ Actions có
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(PEM.encode()).digest()))


def load(name):
    p = D / f"{name}.json"
    if not p.exists():
        return None
    j = json.loads(p.read_text(encoding="utf-8"))
    return j["pub"], json.loads(fernet().decrypt(j["blob"].encode()))


def save(name, pub, sec):
    D.mkdir(parents=True, exist_ok=True)
    blob = fernet().encrypt(json.dumps(sec).encode()).decode()
    (D / f"{name}.json").write_text(json.dumps({"pub": pub, "blob": blob}, ensure_ascii=False, indent=1), encoding="utf-8")


def write_index():
    rows = []
    for f in sorted(D.glob("*.json")) if D.exists() else []:
        rows.append({"name": f.stem, **json.loads(f.read_text(encoding="utf-8"))["pub"]})
    Path("data/index.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def pw_hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000).hex()


def clean(d):
    t = [str(x).lstrip("@") for x in d.get("targets", [])]
    return [x for x in dict.fromkeys(t) if NAME.match(x)][:10]


def check_cookie(c):
    if not re.fullmatch(r"[A-Za-z0-9%._-]{16,200}", c or ""):
        raise ValueError("Cookie không đúng: chỉ dán giá trị của sessionid.")


def handle(body):
    env = json.loads(body)
    priv = serialization.load_pem_private_key(PEM.encode(), None)
    key = priv.decrypt(base64.b64decode(env["k"]), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    d = json.loads(AESGCM(key).decrypt(base64.b64decode(env["i"]), base64.b64decode(env["c"]), None))
    created = datetime.fromisoformat(os.environ["ISSUE_CREATED"].replace("Z", "+00:00")).timestamp() * 1000
    if abs(created - d["ts"]) > 600_000:
        raise ValueError("Yêu cầu quá hạn, hãy gửi lại.")
    name, act, pw = d.get("name", ""), d.get("a"), d.get("pw", "")
    if not NAME.match(name) or len(pw) < 6:
        raise ValueError("Tên hoặc mật khẩu không hợp lệ (mật khẩu từ 6 ký tự).")
    cur = load(name)

    if act == "register":
        if cur:
            raise ValueError("Tài khoản này đã được đăng ký.")
        check_cookie(d.get("cookie"))
        salt = os.urandom(16)
        sec = {"cookie": d["cookie"], "salt": salt.hex(), "hash": pw_hash(pw, salt), "fails": 0, "lock": 0, "ts": d["ts"]}
        pub = {"active": True, "targets": clean(d), "message": d.get("message") or "❤️", "last_run": None, "last_status": "Chưa chạy"}
        save(name, pub, sec)
        return f"✅ Đã đăng ký @{name}. Tài khoản sẽ chạy ở lần tự động kế tiếp."

    if not cur:
        raise ValueError("Không có tài khoản này.")
    pub, sec = cur
    now = time.time()
    if now < sec["lock"]:
        raise ValueError("Tài khoản bị khóa tạm vì nhập sai nhiều lần. Thử lại sau 1 giờ.")
    if not hmac.compare_digest(pw_hash(pw, bytes.fromhex(sec["salt"])), sec["hash"]):
        sec["fails"] += 1
        if sec["fails"] >= 5:
            sec["fails"], sec["lock"] = 0, now + 3600
        save(name, pub, sec)
        raise ValueError("Sai mật khẩu.")
    if d["ts"] <= sec["ts"]:
        raise ValueError("Yêu cầu này đã được dùng rồi.")
    sec["fails"], sec["ts"] = 0, d["ts"]

    if act == "update":
        if d.get("cookie"):
            check_cookie(d["cookie"])
            sec["cookie"], pub["active"] = d["cookie"], True
        pub["targets"], pub["message"] = clean(d), d.get("message") or "❤️"
    elif act in ("stop", "start"):
        pub["active"] = act == "start"
    elif act == "delete":
        (D / f"{name}.json").unlink()
        return "🗑️ Đã xóa tài khoản."
    else:
        raise ValueError("Yêu cầu không hợp lệ.")
    save(name, pub, sec)
    return "✅ Đã cập nhật."


def process():
    try:
        reply = handle(os.environ["ISSUE_BODY"].strip())
    except ValueError as e:
        reply = "❌ " + str(e)
    except Exception:
        reply = "❌ Yêu cầu không hợp lệ."
    write_index()
    num = os.environ["ISSUE_NUMBER"]
    subprocess.run(["gh", "issue", "comment", num, "--body", reply])
    subprocess.run(["gh", "issue", "close", num])


def send_account(browser, name, cookie, targets, msg):
    ctx = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 800})
    try:
        ctx.add_cookies([{"name": n, "value": cookie, "domain": ".tiktok.com", "path": "/", "secure": True}
                         for n in ("sessionid", "sessionid_ss")])
        page = ctx.new_page()
        page.goto("https://www.tiktok.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        if page.locator(LOGIN).count():
            return "expired"
        bad = 0
        for i, t in enumerate(targets):
            try:
                page.goto(f"https://www.tiktok.com/@{t}", wait_until="domcontentloaded")
                page.get_by_role("button", name=MSG_BTN).first.click(timeout=20000)
                box = page.locator('div[contenteditable="true"]').last
                box.wait_for(timeout=20000)
                box.click()
                page.wait_for_timeout(random.randint(500, 1500))
                page.keyboard.insert_text(msg)
                page.keyboard.press("Enter")
                page.wait_for_timeout(2500)
            except Exception:
                bad += 1
                page.screenshot(path=f"shots/{name}-{t}.png")
            if i < len(targets) - 1:
                time.sleep(random.randint(15, 40))
        return "Thành công" if not bad else f"Lỗi {bad}/{len(targets)} người"
    finally:
        ctx.close()


def run():
    from playwright.sync_api import sync_playwright
    Path("shots").mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False,
                                    args=["--disable-blink-features=AutomationControlled"])
        for f in sorted(D.glob("*.json")) if D.exists() else []:
            name = f.stem
            pub, sec = load(name)
            if not pub["active"] or not pub["targets"]:
                continue
            status = send_account(browser, name, sec["cookie"], pub["targets"], pub["message"])
            pub["last_run"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
            if status == "expired":
                pub["active"], status = False, "Cookie hết hạn, hãy cập nhật cookie"
            pub["last_status"] = status
            save(name, pub, sec)
            time.sleep(random.randint(20, 60))
        browser.close()
    write_index()


if __name__ == "__main__":
    if not PEM:
        sys.exit("Thiếu secret PRIVATE_KEY")
    {"process": process, "run": run}[sys.argv[1]]()
