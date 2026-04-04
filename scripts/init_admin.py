#!/usr/bin/env python3
"""Initialize admin user if not exists."""
import os
import time

from data.database import SessionFactory
from data.user.User import UserTable
from Auth import hash_password

phone = os.environ.get("ADMIN_PHONE", "admin")
password = os.environ.get("ADMIN_PASSWORD", "admin123")
name = os.environ.get("ADMIN_NAME", "Administrator")

with SessionFactory() as session:
    existing = session.query(UserTable).filter_by(phone=phone).first()
    if existing:
        print(f"Admin user ({phone}) already exists, skipping.")
    else:
        now = time.strftime("%Y-%m-%d %H:%M")
        admin = UserTable(
            phone=phone,
            name=name,
            password=hash_password(password),
            role="admin",
            status="approved",
            create_date=now,
            update_date=now,
        )
        session.add(admin)
        session.commit()
        print(f"Created admin user: {phone}")
