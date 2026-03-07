from cryptography.fernet import Fernet

# 1. GENERATE A KEY (Run this ONCE and save the output somewhere safe!)
def generate_key():
    key = Fernet.generate_key()
    print(f"Your secret key is: {key.decode()}")
    return key

# 2. ENCRYPT & DECRYPT FUNCTIONS
def encrypt_data(data_string, secret_key):
    f = Fernet(secret_key)
    # Convert string to bytes, encrypt, and return as a string
    encrypted = f.encrypt(data_string.encode())
    return encrypted.decode()

def decrypt_data(encrypted_string, secret_key):
    f = Fernet(secret_key)
    # Convert string back to bytes, decrypt, and return the original string
    decrypted = f.decrypt(encrypted_string.encode())
    return decrypted.decode()

# --- Example Usage ---
# key = b'YOUR_GENERATED_KEY_HERE'
# encrypted_code = encrypt_data("25562189", key)
# print("Encrypted:", encrypted_code)
# print("Decrypted:", decrypt_data(encrypted_code, key))