#!/usr/bin/env python3
import getpass
import argparse
from app import create_app, db
from app.models import User
from werkzeug.security import generate_password_hash

parser = argparse.ArgumentParser(description='Create or update a user and set role')
parser.add_argument('--email', required=True, help='User email')
parser.add_argument('--name', required=False, help='User name')
parser.add_argument('--password', required=False, help='Password (will prompt if omitted)')
parser.add_argument('--role', required=True, choices=['patient', 'doctor', 'admin'], help='Role to assign')

args = parser.parse_args()

app = create_app()
with app.app_context():
    user = User.query.filter_by(email=args.email).first()
    if not user:
        name = args.name or args.email.split('@')[0]
        password = args.password or getpass.getpass('Password: ')
        user = User(name=name, email=args.email, password_hash=generate_password_hash(password), role=args.role)
        db.session.add(user)
        db.session.commit()
        print(f'Created user {args.email} with role {args.role}')
    else:
        user.role = args.role
        if args.password:
            user.password_hash = generate_password_hash(args.password)
        db.session.commit()
        print(f'Updated user {args.email} to role {args.role}')
