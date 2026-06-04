"""
Register an admin user in Vizor NVR.

Usage:
    cd backend
    python -m scripts.admin_register
"""

import sys
import os
import asyncio
import getpass

# Ensure the backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from app.database import async_session_maker, engine
from app.auth.models import User, Role, RoleName, ROLE_DEFAULTS
from app.core.security import hash_password


async def seed_admin_role(session):
    """Ensure the admin role exists."""
    result = await session.execute(
        select(Role).where(Role.name == RoleName.ADMIN.value)
    )
    role = result.scalar_one_or_none()
    if role:
        return role

    role = Role(
        name=RoleName.ADMIN.value,
        description="System admin role",
        permissions=ROLE_DEFAULTS[RoleName.ADMIN],
        is_system=True,
    )
    session.add(role)
    await session.flush()
    return role


async def register_admin():
    print("\n=== Vizor NVR — Admin Registration ===\n")

    username = input("Username: ").strip()
    if not username:
        print("Error: Username cannot be empty.")
        return

    email = input("Email: ").strip()
    if not email or "@" not in email:
        print("Error: Valid email is required.")
        return

    password = getpass.getpass("Password: ")
    if len(password) < 6:
        print("Error: Password must be at least 6 characters.")
        return

    confirm = getpass.getpass("Confirm Password: ")
    if password != confirm:
        print("Error: Passwords do not match.")
        return

    async with async_session_maker() as session:
        # Check if username or email already exists
        existing = await session.execute(
            select(User).where(
                (User.username == username) | (User.email == email)
            )
        )
        if existing.scalar_one_or_none():
            print(f"Error: User with username '{username}' or email '{email}' already exists.")
            return

        admin_role = await seed_admin_role(session)

        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role_id=admin_role.id,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        print(f"\nAdmin user '{username}' created successfully.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(register_admin())
