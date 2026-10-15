import argparse
import getpass
import secrets
from uuid import uuid4
from cryptography.fernet import Fernet
from .db import engine, one, run
from .security import hasher


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['create-admin', 'generate-secrets'])
    parser.add_argument('--username', default='admin')
    args = parser.parse_args()
    if args.command == 'generate-secrets':
        print('APP_SECRET=' + secrets.token_urlsafe(48))
        print('CREDENTIAL_ENCRYPTION_KEY=' + Fernet.generate_key().decode())
        return
    password = getpass.getpass('New password (8+ characters): ')
    if len(password) < 8 or password != getpass.getpass('Repeat password: '):
        raise SystemExit('Password too short or mismatch')
    with engine().begin() as db:
        if one(db, 'SELECT id FROM users LIMIT 1'):
            raise SystemExit('An administrator already exists')
        run(db, 'INSERT INTO users(id,username,password_hash) VALUES (:id,:name,:password)',
            id=uuid4(), name=args.username, password=hasher.hash(password))
    print('Administrator created. Bind TOTP at first login.')


if __name__ == '__main__':
    main()
