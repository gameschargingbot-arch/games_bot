from cryptography.fernet import Fernet
print("Put this in your .env file:")
print("FERNET_KEY=" + Fernet.generate_key().decode())