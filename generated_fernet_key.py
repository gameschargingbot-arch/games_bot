import hashlib

from werkzeug.security import generate_password_hash, check_password_hash
hashed_pw = hashlib.sha256(str(6462476610).encode()).hexdigest()
print(hashed_pw)
