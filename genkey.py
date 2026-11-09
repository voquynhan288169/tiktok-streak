"""Chạy MỘT LẦN trên máy của chủ trang: tạo cặp khóa. pip install cryptography"""
from pathlib import Path
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric import rsa

k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
Path("data").mkdir(exist_ok=True)
Path("data/pubkey.pem").write_bytes(k.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo))
print("Đã tạo data/pubkey.pem (tải file này lên repo).")
print("Copy TOÀN BỘ khối dưới đây vào GitHub Secret tên PRIVATE_KEY, rồi xóa khỏi máy:\n")
print(k.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()).decode())
